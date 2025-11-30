# youtub_downloader/routes.py
from flask import Blueprint, render_template, request, jsonify, send_file
import os
import tempfile
from pytube import YouTube
import pytube
import uuid
import time
import logging
import shutil
import re
import ffmpeg

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

youtube_bp = Blueprint('youtube_downloader', __name__, 
                      template_folder='templates',
                      static_folder='static')

# Armazenar downloads em andamento
downloads = {}


def convert_to_mp3(source_path):
    """Converte arquivo de áudio para MP3 usando ffmpeg."""
    base, _ = os.path.splitext(source_path)
    target_path = f"{base}.mp3"
    try:
        stream = ffmpeg.input(source_path)
        stream = ffmpeg.output(stream, target_path, audio_bitrate='192k', ac=2, ar=44100)
        ffmpeg.run(stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)
        os.remove(source_path)
        return target_path
    except Exception as exc:
        logger.warning(f"Falha ao converter para MP3: {exc}")
        return source_path

def extract_video_id(url):
    """Extrai ID do vídeo YouTube"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_video_info(url):
    """Obter informações básicas usando pytube."""
    try:
        yt = YouTube(url)
        upload_date = ''
        if yt.publish_date:
            upload_date = yt.publish_date.strftime('%Y%m%d')

        return {
            'success': True,
            'title': yt.title or 'Vídeo do YouTube',
            'thumbnail': yt.thumbnail_url or '',
            'duration': yt.length,
            'uploader': yt.author or 'Desconhecido',
            'view_count': yt.views or 0,
            'upload_date': upload_date,
            'webpage_url': yt.watch_url or url
        }

    except Exception as e:
        logger.error(f"Erro ao obter info: {e}")
        return {
            'success': False,
            'error': f'Erro ao analisar vídeo: {str(e)}'
        }

def _select_video_stream(yt, quality):
    """Seleciona o melhor stream progressivo de acordo com a qualidade desejada."""
    target_height = {
        '360': 360,
        '480': 480,
        '720': 720,
        'best': None
    }.get(quality, None)

    streams = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc()
    if not streams:
        return None

    if target_height is None:
        return streams.first()

    for stream in streams:
        if stream.resolution:
            try:
                height = int(stream.resolution.replace('p', ''))
                if height <= target_height:
                    return stream
            except ValueError:
                continue

    return streams.last()


def download_video_simple(url, quality='best', audio_only=False):
    """Download simples utilizando pytube."""
    try:
        temp_dir = tempfile.mkdtemp(prefix='navitools_ytdl_')
        yt = YouTube(url)

        if audio_only:
            stream = yt.streams.filter(only_audio=True).order_by('abr').desc().first()
            if not stream:
                return {'success': False, 'error': 'Stream de áudio não encontrado'}

            temp_file = stream.download(output_path=temp_dir, filename_prefix='audio_')
            final_path = convert_to_mp3(temp_file)
            filename = os.path.basename(final_path)
        else:
            stream = _select_video_stream(yt, quality)
            if not stream:
                return {'success': False, 'error': 'Stream de vídeo não encontrado'}

            final_path = stream.download(output_path=temp_dir, filename_prefix='video_')
            filename = os.path.basename(final_path)

        return {
            'success': True,
            'filepath': final_path,
            'filename': filename,
            'temp_dir': temp_dir
        }

    except Exception as e:
        logger.error(f"Erro no download: {e}")
        return {'success': False, 'error': str(e)}

@youtube_bp.route('/')
def youtube_home():
    """Página inicial"""
    return render_template('youtub_downloader.html')

@youtube_bp.route('/analyze', methods=['POST'])
def analyze_video():
    """Analisar vídeo e baixar diretamente"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        quality = data.get('quality', 'best')
        audio_only = data.get('audio_only', False)
        
        if not url:
            return jsonify({'success': False, 'error': 'URL é obrigatória'}), 400
            
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL deve ser do YouTube'}), 400
        
        # Gerar ID único para este download
        download_id = str(uuid.uuid4())
        
        # Obter informações do vídeo
        video_info = get_video_info(url)
        if not video_info['success']:
            return jsonify(video_info), 400
        
        # Iniciar download
        downloads[download_id] = {
            'status': 'downloading',
            'info': video_info,
            'started_at': time.time()
        }
        
        # Fazer download
        result = download_video_simple(url, quality, audio_only)
        
        if result['success']:
            downloads[download_id].update({
                'status': 'completed',
                'filepath': result['filepath'],
                'filename': result['filename'],
                'temp_dir': result['temp_dir']
            })
            
            return jsonify({
                'success': True,
                'download_id': download_id,
                'info': video_info,
                'message': 'Download concluído!'
            })
        else:
            downloads[download_id].update({
                'status': 'error',
                'error': result['error']
            })
            return jsonify(result), 500
            
    except Exception as e:
        logger.error(f"Erro em analyze: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@youtube_bp.route('/download-file/<download_id>')
def download_file(download_id):
    """Baixar arquivo finalizado"""
    try:
        download_info = downloads.get(download_id)
        
        if not download_info:
            return jsonify({'error': 'Download não encontrado'}), 404
            
        if download_info.get('status') != 'completed':
            return jsonify({'error': 'Download não finalizado'}), 400
            
        filepath = download_info.get('filepath')
        filename = download_info.get('filename')
        
        if not filepath or not os.path.exists(filepath):
            return jsonify({'error': 'Arquivo não encontrado'}), 404
        
        # Definir mimetype
        if filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        else:
            mimetype = 'application/octet-stream'
        
        # Enviar arquivo e limpar depois
        def cleanup():
            time.sleep(30)  # Aguardar download
            try:
                temp_dir = download_info.get('temp_dir')
                if temp_dir and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                if download_id in downloads:
                    del downloads[download_id]
            except:
                pass
        
        import threading
        cleanup_thread = threading.Thread(target=cleanup)
        cleanup_thread.daemon = True
        cleanup_thread.start()
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )
        
    except Exception as e:
        logger.error(f"Erro ao enviar arquivo: {e}")
        return jsonify({'error': str(e)}), 500

@youtube_bp.route('/test', methods=['GET'])
def test_system():
    """Testar sistema"""
    try:
        return jsonify({
            'success': True,
            'message': 'Sistema funcionando!',
            'pytube_version': pytube.__version__
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

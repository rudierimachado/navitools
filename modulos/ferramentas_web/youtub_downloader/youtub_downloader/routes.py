# youtub_downloader/routes.py
from flask import Blueprint, render_template, request, jsonify, send_file
import os
import tempfile
from pytubefix import YouTube
import pytubefix
import uuid
import time
import logging
import shutil
import re
import ffmpeg

# Logger do módulo (herda configuração global do app)
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
    """Obter informações usando pytubefix (mais estável que pytube)."""
    logger.info(f"Analisando URL com pytubefix: {url}")
    
    try:
        # Validar URL
        if not url or not ('youtube.com' in url or 'youtu.be' in url):
            return {
                'success': False,
                'error': 'URL deve ser do YouTube (youtube.com ou youtu.be)'
            }
        
        # pytubefix é mais simples e estável
        yt = YouTube(url)
        logger.info("Conectado ao YouTube com sucesso")
        
        # Obter informações básicas
        title = yt.title or 'Vídeo do YouTube'
        thumbnail = yt.thumbnail_url or ''
        duration = yt.length or 0
        author = yt.author or 'Desconhecido'
        views = yt.views or 0
        
        upload_date = ''
        if yt.publish_date:
            upload_date = yt.publish_date.strftime('%Y%m%d')

        logger.info(f"Vídeo analisado: {title} por {author}")
        
        return {
            'success': True,
            'title': title,
            'thumbnail': thumbnail,
            'duration': duration,
            'uploader': author,
            'view_count': views,
            'upload_date': upload_date,
            'webpage_url': url
        }

    except Exception as e:
        logger.error(f"Erro ao analisar vídeo: {e}")
        
        error_msg = str(e)
        if "unavailable" in error_msg.lower():
            error_msg = "Vídeo não disponível ou foi removido"
        elif "private" in error_msg.lower():
            error_msg = "Vídeo privado - não é possível acessar"
        elif "age" in error_msg.lower():
            error_msg = "Vídeo com restrição de idade"
        else:
            error_msg = "Erro ao acessar o vídeo. Verifique a URL."
            
        return {
            'success': False,
            'error': error_msg
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
    """Download usando pytubefix (mais estável)."""
    try:
        temp_dir = tempfile.mkdtemp(prefix='NEXUSRDR_ytdl_')
        yt = YouTube(url)
        logger.info(f"Iniciando download: {'áudio' if audio_only else 'vídeo'}")

        if audio_only:
            # Download de áudio
            stream = yt.streams.filter(only_audio=True).first()
            if not stream:
                stream = yt.streams.filter(adaptive=True, only_audio=True).first()
            
            if not stream:
                return {'success': False, 'error': 'Nenhum stream de áudio disponível'}

            logger.info(f"Stream de áudio selecionado: {stream}")
            temp_file = stream.download(output_path=temp_dir, filename_prefix='audio_')
            
            # Tentar converter para MP3
            try:
                final_path = convert_to_mp3(temp_file)
            except:
                final_path = temp_file
                logger.warning("Mantendo formato original (conversão MP3 falhou)")
                
            filename = os.path.basename(final_path)
        else:
            # Download de vídeo
            if quality == 'best':
                stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
            else:
                stream = yt.streams.filter(progressive=True, file_extension='mp4', res=f'{quality}p').first()
            
            # Fallback para qualquer stream disponível
            if not stream:
                stream = yt.streams.filter(progressive=True).first()
            
            if not stream:
                return {'success': False, 'error': 'Nenhum stream de vídeo disponível'}

            logger.info(f"Stream de vídeo selecionado: {stream}")
            final_path = stream.download(output_path=temp_dir, filename_prefix='video_')
            filename = os.path.basename(final_path)

        logger.info(f"Download concluído: {filename}")
        return {
            'success': True,
            'filepath': final_path,
            'filename': filename,
            'temp_dir': temp_dir
        }

    except Exception as e:
        logger.error(f"Erro no download: {e}")
        
        error_msg = str(e)
        if "unavailable" in error_msg.lower():
            error_msg = "Vídeo não disponível para download"
        elif "private" in error_msg.lower():
            error_msg = "Vídeo privado - não é possível baixar"
        else:
            error_msg = "Erro no download. Tente novamente."
            
        return {'success': False, 'error': error_msg}

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
        # Testar URL de exemplo
        test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Rick Roll - vídeo público conhecido
        
        logger.info("Testando sistema YouTube Downloader...")
        logger.info(f"Versão do pytubefix: {pytubefix.__version__}")
        
        # Testar análise de vídeo
        result = get_video_info(test_url)
        
        return jsonify({
            'success': True,
            'message': 'Sistema funcionando!',
            'pytubefix_version': pytubefix.__version__,
            'test_result': result
        })
    except Exception as e:
        logger.error(f"Erro no teste do sistema: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@youtube_bp.route('/debug', methods=['POST'])
def debug_url():
    """Endpoint para debug de URLs específicas"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL é obrigatória'}), 400
        
        logger.info(f"=== DEBUG URL: {url} ===")
        
        # Testar análise detalhada
        result = get_video_info(url)
        
        return jsonify({
            'success': True,
            'debug_result': result,
            'url_tested': url
        })
        
    except Exception as e:
        logger.error(f"Erro no debug: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

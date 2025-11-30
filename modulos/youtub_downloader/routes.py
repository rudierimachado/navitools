# youtub_downloader/routes.py
from flask import Blueprint, render_template, request, jsonify, send_file
import os
import tempfile
import yt_dlp
import uuid
import time
import logging
import shutil
import re

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

youtube_bp = Blueprint('youtube_downloader', __name__, 
                      template_folder='templates',
                      static_folder='static')

# Armazenar downloads em andamento
downloads = {}

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
    """Obter informações do vídeo de forma simples"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            return {
                'success': True,
                'title': info.get('title', 'Vídeo do YouTube'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Desconhecido'),
                'view_count': info.get('view_count', 0),
                'upload_date': info.get('upload_date', ''),
                'webpage_url': info.get('webpage_url', url)
            }
            
    except Exception as e:
        logger.error(f"Erro ao obter info: {e}")
        return {
            'success': False,
            'error': f'Erro ao analisar vídeo: {str(e)}'
        }

def download_video_simple(url, quality='best', audio_only=False):
    """Download simples e direto"""
    try:
        # Criar diretório temporário
        temp_dir = tempfile.mkdtemp(prefix='navitools_ytdl_')
        
        # Configurar opções básicas
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'restrictfilenames': True,
            'no_warnings': True,
        }
        
        if audio_only:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'extractaudio': True,
                'audioformat': 'mp3',
                'audioquality': '192K',
            })
        else:
            # Configurar qualidade de vídeo
            if quality == '720':
                ydl_opts['format'] = 'best[height<=720]'
            elif quality == '480':
                ydl_opts['format'] = 'best[height<=480]'
            elif quality == '360':
                ydl_opts['format'] = 'best[height<=360]'
            else:
                ydl_opts['format'] = 'best[height<=1080]'
        
        # Fazer download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Encontrar arquivo baixado
        files = os.listdir(temp_dir)
        if files:
            filepath = os.path.join(temp_dir, files[0])
            return {
                'success': True,
                'filepath': filepath,
                'filename': files[0],
                'temp_dir': temp_dir
            }
        else:
            return {'success': False, 'error': 'Arquivo não foi criado'}
            
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
            'yt_dlp_version': yt_dlp.version.__version__
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# youtub_downloader/routes.py
from flask import Blueprint, render_template, request, jsonify, send_file
import os
import tempfile
import yt_dlp
import uuid
import time
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

youtube_bp = Blueprint('youtube_downloader', __name__, 
                      template_folder='templates',
                      static_folder='static')

# Armazenar downloads em andamento
downloads = {}

@youtube_bp.route('/')
def youtube_home():
    return render_template('youtub_downloader.html', 
                         quality_options=YouTubeConfig.QUALITY_OPTIONS)

@youtube_bp.route('/test', methods=['GET'])
def test_route():
    return jsonify({
        'success': True,
        'message': 'Sistema funcionando!',
        'yt_dlp_version': yt_dlp.version.__version__,
        'ffmpeg_available': YouTubeConfig.FFMPEG_PATH is not None,
        'cache_enabled': True,
        'features': ['instant_thumbnail', 'fast_analysis', 'optimized_download']
    })

@youtube_bp.route('/instant-info', methods=['POST'])
def get_instant_info():
    """Informações instantâneas ao colar URL"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL é obrigatória'}), 400
            
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL deve ser do YouTube'}), 400
        
        # Análise instantânea
        info = extract_instant_info(url)
        return jsonify(info)
        
    except Exception as e:
        logger.error(f"Erro em instant-info: {e}")
        return jsonify({'success': False, 'error': f'Erro: {str(e)}'}), 500

@youtube_bp.route('/quick-info', methods=['POST'])
def get_quick_video_info():
    """Análise rápida otimizada"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL é obrigatória'}), 400
            
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL deve ser do YouTube'}), 400
        
        # Tentar cache primeiro
        cached_info = YouTubeConfig.get_cached_info(url)
        if cached_info and not cached_info.get('instant'):
            return jsonify(cached_info)
        
        # Análise completa
        complete_info = extract_complete_info(url)
        return jsonify(complete_info)
        
    except Exception as e:
        logger.error(f"Erro em quick-info: {e}")
        return jsonify({'success': False, 'error': f'Erro: {str(e)}'}), 500

@youtube_bp.route('/info', methods=['POST'])
def get_video_info():
    """Análise completa para formatos detalhados"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL é obrigatória'}), 400
            
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL deve ser do YouTube'}), 400
        
        info = extract_complete_info(url)
        return jsonify(info)
        
    except Exception as e:
        logger.error(f"Erro em info: {e}")
        return jsonify({'success': False, 'error': f"Erro ao processar URL: {str(e)}"}), 500

@youtube_bp.route('/download', methods=['POST'])
def download_video():
    """Download otimizado"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        quality = data.get('quality', 'best')
        audio_only = data.get('audio_only', False)
        
        if not url:
            return jsonify({'success': False, 'error': 'URL é obrigatória'}), 400
            
        download_id = str(uuid.uuid4())
        
        download_progress[download_id] = {
            'status': 'starting',
            'percent': '0%',
            'percent_float': 0,
            'speed': 'N/A',
            'eta': 'N/A',
            'started_at': time.time(),
            'temp_dir': None,
            'url': url,
            'quality': quality,
            'audio_only': audio_only
        }
        
        # Executar download em thread separada
        future = download_executor.submit(perform_download, url, quality, audio_only, download_id)
        
        return jsonify({
            'success': True,
            'download_id': download_id,
            'message': 'Download iniciado!'
        })
        
    except Exception as e:
        logger.error(f"Erro ao iniciar download: {e}")
        return jsonify({'success': False, 'error': f"Erro ao iniciar download: {str(e)}"}), 500

def perform_download(url, quality, audio_only, download_id):
    """Realizar download com retry"""
    temp_dir = None
    max_retries = 2
    
    try:
        # Criar diretório temporário
        temp_dir = tempfile.mkdtemp(prefix=YouTubeConfig.TEMP_PREFIX)
        
        # Atualizar progresso
        download_progress[download_id].update({
            'status': 'preparing',
            'temp_dir': temp_dir
        })
        
        # Configurar opções de download
        ydl_opts = get_ydl_opts(quality, audio_only, output_dir=temp_dir)
        ydl_opts['progress_hooks'] = [ProgressHook(download_id)]
        
        # Adicionar configurações extras
        ydl_opts.update({
            'concurrent_fragment_downloads': 2,
            'http_chunk_size': 10485760,  # 10MB
        })
        
        # Tentar download
        for attempt in range(max_retries):
            try:
                download_progress[download_id]['attempt'] = attempt + 1
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # Download bem-sucedido
                break
                
            except Exception as e:
                logger.error(f"Erro na tentativa {attempt + 1}: {e}")
                
                if attempt == max_retries - 1:
                    # Última tentativa falhou
                    download_progress[download_id].update({
                        'status': 'error',
                        'error': str(e)
                    })
                    return
                else:
                    # Aguardar antes da próxima tentativa
                    time.sleep(3)
        
        # Verificar se o arquivo foi criado
        if download_progress[download_id].get('status') != 'finished':
            download_progress[download_id].update({
                'status': 'error',
                'error': 'Download não foi concluído corretamente'
            })
    
    except Exception as e:
        logger.error(f"Erro geral no download {download_id}: {e}")
        download_progress[download_id].update({
            'status': 'error',
            'error': str(e)
        })
    
    finally:
        # Cleanup em caso de erro
        if download_progress[download_id].get('status') == 'error' and temp_dir:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass

@youtube_bp.route('/progress/<download_id>')
def get_download_progress(download_id):
    """Obter progresso do download"""
    progress = download_progress.get(download_id, {
        'status': 'not_found',
        'error': 'Download não encontrado'
    })
    
    # Adicionar tempo decorrido
    if 'started_at' in progress:
        elapsed = time.time() - progress['started_at']
        progress['elapsed'] = f"{int(elapsed)}s"
    
    return jsonify(progress)

@youtube_bp.route('/download-file/<download_id>')
def download_file(download_id):
    """Baixar arquivo finalizado"""
    try:
        progress = download_progress.get(download_id)
        
        if not progress:
            return jsonify({'error': 'Download não encontrado'}), 404
            
        if progress.get('status') != 'finished':
            return jsonify({'error': f'Download não finalizado. Status: {progress.get("status")}'}), 400
            
        filepath = progress.get('filepath')
        
        if not filepath or not os.path.exists(filepath):
            return jsonify({'error': 'Arquivo não encontrado'}), 404
            
        filename = progress.get('filename', 'video')
        
        # Definir mimetype
        if filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.endswith('.webm'):
            mimetype = 'video/webm'
        else:
            mimetype = 'application/octet-stream'
        
        # Enviar arquivo
        response = send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )
        
        # Agendar cleanup
        def delayed_cleanup():
            time.sleep(20)  # Aguardar download
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                temp_dir = progress.get('temp_dir')
                if temp_dir and os.path.isdir(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                if download_id in download_progress:
                    del download_progress[download_id]
            except Exception as e:
                logger.error(f"Erro no cleanup: {e}")
                
        cleanup_thread = threading.Thread(target=delayed_cleanup)
        cleanup_thread.daemon = True
        cleanup_thread.start()
        
        return response
        
    except Exception as e:
        logger.error(f"Erro ao enviar arquivo: {e}")
        return jsonify({'error': f"Erro ao baixar arquivo: {str(e)}"}), 500

@youtube_bp.route('/cancel/<download_id>', methods=['POST'])
def cancel_download(download_id):
    """Cancelar download"""
    if download_id in download_progress:
        download_progress[download_id]['status'] = 'cancelled'
        return jsonify({'success': True, 'message': 'Download cancelado'})
    
    return jsonify({'success': False, 'error': 'Download não encontrado'}), 404

@youtube_bp.route('/cleanup', methods=['POST'])
def cleanup_files():
    """Limpeza do sistema"""
    try:
        cleaned_dirs = 0
        current_time = time.time()
        
        # Limpar diretórios temporários antigos
        temp_root = tempfile.gettempdir()
        for entry in os.listdir(temp_root):
            if not entry.startswith(YouTubeConfig.TEMP_PREFIX):
                continue
                
            temp_path = os.path.join(temp_root, entry)
            if not os.path.isdir(temp_path):
                continue
                
            try:
                dir_age = current_time - os.path.getctime(temp_path)
                if dir_age > 3600:  # 1 hora
                    shutil.rmtree(temp_path, ignore_errors=True)
                    cleaned_dirs += 1
            except:
                pass
        
        # Limpar downloads antigos
        old_downloads = []
        for download_id, progress in list(download_progress.items()):
            if 'started_at' in progress:
                if current_time - progress['started_at'] > 7200:  # 2 horas
                    old_downloads.append(download_id)
        
        for download_id in old_downloads:
            try:
                del download_progress[download_id]
            except:
                pass
        
        # Limpar cache
        YouTubeConfig.cleanup_old_cache()
        
        return jsonify({
            'success': True,
            'cleaned_dirs': cleaned_dirs,
            'cleaned_progress': len(old_downloads),
            'message': 'Limpeza concluída'
        })
        
    except Exception as e:
        logger.error(f"Erro na limpeza: {e}")
        return jsonify({'success': False, 'error': f"Erro na limpeza: {str(e)}"}), 500

@youtube_bp.route('/stats')
def get_stats():
    """Estatísticas do sistema"""
    try:
        active_downloads = len([p for p in download_progress.values() 
                              if p.get('status') in ['downloading', 'preparing']])
        
        return jsonify({
            'success': True,
            'stats': {
                'active_downloads': active_downloads,
                'total_tracked': len(download_progress),
                'cache_size': len(YouTubeConfig._memory_cache),
                'ffmpeg_available': YouTubeConfig.FFMPEG_PATH is not None,
                'yt_dlp_version': yt_dlp.version.__version__,
                'system_status': 'operational'
            }
        })
    
    except Exception as e:
        logger.error(f"Erro ao obter stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
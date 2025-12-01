# youtub_downloader/config.py
import os
import yt_dlp
import tempfile
import re
import time
import shutil
from pathlib import Path

class YouTubeConfig:
    # Diretórios
    TEMP_PREFIX = 'NEXUSRDR_ytdl_'
    BASE_DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "youtube_downloads"
    
    # Cache simples em memória (sem Redis)
    _memory_cache = {}
    CACHE_TTL = 1800  # 30 minutos
    
    # FFmpeg - busca automática
    FFMPEG_PATH = None
    
    def __init__(self):
        self.setup_directories()
        self.setup_ffmpeg()
    
    @classmethod
    def setup_directories(cls):
        """Criar diretórios necessários"""
        cls.BASE_DOWNLOAD_DIR.mkdir(exist_ok=True)
    
    @classmethod
    def setup_ffmpeg(cls):
        """Configurar FFmpeg automaticamente"""
        cls.FFMPEG_PATH = cls.find_ffmpeg()
        if cls.FFMPEG_PATH:
            print(f"✅ FFmpeg encontrado: {cls.FFMPEG_PATH}")
        else:
            print("⚠️ FFmpeg não encontrado - funcionalidade limitada")
    
    @staticmethod
    def find_ffmpeg():
        """Encontra FFmpeg automaticamente"""
        ffmpeg_path = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
        if ffmpeg_path:
            return ffmpeg_path
        
        # Buscar em locais comuns
        common_paths = [
            '/usr/bin/ffmpeg',
            '/usr/local/bin/ffmpeg',
            'C:\\ffmpeg\\bin\\ffmpeg.exe',
            'C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe'
        ]
        
        for path in common_paths:
            if os.path.isfile(path):
                return path
        
        return None
    
    # Configurações otimizadas para 2024
    YDL_OPTS_BASE = {
        'restrictfilenames': True,
        'no_warnings': False,
        'ignoreerrors': False,
        'format_sort': ['res', 'ext:mp4:m4a'],
        'writesubtitles': False,
        'writeautomaticsub': False,
        'embed_subs': False,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'socket_timeout': 30,
        'retries': 3,
        'fragment_retries': 3,
        'extractor_retries': 3,
        'http_chunk_size': 10485760,  # 10MB
        'concurrent_fragment_downloads': 4,
    }
    
    QUALITY_OPTIONS = {
        'best': {'name': '🎯 Melhor Qualidade', 'format': 'best[height<=1080]'},
        'high': {'name': '📺 Alta (720p)', 'format': 'best[height<=720]'},
        'medium': {'name': '📱 Média (480p)', 'format': 'best[height<=480]'},
        'low': {'name': '💾 Baixa (360p)', 'format': 'best[height<=360]'},
        'audio': {'name': '🎵 Apenas Áudio (MP3)', 'format': 'bestaudio/best'}
    }

    @staticmethod
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
    
    @staticmethod
    def get_instant_thumbnail(video_id):
        """Thumbnail instantâneo"""
        if not video_id:
            return None
        return f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'
    
    @staticmethod
    def get_cached_info(url):
        """Cache simples em memória"""
        cache_key = f"yt_info:{hash(url)}"
        if cache_key in YouTubeConfig._memory_cache:
            cached_data, timestamp = YouTubeConfig._memory_cache[cache_key]
            if time.time() - timestamp < YouTubeConfig.CACHE_TTL:
                return cached_data
            else:
                del YouTubeConfig._memory_cache[cache_key]
        return None
    
    @staticmethod
    def cache_info(url, info):
        """Armazenar no cache"""
        cache_key = f"yt_info:{hash(url)}"
        YouTubeConfig._memory_cache[cache_key] = (info, time.time())
    
    @staticmethod
    def cleanup_old_cache():
        """Limpar cache antigo"""
        current_time = time.time()
        expired_keys = []
        
        for cache_key, (data, timestamp) in YouTubeConfig._memory_cache.items():
            if current_time - timestamp > YouTubeConfig.CACHE_TTL:
                expired_keys.append(cache_key)
        
        for key in expired_keys:
            del YouTubeConfig._memory_cache[key]

def get_ydl_opts(quality='best', audio_only=False, output_dir=None):
    """Opções otimizadas para download"""
    opts = YouTubeConfig.YDL_OPTS_BASE.copy()
    
    if output_dir:
        opts['outtmpl'] = os.path.join(output_dir, '%(title)s.%(ext)s')
    else:
        opts['outtmpl'] = os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s')
    
    # Configurar FFmpeg se disponível
    if YouTubeConfig.FFMPEG_PATH:
        opts['ffmpeg_location'] = YouTubeConfig.FFMPEG_PATH
    
    if audio_only:
        opts.update({
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'audioquality': '192K',
        })
        
        # Usar FFmpeg se disponível
        if YouTubeConfig.FFMPEG_PATH:
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
    else:
        # Formato de vídeo
        format_selector = YouTubeConfig.QUALITY_OPTIONS.get(quality, {'format': 'best'})['format']
        
        if YouTubeConfig.FFMPEG_PATH:
            # Se tem FFmpeg, pode mesclar vídeo e áudio
            opts['format'] = f'{format_selector}+bestaudio[ext=m4a]/best[ext=mp4]/best'
            opts['merge_output_format'] = 'mp4'
        else:
            # Sem FFmpeg, baixar formato único
            opts['format'] = f'{format_selector}[ext=mp4]/best[ext=mp4]/best'
    
    return opts

def extract_instant_info(url):
    """Informações instantâneas via ID do vídeo"""
    video_id = YouTubeConfig.extract_video_id(url)
    if not video_id:
        return {'success': False, 'error': 'URL inválida'}
    
    # Verificar cache primeiro
    cached = YouTubeConfig.get_cached_info(url)
    if cached:
        cached['cached'] = True
        return cached
    
    # Informações básicas instantâneas
    thumbnail = YouTubeConfig.get_instant_thumbnail(video_id)
    clean_url = f'https://www.youtube.com/watch?v={video_id}'
    
    return {
        'success': True,
        'video_id': video_id,
        'thumbnail': thumbnail,
        'webpage_url': clean_url,
        'instant': True,
        'title': 'Analisando...',
        'uploader': 'Carregando...',
        'duration': 0,
        'view_count': 0,
        'upload_date': ''
    }

def extract_complete_info(url):
    """Análise completa com yt-dlp otimizado"""
    # Verificar cache primeiro
    cached = YouTubeConfig.get_cached_info(url)
    if cached and not cached.get('instant', False):
        return cached
    
    # Configuração otimizada
    ydl_opts = {
        'quiet': True,
        'no_warnings': False,
        'extract_flat': False,
        'skip_download': True,
        'socket_timeout': 30,
        'retries': 3,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'writeinfojson': False,
        'writethumbnail': False,
        'ignoreerrors': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Extrair formatos disponíveis
            formats = []
            if 'formats' in info and info['formats']:
                seen_heights = set()
                for f in info.get('formats', [])[:30]:  # Limitar análise
                    if (f.get('vcodec') != 'none' and 
                        f.get('height') and 
                        f.get('height') not in seen_heights and 
                        f.get('height') <= 1080):
                        
                        height = f['height']
                        formats.append({
                            'height': height,
                            'ext': f.get('ext', 'mp4'),
                            'filesize': f.get('filesize', 0),
                            'format_id': f['format_id'],
                            'fps': f.get('fps', 30)
                        })
                        seen_heights.add(height)
            
            formats.sort(key=lambda x: x['height'], reverse=True)
            
            result = {
                'success': True,
                'title': info.get('title', 'Vídeo do YouTube'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Desconhecido'),
                'view_count': info.get('view_count', 0),
                'upload_date': info.get('upload_date', ''),
                'description': (info.get('description', '')[:200] + '...') if info.get('description') else '',
                'formats': formats,
                'is_live': info.get('is_live', False),
                'webpage_url': info.get('webpage_url', url),
                'cached': False,
                'ffmpeg_available': YouTubeConfig.FFMPEG_PATH is not None
            }
            
            # Salvar no cache
            YouTubeConfig.cache_info(url, result)
            return result
            
    except Exception as e:
        return {
            'success': False,
            'error': f'Erro ao analisar vídeo: {str(e)}'
        }

# Inicializar configuração
YouTubeConfig.setup_directories()
YouTubeConfig.setup_ffmpeg()
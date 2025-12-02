import os
from pathlib import Path

class Config:
    """Configurações do módulo Removedor De Fundo"""
    
    # Diretórios
    BASE_DIR = Path(__file__).parent
    UPLOAD_DIR = BASE_DIR / "uploads"
    PROCESSED_DIR = BASE_DIR / "processed" 
    STATIC_DIR = BASE_DIR / "static"
    
    # Configurações de upload
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    MAX_FILES_PER_BATCH = 20
    MAX_REQUESTS_PER_IP = 30  # por hora
    MAX_LIFETIME_SECONDS = 10 * 60  # 10 minutos
    
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}
    
    # Modelos AI disponíveis
    AI_MODELS = {
        'u2net': 'U²-Net (Geral - Recomendado)',
        'u2net_human_seg': 'U²-Net Human (Pessoas)',
        'u2net_cloth_seg': 'U²-Net Cloth (Roupas)',
        'silueta': 'Silueta (Rápido)',
        'isnet-general-use': 'ISNet (Alta qualidade)',
    }
    
    # Formatos de saída
    OUTPUT_FORMATS = {
        'transparent': 'PNG Transparente',
        'white': 'Fundo Branco',
        'black': 'Fundo Preto',
        'custom': 'Cor Personalizada'
    }
    
    # Criar diretórios se não existirem
    @classmethod
    def create_directories(cls):
        for dir_path in [cls.UPLOAD_DIR, cls.PROCESSED_DIR]:
            dir_path.mkdir(exist_ok=True)

def allowed_file(filename):
    """Verifica se o arquivo tem extensão permitida"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def get_unique_filename(filename):
    """Gera nome único para o arquivo"""
    import uuid
    ext = filename.rsplit('.', 1)[1].lower()
    return f"{uuid.uuid4().hex}.{ext}"
import os
from pathlib import Path

class Config:
    """Configurações completas do Removedor de Fundo Ultra Otimizado"""
    
    # ========================================
    # CONFIGURAÇÕES BÁSICAS
    # ========================================
    
    # Diretórios
    BASE_DIR = Path(__file__).parent
    UPLOAD_DIR = BASE_DIR / "uploads"
    PROCESSED_DIR = BASE_DIR / "processed" 
    STATIC_DIR = BASE_DIR / "static"
    TEMP_DIR = BASE_DIR / "temp"
    
    # Configurações de upload
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # 32MB
    MAX_FILES_PER_BATCH = 8
    MAX_REQUESTS_PER_IP = 25  # por hora
    MAX_LIFETIME_SECONDS = 15 * 60  # 15 minutos
    
    # Extensões permitidas
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff'}
    
    # ========================================
    # MODELOS DE IA OTIMIZADOS (REMBG)
    # ========================================
    
    AI_MODELS = {
        'isnet-general-use': {
            'name': 'ISNet (Máxima Qualidade)',
            'description': 'Estado da arte para qualquer objeto',
            'speed': 'Médio',
            'quality': 'Excelente',
            'best_for': 'Objetos complexos, máxima precisão',
            'recommended': True,
            'category': 'premium'
        },
        'u2net': {
            'name': 'U²-Net (Balanceado)',  
            'description': 'Ótimo equilíbrio qualidade/velocidade',
            'speed': 'Rápido',
            'quality': 'Muito Boa',
            'best_for': 'Uso geral, objetos diversos',
            'recommended': True,
            'category': 'balanced'
        },
        'u2net_human_seg': {
            'name': 'U²-Net Pessoas (Retratos)',
            'description': 'Especializado em pessoas e retratos',
            'speed': 'Rápido', 
            'quality': 'Excelente para pessoas',
            'best_for': 'Fotos de pessoas, retratos, selfies',
            'recommended': True,
            'category': 'people'
        },
        'u2net_cloth_seg': {
            'name': 'U²-Net Roupas',
            'description': 'Focado em tecidos e roupas',
            'speed': 'Rápido',
            'quality': 'Excelente para roupas',
            'best_for': 'Roupas, tecidos, moda',
            'recommended': False,
            'category': 'specialized'
        },
        'u2netp': {
            'name': 'U²-Net Leve (Ultra Rápido)',
            'description': 'Versão otimizada para velocidade',
            'speed': 'Muito Rápido',
            'quality': 'Boa',
            'best_for': 'Processamento em massa, testes',
            'recommended': False,
            'category': 'fast'
        },
        'silueta': {
            'name': 'Silueta (Instantâneo)',
            'description': 'Silhuetas básicas muito rápidas',
            'speed': 'Instantâneo',
            'quality': 'Básica',
            'best_for': 'Silhuetas simples, protótipos',
            'recommended': False,
            'category': 'basic'
        }
    }
    
    # ========================================
    # CONFIGURAÇÕES DE QUALIDADE ULTRA
    # ========================================
    
    QUALITY_PRESETS = {
        'maxima': {
            'name': 'Qualidade Máxima',
            'description': 'Melhor qualidade possível (mais lento)',
            'icon': '🔥',
            'processing_time': '15-30s',
            'settings': {
                'max_resolution': 2048,
                'alpha_matting': True,
                'alpha_matting_foreground_threshold': 270,
                'alpha_matting_background_threshold': 5,
                'alpha_matting_erode_structure_size': 15,
                'alpha_matting_base_size': 2000,
                'alpha_matting_erosion_size': 3,
                'edge_enhancement': True,
                'noise_reduction': True,
                'post_processing': True,
                'bilateral_filter': True,
                'morphology_operations': True
            }
        },
        'alta': {
            'name': 'Alta Qualidade', 
            'description': 'Excelente qualidade (recomendado)',
            'icon': '⭐',
            'processing_time': '8-15s',
            'settings': {
                'max_resolution': 1536,
                'alpha_matting': True,
                'alpha_matting_foreground_threshold': 250,
                'alpha_matting_background_threshold': 8,
                'alpha_matting_erode_structure_size': 12,
                'alpha_matting_base_size': 1500,
                'alpha_matting_erosion_size': 2,
                'edge_enhancement': True,
                'noise_reduction': False,
                'post_processing': True,
                'bilateral_filter': True,
                'morphology_operations': False
            }
        },
        'media': {
            'name': 'Qualidade Média',
            'description': 'Boa qualidade e velocidade',
            'icon': '⚡',
            'processing_time': '3-8s',
            'settings': {
                'max_resolution': 1024,
                'alpha_matting': True,
                'alpha_matting_foreground_threshold': 240,
                'alpha_matting_background_threshold': 10,
                'alpha_matting_erode_structure_size': 10,
                'alpha_matting_base_size': 1000,
                'edge_enhancement': False,
                'noise_reduction': False,
                'post_processing': False,
                'bilateral_filter': False,
                'morphology_operations': False
            }
        },
        'rapida': {
            'name': 'Processamento Rápido',
            'description': 'Máxima velocidade',
            'icon': '🚀',
            'processing_time': '1-3s',
            'settings': {
                'max_resolution': 768,
                'alpha_matting': False,
                'edge_enhancement': False,
                'noise_reduction': False,
                'post_processing': False,
                'bilateral_filter': False,
                'morphology_operations': False
            }
        }
    }
    
    # ========================================
    # FORMATOS DE SAÍDA
    # ========================================
    
    OUTPUT_FORMATS = {
        'transparent': {
            'name': 'PNG Transparente',
            'description': 'Fundo transparente (recomendado)',
            'extension': 'png',
            'quality': 100,
            'supports_transparency': True
        },
        'white': {
            'name': 'Fundo Branco',
            'description': 'Fundo branco sólido',
            'extension': 'jpg',
            'quality': 95,
            'supports_transparency': False,
            'background_color': (255, 255, 255)
        },
        'black': {
            'name': 'Fundo Preto',
            'description': 'Fundo preto sólido',
            'extension': 'jpg',
            'quality': 95,
            'supports_transparency': False,
            'background_color': (0, 0, 0)
        },
        'custom': {
            'name': 'Cor Personalizada',
            'description': 'Escolha sua cor de fundo',
            'extension': 'jpg',
            'quality': 95,
            'supports_transparency': False,
            'background_color': None  # Será definido pelo usuário
        },
        'gradient': {
            'name': 'Gradiente Elegante',
            'description': 'Fundo gradiente automático',
            'extension': 'jpg',
            'quality': 95,
            'supports_transparency': False,
            'background_color': 'gradient'
        }
    }
    
    # ========================================
    # CONFIGURAÇÕES AVANÇADAS DE PROCESSAMENTO
    # ========================================
    
    PROCESSING_OPTIONS = {
        'pre_processing': {
            'contrast_enhancement': True,
            'noise_reduction_models': ['maxima'],
            'edge_sharpening': ['alta', 'maxima'],
            'adaptive_resize': True,
            'optimal_size_multiple': 32  # Múltiplos de 32 funcionam melhor
        },
        'rembg_optimization': {
            'use_gpu': True,  # Quando disponível
            'model_cache': True,
            'session_reuse': True,
            'memory_optimization': True
        },
        'post_processing': {
            'edge_smoothing': ['alta', 'maxima'],
            'hole_filling': ['maxima'],
            'alpha_refinement': ['alta', 'maxima'],
            'final_resize_algorithm': 'LANCZOS'
        }
    }
    
    # ========================================
    # CONFIGURAÇÕES DE PERFORMANCE
    # ========================================
    
    PERFORMANCE_SETTINGS = {
        'batch_processing': {
            'max_concurrent': 3,
            'queue_timeout': 300,  # 5 minutos
            'memory_cleanup_interval': 600  # 10 minutos
        },
        'caching': {
            'model_cache_size': 3,  # Manter 3 modelos em cache
            'result_cache_ttl': 3600,  # 1 hora
            'temp_file_cleanup': True
        },
        'monitoring': {
            'log_processing_times': True,
            'track_memory_usage': True,
            'error_reporting': True
        }
    }
    
    # ========================================
    # CONFIGURAÇÕES DE SEGURANÇA
    # ========================================
    
    SECURITY_SETTINGS = {
        'file_validation': {
            'check_file_headers': True,
            'max_file_size': MAX_CONTENT_LENGTH,
            'allowed_mime_types': [
                'image/jpeg', 'image/jpg', 'image/png', 
                'image/webp', 'image/bmp', 'image/tiff'
            ],
            'scan_for_malware': False  # Implementar se necessário
        },
        'rate_limiting': {
            'requests_per_hour': MAX_REQUESTS_PER_IP,
            'burst_limit': 10,
            'ban_duration': 3600  # 1 hora
        }
    }
    
    # ========================================
    # MENSAGENS E TEXTOS
    # ========================================
    
    MESSAGES = {
        'success': {
            'upload': 'Imagem enviada com sucesso!',
            'processing': 'Fundo removido com sucesso!',
            'download': 'Download iniciado!'
        },
        'errors': {
            'file_too_large': f'Arquivo muito grande! Máximo: {MAX_CONTENT_LENGTH // (1024*1024)}MB',
            'invalid_format': 'Formato não suportado. Use: PNG, JPG, JPEG, WEBP, BMP',
            'processing_failed': 'Falha no processamento. Tente outro modelo.',
            'file_not_found': 'Arquivo não encontrado.',
            'server_error': 'Erro interno do servidor. Tente novamente.'
        },
        'tips': [
            'ISNet oferece a melhor qualidade para objetos complexos',
            'U²-Net Pessoas é ideal para retratos e selfies',
            'Use "Qualidade Máxima" para melhores resultados',
            'Imagens com boa iluminação produzem melhores resultados',
            'Evite fundos muito complexos ou similares ao objeto principal'
        ]
    }
    
    # ========================================
    # MÉTODOS DE CONFIGURAÇÃO
    # ========================================
    
    @classmethod
    def create_directories(cls):
        """Cria todos os diretórios necessários"""
        directories = [
            cls.UPLOAD_DIR, 
            cls.PROCESSED_DIR, 
            cls.TEMP_DIR,
            cls.STATIC_DIR
        ]
        
        for directory in directories:
            directory.mkdir(exist_ok=True, parents=True)
            
        # Criar arquivo .gitkeep para manter diretórios no git
        for directory in [cls.UPLOAD_DIR, cls.PROCESSED_DIR, cls.TEMP_DIR]:
            gitkeep_file = directory / '.gitkeep'
            if not gitkeep_file.exists():
                gitkeep_file.touch()
    
    @classmethod
    def get_recommended_models(cls):
        """Retorna apenas modelos recomendados"""
        return {k: v for k, v in cls.AI_MODELS.items() if v.get('recommended', False)}
    
    @classmethod
    def get_models_by_category(cls, category: str):
        """Retorna modelos por categoria"""
        return {k: v for k, v in cls.AI_MODELS.items() if v.get('category') == category}
    
    @classmethod
    def get_quality_settings(cls, quality_level: str):
        """Retorna configurações específicas de qualidade"""
        return cls.QUALITY_PRESETS.get(quality_level, cls.QUALITY_PRESETS['alta'])['settings']
    
    @classmethod
    def is_valid_model(cls, model_name: str) -> bool:
        """Verifica se o modelo é válido"""
        return model_name in cls.AI_MODELS
    
    @classmethod
    def is_valid_quality(cls, quality_level: str) -> bool:
        """Verifica se o nível de qualidade é válido"""
        return quality_level in cls.QUALITY_PRESETS
    
    @classmethod
    def get_optimal_settings_for_image(cls, file_size: int, dimensions: tuple):
        """Sugere configurações ótimas baseadas na imagem"""
        width, height = dimensions
        total_pixels = width * height
        
        # Sugerir qualidade baseada no tamanho e complexidade
        if file_size > 10 * 1024 * 1024 or total_pixels > 2000 * 2000:
            return 'media'  # Imagens muito grandes
        elif total_pixels < 500 * 500:
            return 'rapida'  # Imagens pequenas
        else:
            return 'alta'  # Padrão recomendado
    
    @classmethod
    def get_processing_estimate(cls, quality_level: str, file_size: int) -> str:
        """Estima tempo de processamento"""
        base_time = cls.QUALITY_PRESETS[quality_level]['processing_time']
        
        # Ajustar baseado no tamanho do arquivo
        if file_size > 5 * 1024 * 1024:  # > 5MB
            return f"{base_time} (arquivo grande)"
        elif file_size < 1 * 1024 * 1024:  # < 1MB  
            return f"{base_time} (arquivo pequeno)"
        else:
            return base_time

# ========================================
# FUNÇÕES UTILITÁRIAS
# ========================================

def allowed_file(filename: str) -> bool:
    """Verifica se o arquivo tem extensão permitida"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def get_unique_filename(filename: str) -> str:
    """Gera nome único para o arquivo"""
    import uuid
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'png'
    return f"{uuid.uuid4().hex}.{ext}"

def format_file_size(size_bytes: int) -> str:
    """Formata tamanho do arquivo"""
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"

def validate_image_file(file_path: str) -> tuple[bool, str]:
    """Valida arquivo de imagem"""
    try:
        from PIL import Image
        
        # Verificar se arquivo existe
        if not os.path.exists(file_path):
            return False, "Arquivo não encontrado"
        
        # Verificar tamanho
        file_size = os.path.getsize(file_path)
        if file_size > Config.MAX_CONTENT_LENGTH:
            return False, Config.MESSAGES['errors']['file_too_large']
        
        # Verificar se é imagem válida
        with Image.open(file_path) as img:
            img.verify()
        
        return True, "Arquivo válido"
        
    except Exception as e:
        return False, f"Arquivo inválido: {str(e)}"

def cleanup_old_files():
    """Remove arquivos antigos"""
    import time
    import shutil
    
    current_time = time.time()
    max_age = Config.MAX_LIFETIME_SECONDS
    removed_count = 0
    
    # Limpar uploads
    for file_path in Config.UPLOAD_DIR.glob('*'):
        if file_path.is_file() and current_time - file_path.stat().st_mtime > max_age:
            file_path.unlink(missing_ok=True)
            removed_count += 1
    
    # Limpar processados
    for file_path in Config.PROCESSED_DIR.glob('*'):
        if file_path.is_file() and current_time - file_path.stat().st_mtime > max_age:
            file_path.unlink(missing_ok=True)
            removed_count += 1
    
    # Limpar temporários
    for file_path in Config.TEMP_DIR.glob('*'):
        if file_path.is_file() and current_time - file_path.stat().st_mtime > max_age:
            file_path.unlink(missing_ok=True)
            removed_count += 1
    
    return removed_count

# Inicializar diretórios ao importar o módulo
Config.create_directories()
import os
from PIL import Image
import zipfile
import tempfile
from werkzeug.utils import secure_filename
import base64
import io


class Config:
    # Extensões permitidas para upload/conversão (expandida)
    ALLOWED_EXTENSIONS = {
        'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'tif',
        'ico', 'svg', 'psd', 'pdf', 'pcx', 'tga', 'xbm', 'xpm',
        'ppm', 'pgm', 'pbm', 'heic', 'heif', 'avif'
    }

    # Tamanho máximo de upload (32 MB)
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024

    # Formatos de saída disponíveis
    OUTPUT_FORMATS = {
        'jpg': {'name': '📸 JPG - Fotos (Menor)', 'quality': True, 'web_optimized': True},
        'png': {'name': '🖼️ PNG - Gráficos (Transparência)', 'quality': False, 'web_optimized': True},
        'webp': {'name': '🚀 WEBP - Web Moderno', 'quality': True, 'web_optimized': True},
        'avif': {'name': '⚡ AVIF - Próxima Geração', 'quality': True, 'web_optimized': True},
        'heic': {'name': '🍎 HEIC - Padrão Apple', 'quality': True, 'web_optimized': False},
        'gif': {'name': '🎬 GIF - Animações', 'quality': False, 'web_optimized': True},
        'bmp': {'name': '🗂️ BMP - Básico', 'quality': False, 'web_optimized': False},
        'tiff': {'name': '📊 TIFF - Impressão', 'quality': True, 'web_optimized': False},
        'ico': {'name': '🔷 ICO - Ícone Windows', 'quality': False, 'web_optimized': False},
        'pdf': {'name': '📄 PDF - Documento', 'quality': True, 'web_optimized': False},
        'base64': {'name': '💻 BASE64 - Código Web', 'quality': True, 'web_optimized': True}
    }


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def compress_to_target_size(img, target_size_kb, output_format):
    """Comprime imagem até atingir tamanho alvo"""
    target_size_bytes = target_size_kb * 1024
    
    # Configuração inicial
    quality = 95
    temp_buffer = io.BytesIO()
    
    while quality > 10:
        temp_buffer.seek(0)
        temp_buffer.truncate()
        
        if output_format.upper() in ['JPEG', 'JPG']:
            img.save(temp_buffer, format='JPEG', quality=quality, optimize=True)
        elif output_format.upper() == 'WEBP':
            img.save(temp_buffer, format='WEBP', quality=quality, optimize=True)
        elif output_format.upper() == 'AVIF':
            img.save(temp_buffer, format='AVIF', quality=quality, optimize=True)
        else:
            break
            
        if temp_buffer.tell() <= target_size_bytes:
            break
            
        quality -= 5
    
    return quality if quality > 10 else 10


def optimize_for_web(img, output_format):
    """Otimizações específicas para web"""
    # Redimensionar se muito grande para web
    max_width, max_height = 1920, 1080
    
    if img.width > max_width or img.height > max_height:
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    
    # Converter para RGB se necessário para formatos web
    if output_format.upper() in ['JPEG', 'JPG', 'WEBP'] and img.mode in ('RGBA', 'P'):
        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = rgb_img
    
    return img


def convert_to_base64(img, quality=85):
    """Converte imagem para Base64 data URI"""
    buffer = io.BytesIO()
    
    # Converter para RGB se necessário
    if img.mode in ('RGBA', 'P'):
        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = rgb_img
    
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    img_base64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/jpeg;base64,{img_base64}"


def convert_to_ico(img, sizes=[16, 32, 48, 64]):
    """Converte para ICO com múltiplos tamanhos"""
    ico_images = []
    
    for size in sizes:
        resized = img.copy()
        resized.thumbnail((size, size), Image.Resampling.LANCZOS)
        
        # Garantir modo correto para ICO
        if resized.mode != 'RGBA':
            resized = resized.convert('RGBA')
        
        ico_images.append(resized)
    
    return ico_images


def convert_image(input_path, output_format, quality=85, target_size_kb=None, web_optimize=False):
    """
    Converte imagem para o formato especificado com opções avançadas
    """
    try:
        with Image.open(input_path) as img:
            # Otimização para web se solicitada
            if web_optimize and Config.OUTPUT_FORMATS.get(output_format.lower(), {}).get('web_optimized'):
                img = optimize_for_web(img, output_format)
            
            # Gerar nome do arquivo de saída
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            
            # Casos especiais
            if output_format.lower() == 'base64':
                base64_data = convert_to_base64(img, quality)
                output_filename = f"{base_name}.txt"
                temp_dir = tempfile.gettempdir()
                output_path = os.path.join(temp_dir, output_filename)
                
                with open(output_path, 'w') as f:
                    f.write(base64_data)
                
                return output_path, output_filename
            
            elif output_format.lower() == 'ico':
                output_filename = f"{base_name}.ico"
                temp_dir = tempfile.gettempdir()
                output_path = os.path.join(temp_dir, output_filename)
                
                # Criar ICO com múltiplos tamanhos
                img.save(output_path, format='ICO', sizes=[(16,16), (32,32), (48,48), (64,64)])
                return output_path, output_filename
            
            elif output_format.lower() == 'pdf':
                output_filename = f"{base_name}.pdf"
                temp_dir = tempfile.gettempdir()
                output_path = os.path.join(temp_dir, output_filename)
                
                # Converter para RGB se necessário
                if img.mode in ('RGBA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = rgb_img
                
                img.save(output_path, format='PDF', quality=quality, optimize=True)
                return output_path, output_filename
            
            else:
                # Conversão normal
                output_filename = f"{base_name}.{output_format.lower()}"
                temp_dir = tempfile.gettempdir()
                output_path = os.path.join(temp_dir, output_filename)
                
                # Compressão por tamanho alvo
                if target_size_kb and Config.OUTPUT_FORMATS.get(output_format.lower(), {}).get('quality'):
                    quality = compress_to_target_size(img, target_size_kb, output_format)
                
                # Converter RGBA para RGB se necessário (para JPG)
                if output_format.upper() in ['JPEG', 'JPG'] and img.mode in ('RGBA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = rgb_img
                
                # Salvar com configurações específicas por formato
                if output_format.upper() in ['JPEG', 'JPG']:
                    img.save(output_path, format='JPEG', quality=quality, optimize=True, progressive=True)
                elif output_format.upper() == 'PNG':
                    img.save(output_path, format='PNG', optimize=True, compress_level=9)
                elif output_format.upper() == 'WEBP':
                    img.save(output_path, format='WEBP', quality=quality, optimize=True, method=6)
                elif output_format.upper() == 'AVIF':
                    img.save(output_path, format='AVIF', quality=quality, optimize=True)
                elif output_format.upper() == 'HEIC':
                    # Fallback para JPG se HEIC não suportado
                    try:
                        img.save(output_path, format='HEIC', quality=quality)
                    except:
                        output_filename = f"{base_name}.jpg"
                        output_path = os.path.join(temp_dir, output_filename)
                        img.save(output_path, format='JPEG', quality=quality, optimize=True)
                else:
                    img.save(output_path, format=output_format.upper(), optimize=True)
                
                return output_path, output_filename
            
    except Exception as e:
        raise Exception(f"Erro ao converter imagem: {str(e)}")


def create_zip_download(file_paths, zip_name="imagens_convertidas.zip"):
    """
    Cria um arquivo ZIP com todas as imagens convertidas
    """
    temp_dir = tempfile.gettempdir()
    zip_path = os.path.join(temp_dir, zip_name)
    
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for file_path, filename in file_paths:
            if os.path.exists(file_path):
                zipf.write(file_path, filename)
    
    return zip_path


def get_image_info(file_path):
    """
    Obtém informações detalhadas da imagem
    """
    try:
        with Image.open(file_path) as img:
            file_size = os.path.getsize(file_path)
            
            return {
                'format': img.format,
                'size': img.size,
                'mode': img.mode,
                'file_size': file_size,
                'width': img.width,
                'height': img.height,
                'aspect_ratio': round(img.width / img.height, 2),
                'megapixels': round((img.width * img.height) / 1000000, 2),
                'has_transparency': img.mode in ('RGBA', 'LA', 'P'),
                'color_depth': len(img.getbands()),
                'dpi': img.info.get('dpi', (72, 72))
            }
    except:
        return None
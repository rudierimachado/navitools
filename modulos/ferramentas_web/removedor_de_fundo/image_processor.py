import cv2
import numpy as np
from PIL import Image, ImageFilter
import rembg
from pathlib import Path
import io
from typing import Tuple, Optional, Union

class BackgroundRemover:
    """Classe principal para remoção de fundo com IA"""
    
    def __init__(self, model_name: str = 'u2net'):
        self.model_name = model_name
        self.session = rembg.new_session(model_name)
    
    def remove_background(self, image_path: Union[str, Path]) -> Image.Image:
        """Remove o fundo da imagem usando IA"""
        try:
            with open(image_path, 'rb') as f:
                input_data = f.read()
            
            # Processa com rembg
            output_data = rembg.remove(input_data, session=self.session)
            
            # Converte para PIL Image
            output_image = Image.open(io.BytesIO(output_data))
            return output_image
            
        except Exception as e:
            raise Exception(f"Erro ao processar imagem: {str(e)}")
    
    def apply_background(self, image: Image.Image, bg_type: str, 
                        custom_color: Optional[Tuple[int, int, int]] = None) -> Image.Image:
        """Aplica novo fundo à imagem"""
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        width, height = image.size
        
        if bg_type == 'transparent':
            return image
        
        elif bg_type == 'white':
            background = Image.new('RGB', (width, height), (255, 255, 255))
            
        elif bg_type == 'black':
            background = Image.new('RGB', (width, height), (0, 0, 0))
            
        elif bg_type == 'custom' and custom_color:
            background = Image.new('RGB', (width, height), custom_color)
            
        else:
            # Gradiente padrão
            background = self._create_gradient_background(width, height)
        
        # Combina imagem com fundo
        if bg_type != 'transparent':
            background.paste(image, (0, 0), image)
            return background
        
        return image
    
    def _create_gradient_background(self, width: int, height: int) -> Image.Image:
        """Cria fundo gradiente"""
        background = Image.new('RGB', (width, height))
        
        for y in range(height):
            # Gradiente de azul para branco
            ratio = y / height
            color = (
                int(173 + (255 - 173) * ratio),  # R
                int(216 + (255 - 216) * ratio),  # G
                int(230 + (255 - 230) * ratio)   # B
            )
            
            for x in range(width):
                background.putpixel((x, y), color)
        
        return background
    
    def enhance_edges(self, image: Image.Image) -> Image.Image:
        """Melhora as bordas da imagem"""
        if image.mode != 'RGBA':
            return image
        
        # Suaviza bordas
        alpha = image.split()[-1]
        alpha = alpha.filter(ImageFilter.GaussianBlur(0.5))
        
        # Reconstrói imagem
        r, g, b, _ = image.split()
        enhanced = Image.merge('RGBA', (r, g, b, alpha))
        
        return enhanced
    
    def resize_image(self, image: Image.Image, max_size: int = 2048) -> Image.Image:
        """Redimensiona imagem mantendo proporção"""
        width, height = image.size
        
        if max(width, height) <= max_size:
            return image
        
        if width > height:
            new_width = max_size
            new_height = int(height * max_size / width)
        else:
            new_height = max_size
            new_width = int(width * max_size / height)
        
        return image.resize((new_width, new_height), Image.Resampling.LANCZOS)

class BatchProcessor:
    """Processamento em lote de imagens"""
    
    def __init__(self, model_name: str = 'u2net'):
        self.remover = BackgroundRemover(model_name)
        self.progress_callback = None
    
    def set_progress_callback(self, callback):
        """Define callback para progresso"""
        self.progress_callback = callback
    
    def process_batch(self, image_paths: list, output_dir: Path, 
                     bg_type: str = 'transparent', custom_color: Optional[Tuple[int, int, int]] = None) -> list:
        """Processa múltiplas imagens"""
        results = []
        total = len(image_paths)
        
        for i, image_path in enumerate(image_paths):
            try:
                # Remove fundo
                processed = self.remover.remove_background(image_path)
                
                # Aplica novo fundo
                final_image = self.remover.apply_background(processed, bg_type, custom_color)
                
                # Melhora bordas
                final_image = self.remover.enhance_edges(final_image)
                
                # Salva resultado
                output_path = output_dir / f"processed_{Path(image_path).name}"
                
                if bg_type == 'transparent':
                    final_image.save(output_path, 'PNG')
                else:
                    final_image = final_image.convert('RGB')
                    final_image.save(output_path, 'JPEG', quality=95)
                
                results.append({
                    'success': True,
                    'input_path': str(image_path),
                    'output_path': str(output_path),
                    'filename': output_path.name
                })
                
                # Callback de progresso
                if self.progress_callback:
                    self.progress_callback(i + 1, total)
                    
            except Exception as e:
                results.append({
                    'success': False,
                    'input_path': str(image_path),
                    'error': str(e)
                })
        
        return results
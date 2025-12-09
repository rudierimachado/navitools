import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import rembg
from pathlib import Path
import io
from typing import Tuple, Optional, Union
import logging

logger = logging.getLogger(__name__)

class SuperRembgProcessor:
    """Processador rembg super otimizado para máxima qualidade"""
    
    def __init__(self, model_name: str = 'u2net'):
        self.model_name = model_name
        self.session = None
        logger.info(f"Inicializando SuperRembg com: {model_name}")
        
    def _get_optimized_session(self):
        """Cria sessão rembg otimizada"""
        if self.session is None:
            try:
                logger.info(f"Criando sessão otimizada para: {self.model_name}")
                self.session = rembg.new_session(
                    self.model_name,
                    providers=['CPUExecutionProvider']  # Mais estável
                )
                logger.info("Sessão rembg criada com sucesso")
            except Exception as e:
                logger.error(f"Erro ao criar sessão: {e}")
                # Fallback para modelo mais confiável
                self.session = rembg.new_session('u2net')
                self.model_name = 'u2net'
        return self.session
    
    def close(self):
        """Libera a sessão rembg da memória assim que não for mais necessária.

        Isso evita manter o modelo carregado na RAM por mais tempo do que o
        necessário, principalmente em ambientes com pouca memória.
        """
        try:
            if self.session is not None:
                # Apenas remover a referência; o GC cuida do restante.
                self.session = None
        except Exception:
            # Em caso de qualquer erro, garantimos que a referência seja removida.
            self.session = None
    
    def _enhance_for_segmentation(self, image: Image.Image) -> Image.Image:
        """Pré-processamento avançado para melhor segmentação"""
        logger.info("Aplicando pré-processamento avançado...")
        
        # 1. Converter para RGB
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # 2. Redimensionar inteligentemente (múltiplos de 32 funcionam melhor)
        original_size = image.size
        optimal_size = self._get_optimal_size(original_size)
        if optimal_size != original_size:
            image = image.resize(optimal_size, Image.Resampling.LANCZOS)
        
        # 3. Melhorar contraste adaptativo
        image = self._adaptive_contrast_enhancement(image)
        
        # 4. Redução de ruído
        image = self._advanced_denoise(image)
        
        # 5. Aguçar bordas sutilmente
        image = self._edge_enhancement(image)
        
        logger.info(f"Pré-processamento concluído: {original_size} -> {image.size}")
        return image, original_size
    
    def _get_optimal_size(self, size: Tuple[int, int]) -> Tuple[int, int]:
        """Calcula tamanho ótimo (múltiplos de 32)"""
        width, height = size
        max_dim = 1024  # Tamanho máximo para qualidade/velocidade
        
        if max(width, height) > max_dim:
            if width > height:
                new_width = max_dim
                new_height = int(height * max_dim / width)
            else:
                new_height = max_dim
                new_width = int(width * max_dim / height)
        else:
            new_width, new_height = width, height
        
        # Ajustar para múltiplos de 32
        new_width = ((new_width + 31) // 32) * 32
        new_height = ((new_height + 31) // 32) * 32
        
        return (new_width, new_height)
    
    def _adaptive_contrast_enhancement(self, image: Image.Image) -> Image.Image:
        """Melhora contraste de forma adaptativa"""
        # Converter para array numpy para processamento
        img_array = np.array(image)
        
        # CLAHE (Contrast Limited Adaptive Histogram Equalization)
        lab = cv2.cvtColor(img_array, cv2.COLOR_RGB2LAB)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        lab[:,:,0] = clahe.apply(lab[:,:,0])
        enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        
        return Image.fromarray(enhanced)
    
    def _advanced_denoise(self, image: Image.Image) -> Image.Image:
        """Redução de ruído avançada"""
        img_array = np.array(image)
        
        # Filtro bilateral para reduzir ruído preservando bordas
        denoised = cv2.bilateralFilter(img_array, 9, 75, 75)
        
        return Image.fromarray(denoised)
    
    def _edge_enhancement(self, image: Image.Image) -> Image.Image:
        """Realce sutil de bordas"""
        enhancer = ImageEnhance.Sharpness(image)
        return enhancer.enhance(1.05)  # Realce muito sutil
    
    def remove_background(self, image_path: Union[str, Path], quality_level: str = 'ultra') -> Image.Image:
        """Remove fundo com configurações ultra otimizadas"""
        try:
            logger.info(f"Iniciando remoção de fundo ultra: {image_path}")
            
            # Carregar imagem
            original_image = Image.open(image_path)
            logger.info(f"Imagem carregada: {original_image.size}, modo: {original_image.mode}")
            
            # Pré-processar
            processed_image, original_size = self._enhance_for_segmentation(original_image)
            
            # Converter para bytes
            img_byte_arr = io.BytesIO()
            processed_image.save(img_byte_arr, format='PNG', optimize=True)
            input_data = img_byte_arr.getvalue()
            
            logger.info(f"Dados de entrada preparados: {len(input_data)} bytes")
            
            # Obter sessão
            session = self._get_optimized_session()
            
            # Configurações ultra otimizadas baseadas na qualidade
            remove_kwargs = self._get_quality_settings(quality_level)
            remove_kwargs["session"] = session
            
            logger.info(f"Processando com configurações: {quality_level}")
            logger.info(f"Parâmetros: {remove_kwargs}")
            
            # PROCESSAR com rembg otimizado
            output_data = rembg.remove(input_data, **remove_kwargs)
            
            logger.info(f"Processamento concluído: {len(output_data)} bytes")
            
            # Converter resultado para PIL
            result_image = Image.open(io.BytesIO(output_data))
            logger.info(f"Resultado: {result_image.size}, modo: {result_image.mode}")
            
            # Redimensionar de volta ao tamanho original se necessário
            if result_image.size != original_size:
                result_image = result_image.resize(original_size, Image.Resampling.LANCZOS)
                logger.info(f"Redimensionado para tamanho original: {original_size}")
            
            # Pós-processamento para refinar
            final_result = self._post_process_mask(result_image, quality_level)
            
            logger.info("Remoção de fundo concluída com sucesso")
            return final_result
            
        except Exception as e:
            logger.exception(f"Erro na remoção de fundo: {e}")
            raise Exception(f"Falha na remoção de fundo: {str(e)}")
    
    def _get_quality_settings(self, quality_level: str) -> dict:
        """Configurações otimizadas por nível de qualidade"""
        
        if quality_level == 'maxima':
            return {
                "only_mask": False,
                "post_process_mask": True,
                "alpha_matting": True,
                "alpha_matting_foreground_threshold": 270,
                "alpha_matting_background_threshold": 5,
                "alpha_matting_erode_structure_size": 15,
                "alpha_matting_base_size": 2000,
                "alpha_matting_erosion_size": 3,
            }
        elif quality_level == 'alta':
            return {
                "only_mask": False,
                "post_process_mask": True,
                "alpha_matting": True,
                "alpha_matting_foreground_threshold": 250,
                "alpha_matting_background_threshold": 8,
                "alpha_matting_erode_structure_size": 12,
                "alpha_matting_base_size": 1500,
                "alpha_matting_erosion_size": 2,
            }
        elif quality_level == 'media':
            return {
                "only_mask": False,
                "post_process_mask": True,
                "alpha_matting": True,
                "alpha_matting_foreground_threshold": 240,
                "alpha_matting_background_threshold": 10,
                "alpha_matting_erode_structure_size": 10,
                "alpha_matting_base_size": 1000,
            }
        else:  # rapida
            return {
                "only_mask": False,
                "post_process_mask": True,
                "alpha_matting": False,
            }
    
    def _post_process_mask(self, image: Image.Image, quality_level: str) -> Image.Image:
        """Pós-processamento da máscara para refinar bordas"""
        if quality_level == 'rapida':
            return image
        
        logger.info("Aplicando pós-processamento de máscara...")
        
        if image.mode != 'RGBA':
            return image
        
        # Separar canais
        r, g, b, alpha = image.split()
        
        # Converter alpha para array numpy
        alpha_array = np.array(alpha)
        
        # 1. Suavização gaussiana leve
        alpha_smooth = cv2.GaussianBlur(alpha_array, (3, 3), 0.8)
        
        # 2. Morfologia para fechar pequenos buracos
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        alpha_morph = cv2.morphologyEx(alpha_smooth, cv2.MORPH_CLOSE, kernel)
        
        # 3. Filtro bilateral para bordas mais naturais
        if quality_level in ['alta', 'maxima']:
            alpha_final = cv2.bilateralFilter(alpha_morph, 5, 50, 50)
        else:
            alpha_final = alpha_morph
        
        # Reconstruir imagem
        alpha_final_pil = Image.fromarray(alpha_final)
        result = Image.merge('RGBA', (r, g, b, alpha_final_pil))
        
        logger.info("Pós-processamento concluído")
        return result
    
    def apply_background(self, image: Image.Image, bg_type: str, 
                        custom_color: Optional[Tuple[int, int, int]] = None) -> Image.Image:
        """Aplica fundo com qualidade otimizada"""
        try:
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
                background = self._create_gradient_background(width, height)
            
            # Composição de alta qualidade
            if bg_type != 'transparent':
                # Usar composição alpha para bordas suaves
                background = background.convert('RGBA')
                result = Image.alpha_composite(background, image)
                return result.convert('RGB')
            
            return image
            
        except Exception as e:
            logger.error(f"Erro ao aplicar fundo: {e}")
            return image
    
    def _create_gradient_background(self, width: int, height: int) -> Image.Image:
        """Gradiente elegante"""
        background = Image.new('RGB', (width, height))
        for y in range(height):
            ratio = y / height
            color = (
                int(240 + (255 - 240) * ratio),
                int(248 + (255 - 248) * ratio), 
                int(255)
            )
            for x in range(width):
                background.putpixel((x, y), color)
        return background

# Alias para compatibilidade
BackgroundRemover = SuperRembgProcessor

class BatchProcessor:
    """Processamento em lote reutilizando o SuperRembgProcessor"""

    def __init__(self, model_name: str = 'u2net', quality_level: str = 'media'):
        self.model_name = model_name
        self.quality_level = quality_level
        self._progress_callback = None

    def set_progress_callback(self, callback):
        self._progress_callback = callback

    def _emit_progress(self, current: int, total: int):
        if callable(self._progress_callback):
            try:
                self._progress_callback(current, total)
            except Exception as exc:
                logger.debug(f"Callback de progresso falhou: {exc}")

    def process_batch(self, input_paths, output_dir, bg_type='transparent', custom_color=None):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        processor = SuperRembgProcessor(self.model_name)

        # Normaliza cor customizada caso seja string
        if isinstance(custom_color, str) and custom_color.startswith('#') and len(custom_color) == 7:
            custom_color = tuple(int(custom_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))

        total = len(input_paths)
        results = []

        try:
            for index, input_path in enumerate(input_paths, start=1):
                path_obj = Path(input_path)
                result_info = {
                    'input_path': str(path_obj),
                    'output_path': None,
                    'output_filename': None,
                    'success': False,
                    'error': None
                }

                try:
                    processed_image = processor.remove_background(path_obj, self.quality_level)
                    final_image = processor.apply_background(processed_image, bg_type, custom_color)

                    stem = path_obj.stem
                    output_filename = f"{stem}_processed.png"
                    output_path = output_dir / output_filename

                    # PNG para preservar transparência mesmo em lotes
                    final_image.save(output_path, 'PNG', optimize=True, compress_level=6)

                    result_info.update({
                        'output_path': str(output_path),
                        'output_filename': output_filename,
                        'success': True
                    })

                except Exception as exc:
                    logger.exception(f"Erro ao processar arquivo {path_obj}: {exc}")
                    result_info['error'] = str(exc)

                results.append(result_info)
                self._emit_progress(index, total)

        finally:
            # Garante que a sessão rembg seja liberada ao final do lote,
            # reduzindo o tempo de vida do modelo na RAM.
            try:
                processor.close()
            except Exception as exc:
                logger.debug(f"Falha ao liberar sessão rembg: {exc}")

        return results
import os
import tempfile
import uuid
from datetime import datetime

import pikepdf
from pikepdf import Dictionary, Name, Stream, Array


def add_watermark_to_pdf(input_path: str, watermark_text: str, opacity: float = 0.3) -> tuple[str, str]:
    """Adiciona marca d'água a um PDF.
    
    Args:
        input_path: Caminho do PDF de entrada
        watermark_text: Texto da marca d'água
        opacity: Opacidade da marca (0.0 a 1.0)
    
    Returns:
        Tupla (output_path, output_filename)
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError("Arquivo PDF de entrada não encontrado.")
    
    ext = os.path.splitext(input_path)[1] or ".pdf"
    output_filename = f"pdf_com_marca_{uuid.uuid4().hex}{ext}"
    output_path = os.path.join(tempfile.gettempdir(), output_filename)
    
    try:
        with pikepdf.open(input_path) as pdf:
            for page in pdf.pages:
                # Criar conteúdo da marca d'água em PDF
                watermark_stream = f"""
BT
/F1 48 Tf
1 0 0 1 100 400 Tm
{opacity} ca
0.7 0.7 0.7 rg
({watermark_text}) Tj
ET
                """.encode('latin-1')
                
                # Adicionar marca à página
                watermark_obj = pikepdf.Stream(pdf, watermark_stream)
                
                if "/Contents" in page:
                    # Se já existe conteúdo, adicionar antes
                    if isinstance(page.Contents, Array):
                        page.Contents.insert(0, watermark_obj)
                    else:
                        page.Contents = Array([watermark_obj, page.Contents])
                else:
                    page.Contents = watermark_obj
            
            pdf.save(output_path)
    except Exception as e:
        raise Exception(f"Erro ao adicionar marca d'água: {str(e)}")
    
    return output_path, output_filename


def add_page_numbers_to_pdf(input_path: str, start_page: int = 1, position: str = "bottom_right") -> tuple[str, str]:
    """Adiciona números de página a um PDF.
    
    Args:
        input_path: Caminho do PDF de entrada
        start_page: Página inicial da numeração
        position: Posição dos números (bottom_right, bottom_center, bottom_left, top_right, top_center, top_left)
    
    Returns:
        Tupla (output_path, output_filename)
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError("Arquivo PDF de entrada não encontrado.")
    
    ext = os.path.splitext(input_path)[1] or ".pdf"
    output_filename = f"pdf_numerado_{uuid.uuid4().hex}{ext}"
    output_path = os.path.join(tempfile.gettempdir(), output_filename)
    
    position_map = {
        "bottom_right": (500, 30),
        "bottom_center": (280, 30),
        "bottom_left": (50, 30),
        "top_right": (500, 750),
        "top_center": (280, 750),
        "top_left": (50, 750),
    }
    
    x, y = position_map.get(position, (500, 30))
    
    try:
        with pikepdf.open(input_path) as pdf:
            for idx, page in enumerate(pdf.pages, start=start_page):
                page_num = idx
                number_stream = f"""
BT
/F1 12 Tf
1 0 0 1 {x} {y} Tm
({page_num}) Tj
ET
                """.encode('latin-1')
                
                number_obj = pikepdf.Stream(pdf, number_stream)
                
                if "/Contents" in page:
                    if isinstance(page.Contents, Array):
                        page.Contents.insert(0, number_obj)
                    else:
                        page.Contents = Array([number_obj, page.Contents])
                else:
                    page.Contents = number_obj
            
            pdf.save(output_path)
    except Exception as e:
        raise Exception(f"Erro ao adicionar números de página: {str(e)}")
    
    return output_path, output_filename


def rotate_pdf_pages(input_path: str, rotation: int = 90) -> tuple[str, str]:
    """Rotaciona as páginas de um PDF.
    
    Args:
        input_path: Caminho do PDF de entrada
        rotation: Ângulo de rotação (90, 180, 270)
    
    Returns:
        Tupla (output_path, output_filename)
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError("Arquivo PDF de entrada não encontrado.")
    
    if rotation not in [90, 180, 270]:
        raise ValueError("Rotação deve ser 90, 180 ou 270 graus.")
    
    ext = os.path.splitext(input_path)[1] or ".pdf"
    output_filename = f"pdf_rotacionado_{uuid.uuid4().hex}{ext}"
    output_path = os.path.join(tempfile.gettempdir(), output_filename)
    
    try:
        with pikepdf.open(input_path) as pdf:
            for page in pdf.pages:
                current_rotation = int(page.get("/Rotate", 0))
                new_rotation = (current_rotation + rotation) % 360
                page.Rotate = new_rotation
            
            pdf.save(output_path)
    except Exception as e:
        raise Exception(f"Erro ao rotacionar PDF: {str(e)}")
    
    return output_path, output_filename

import os
import tempfile
import sys
from werkzeug.utils import secure_filename

# Cache da aplicação Office para reutilizar
_office_apps = {}


def convert_to_pdf(input_path):
    """
    Converte arquivo Word/Excel/PowerPoint para PDF.
    Otimizado para velocidade usando cache de aplicações Office.
    
    Args:
        input_path: Caminho do arquivo de entrada
        
    Returns:
        tuple: (caminho_arquivo_pdf, nome_arquivo_pdf)
    """
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_filename = f"{base_name}.pdf"
    temp_dir = tempfile.gettempdir()
    output_path = os.path.join(temp_dir, output_filename)
    
    file_ext = os.path.splitext(input_path.lower())[1]
    
    # Método 1: Tentar usar comtypes (Windows + MS Office) - OTIMIZADO
    if sys.platform == 'win32':
        try:
            import comtypes.client
            
            if file_ext in ['.doc', '.docx']:
                # Reutiliza instância do Word se já existir
                if 'word' not in _office_apps:
                    _office_apps['word'] = comtypes.client.CreateObject('Word.Application')
                    _office_apps['word'].Visible = False
                    _office_apps['word'].DisplayAlerts = 0  # Desabilita alertas
                
                word = _office_apps['word']
                doc = word.Documents.Open(input_path, ReadOnly=True, AddToRecentFiles=False)
                doc.SaveAs(output_path, FileFormat=17)  # 17 = PDF
                doc.Close(SaveChanges=False)
                return output_path, output_filename
                
            elif file_ext in ['.xls', '.xlsx']:
                if 'excel' not in _office_apps:
                    _office_apps['excel'] = comtypes.client.CreateObject('Excel.Application')
                    _office_apps['excel'].Visible = False
                    _office_apps['excel'].DisplayAlerts = False
                
                excel = _office_apps['excel']
                wb = excel.Workbooks.Open(input_path, ReadOnly=True, UpdateLinks=False)
                wb.ExportAsFixedFormat(0, output_path)  # 0 = PDF
                wb.Close(SaveChanges=False)
                return output_path, output_filename
                
            elif file_ext in ['.ppt', '.pptx']:
                if 'powerpoint' not in _office_apps:
                    _office_apps['powerpoint'] = comtypes.client.CreateObject('PowerPoint.Application')
                
                powerpoint = _office_apps['powerpoint']
                presentation = powerpoint.Presentations.Open(input_path, ReadOnly=True, WithWindow=False)
                presentation.SaveAs(output_path, 32)  # 32 = PDF
                presentation.Close()
                return output_path, output_filename
                
        except Exception as e:
            # Limpa cache em caso de erro
            _office_apps.clear()
            pass  # Se falhar, tenta pypandoc
    
    # Método 2: Tentar usar pypandoc
    try:
        import pypandoc
        
        if file_ext in ['.doc', '.docx', '.txt', '.rtf', '.odt', '.md']:
            pypandoc.convert_file(input_path, 'pdf', outputfile=output_path)
            if os.path.exists(output_path):
                return output_path, output_filename
        elif file_ext in ['.html', '.htm']:
            pypandoc.convert_file(input_path, 'pdf', outputfile=output_path, extra_args=['--standalone'])
            if os.path.exists(output_path):
                return output_path, output_filename
    except:
        pass
    
    # Método 3: Tentar converter imagens para PDF
    try:
        if file_ext in ['.jpg', '.jpeg', '.png', '.webp']:
            from PIL import Image
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            
            # Abrir imagem
            img = Image.open(input_path)
            
            # Criar PDF
            c = canvas.Canvas(output_path, pagesize=letter)
            page_width, page_height = letter
            
            # Calcular dimensões para manter proporção
            img_width, img_height = img.size
            scale = min(page_width / img_width, page_height / img_height) * 0.9
            scaled_width = img_width * scale
            scaled_height = img_height * scale
            
            # Centralizar imagem
            x = (page_width - scaled_width) / 2
            y = (page_height - scaled_height) / 2
            
            # Adicionar imagem ao PDF
            c.drawImage(input_path, x, y, scaled_width, scaled_height)
            c.save()
            
            if os.path.exists(output_path):
                return output_path, output_filename
    except:
        pass
    
    # Se nenhum método funcionou
    raise Exception(
        "Não foi possível converter o arquivo. "
        "Instale o Microsoft Office (Word/Excel/PowerPoint) ou execute: pip install pypandoc"
    )


def cleanup_office_apps():
    """Limpa instâncias do Office em cache (chamar ao encerrar aplicação)."""
    global _office_apps
    try:
        if 'word' in _office_apps:
            _office_apps['word'].Quit()
        if 'excel' in _office_apps:
            _office_apps['excel'].Quit()
        if 'powerpoint' in _office_apps:
            _office_apps['powerpoint'].Quit()
    except:
        pass
    finally:
        _office_apps.clear()


def is_valid_file(filename):
    """Verifica se o arquivo tem extensão válida para conversão."""
    valid_extensions = {
        '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', 
        '.txt', '.rtf', '.odt', '.ods', '.html', '.htm', '.md',
        '.jpg', '.jpeg', '.png', '.webp'
    }
    ext = os.path.splitext(filename.lower())[1]
    return ext in valid_extensions

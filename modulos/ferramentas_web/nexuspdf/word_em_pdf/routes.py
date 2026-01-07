from flask import Blueprint, render_template, request, send_file, redirect, url_for, flash
import os
import tempfile
from werkzeug.utils import secure_filename

from .service import convert_to_pdf, is_valid_file


word_em_pdf_bp = Blueprint(
    'nexuspdf_word_em_pdf',
    __name__,
    template_folder='templates',
    static_folder='static',
)


@word_em_pdf_bp.route('/', methods=['GET'])
def word_em_pdf():
    """Tela principal com seleção de formatos."""
    return render_template('word_em_pdf.html')


@word_em_pdf_bp.route('/word', methods=['GET', 'POST'])
def word_to_pdf():
    """Conversão específica para Word."""
    if request.method == 'GET':
        return render_template('word_converter.html', 
                             title='Word para PDF',
                             description='Converta documentos Word (.doc, .docx, .rtf) para PDF',
                             formats='.doc, .docx, .rtf',
                             accept='.doc,.docx,.rtf')

    return _handle_conversion('word')


@word_em_pdf_bp.route('/excel', methods=['GET', 'POST'])
def excel_to_pdf():
    """Conversão específica para Excel."""
    if request.method == 'GET':
        return render_template('word_converter.html',
                             title='Excel para PDF', 
                             description='Converta planilhas Excel (.xls, .xlsx, .csv) para PDF',
                             formats='.xls, .xlsx, .csv',
                             accept='.xls,.xlsx,.csv')

    return _handle_conversion('excel')


@word_em_pdf_bp.route('/powerpoint', methods=['GET', 'POST'])
def powerpoint_to_pdf():
    """Conversão específica para PowerPoint."""
    if request.method == 'GET':
        return render_template('word_converter.html',
                             title='PowerPoint para PDF',
                             description='Converta apresentações PowerPoint (.ppt, .pptx) para PDF', 
                             formats='.ppt, .pptx',
                             accept='.ppt,.pptx')

    return _handle_conversion('powerpoint')


@word_em_pdf_bp.route('/texto', methods=['GET', 'POST'])
def texto_to_pdf():
    """Conversão específica para Texto."""
    if request.method == 'GET':
        return render_template('word_converter.html',
                             title='Texto para PDF',
                             description='Converta arquivos de texto (.txt, .md) para PDF',
                             formats='.txt, .md', 
                             accept='.txt,.md')

    return _handle_conversion('texto')


@word_em_pdf_bp.route('/imagens', methods=['GET', 'POST'])
def imagens_to_pdf():
    """Conversão específica para Imagens."""
    if request.method == 'GET':
        return render_template('word_converter.html',
                             title='Imagens para PDF',
                             description='Combine imagens (.jpg, .png, .webp) em PDF',
                             formats='.jpg, .png, .webp',
                             accept='.jpg,.jpeg,.png,.webp')

    return _handle_conversion('imagens')


@word_em_pdf_bp.route('/odt', methods=['GET', 'POST'])
def odt_to_pdf():
    """Conversão específica para ODT."""
    if request.method == 'GET':
        return render_template('odt_converter.html')

    return _handle_conversion('odt')


@word_em_pdf_bp.route('/ods', methods=['GET', 'POST'])
def ods_to_pdf():
    """Conversão específica para ODS."""
    if request.method == 'GET':
        return render_template('ods_converter.html')

    return _handle_conversion('ods')


@word_em_pdf_bp.route('/html', methods=['GET', 'POST'])
def html_to_pdf():
    """Conversão específica para HTML."""
    if request.method == 'GET':
        return render_template('html_converter.html')

    return _handle_conversion('html')


def _handle_conversion(doc_type):
    """Função helper para processar conversão."""
    doc_file = request.files.get('doc_file')

    if not doc_file or doc_file.filename == '':
        flash('Envie um arquivo válido para conversão.', 'danger')
        return redirect(request.url)

    filename = secure_filename(doc_file.filename)
    if not is_valid_file(filename):
        flash('Formato não suportado para este tipo de conversão.', 'danger')
        return redirect(request.url)

    temp_input_path = os.path.join(tempfile.gettempdir(), filename)
    doc_file.save(temp_input_path)

    try:
        output_path, output_filename = convert_to_pdf(temp_input_path)
        
        response = send_file(
            output_path,
            as_attachment=True,
            download_name=output_filename,
            mimetype='application/pdf'
        )
        
        # Limpar arquivos temporários após envio
        try:
            os.remove(temp_input_path)
        except:
            pass
            
        return response
        
    except Exception as e:
        flash(f'Erro ao converter arquivo: {str(e)}', 'danger')
        try:
            os.remove(temp_input_path)
        except:
            pass
        return redirect(request.url)

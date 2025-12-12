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


@word_em_pdf_bp.route('/', methods=['GET', 'POST'])
def word_em_pdf():
    """Tela principal e processamento de conversão Word para PDF."""
    if request.method == 'GET':
        return render_template('word_em_pdf.html')

    doc_file = request.files.get('doc_file')

    if not doc_file or doc_file.filename == '':
        flash('Envie um arquivo válido para conversão.', 'danger')
        return redirect(url_for('nexuspdf_word_em_pdf.word_em_pdf'))

    filename = secure_filename(doc_file.filename)
    if not is_valid_file(filename):
        flash('Formato não suportado. Use: Word (.doc, .docx), Excel (.xls, .xlsx), PowerPoint (.ppt, .pptx), TXT ou RTF.', 'danger')
        return redirect(url_for('nexuspdf_word_em_pdf.word_em_pdf'))

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
        return redirect(url_for('nexuspdf_word_em_pdf.word_em_pdf'))

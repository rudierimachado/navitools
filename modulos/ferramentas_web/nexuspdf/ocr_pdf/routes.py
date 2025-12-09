from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
import os
import tempfile
import uuid
from werkzeug.utils import secure_filename

from .service import perform_ocr_on_pdf


ocr_pdf_bp = Blueprint(
    'nexuspdf_ocr_pdf',
    __name__,
    template_folder='templates',
    static_folder='static',
)


@ocr_pdf_bp.route('/', methods=['GET', 'POST'])
def ocr_pdf():
    if request.method == 'GET':
        return render_template('ocr_pdf.html')

    pdf_file = request.files.get('pdf_file')

    if not pdf_file or pdf_file.filename == '':
        flash('Envie um arquivo PDF válido para realizar OCR.', 'danger')
        return redirect(url_for('nexuspdf_ocr_pdf.ocr_pdf'))

    filename = secure_filename(pdf_file.filename)
    if not filename.lower().endswith('.pdf'):
        flash('Apenas arquivos PDF são aceitos.', 'danger')
        return redirect(url_for('nexuspdf_ocr_pdf.ocr_pdf'))

    temp_input_path = os.path.join(tempfile.gettempdir(), filename)
    pdf_file.save(temp_input_path)

    mode = request.form.get('mode') or 'advanced'

    try:
        extracted_text = perform_ocr_on_pdf(temp_input_path, mode=mode)
    except Exception:
        flash('Não foi possível processar o OCR deste PDF. Tente novamente em instantes.', 'danger')
        return redirect(url_for('nexuspdf_ocr_pdf.ocr_pdf'))
    finally:
        if os.path.exists(temp_input_path):
            try:
                os.remove(temp_input_path)
            except OSError:
                pass

    # Gerar arquivo TXT temporário com o resultado do OCR
    txt_filename = f"ocr_{uuid.uuid4().hex}.txt"
    txt_path = os.path.join(tempfile.gettempdir(), txt_filename)
    try:
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(extracted_text or '')
    except OSError:
        txt_filename = None

    return render_template(
        'ocr_pdf.html',
        extracted_text=extracted_text,
        filename=filename,
        txt_filename=txt_filename,
    )


@ocr_pdf_bp.route('/download/<path:txt_filename>')
def ocr_pdf_download(txt_filename: str):
    txt_path = os.path.join(tempfile.gettempdir(), txt_filename)
    if not os.path.exists(txt_path):
        flash('Arquivo de texto do OCR não foi encontrado. Gere novamente o OCR.', 'danger')
        return redirect(url_for('nexuspdf_ocr_pdf.ocr_pdf'))

    download_name = txt_filename
    return send_file(
        txt_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='text/plain; charset=utf-8',
    )

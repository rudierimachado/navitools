from flask import Blueprint, render_template, request, send_file, redirect, url_for, flash
import os
import tempfile
from werkzeug.utils import secure_filename

from .service import compress_pdf


comprimir_pdf_bp = Blueprint(
    'nexuspdf_comprimir_pdf',
    __name__,
    template_folder='templates',
    static_folder='static',
)


@comprimir_pdf_bp.route('/', methods=['GET', 'POST'])
def comprimir_pdf():
    """Tela principal e processamento de compressão de PDF."""
    if request.method == 'GET':
        return render_template('comprimir_pdf.html')

    pdf_file = request.files.get('pdf_file')
    quality = request.form.get('quality', 'media')

    if not pdf_file or pdf_file.filename == '':
        flash('Envie um arquivo PDF válido para compressão.', 'danger')
        return redirect(url_for('nexuspdf_comprimir_pdf.comprimir_pdf'))

    filename = secure_filename(pdf_file.filename)
    if not filename.lower().endswith('.pdf'):
        flash('Apenas arquivos PDF são aceitos.', 'danger')
        return redirect(url_for('nexuspdf_comprimir_pdf.comprimir_pdf'))

    temp_input_path = os.path.join(tempfile.gettempdir(), filename)
    pdf_file.save(temp_input_path)

    try:
        original_size = os.path.getsize(temp_input_path)
        output_path, output_filename = compress_pdf(temp_input_path, quality=quality)
        compressed_size = os.path.getsize(output_path)
    except Exception:
        flash('Não foi possível comprimir o PDF. Tente novamente em instantes.', 'danger')
        return redirect(url_for('nexuspdf_comprimir_pdf.comprimir_pdf'))
    finally:
        if os.path.exists(temp_input_path):
            try:
                os.remove(temp_input_path)
            except OSError:
                pass

    reduction_percent = 0.0
    if original_size > 0 and compressed_size >= 0:
        reduction_percent = round((1 - (compressed_size / original_size)) * 100, 1)

    result = {
        'filename': output_filename,
        'original_size': original_size,
        'compressed_size': compressed_size,
        'reduction_percent': reduction_percent,
        'quality': quality,
    }

    return render_template('comprimir_pdf.html', result=result)


@comprimir_pdf_bp.route('/download/<path:filename>')
def comprimir_pdf_download(filename: str):
    output_path = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(output_path):
        flash('Arquivo comprimido não encontrado. Gere novamente a compressão.', 'danger')
        return redirect(url_for('nexuspdf_comprimir_pdf.comprimir_pdf'))

    return send_file(
        output_path,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf',
    )

from flask import Blueprint, render_template, request, send_file, redirect, url_for, flash
import os
import tempfile
from werkzeug.utils import secure_filename

from .service import add_watermark_to_pdf, add_page_numbers_to_pdf, rotate_pdf_pages


editar_pdf_bp = Blueprint(
    'nexuspdf_editar_pdf',
    __name__,
    template_folder='templates',
    static_folder='static',
)


@editar_pdf_bp.route('/', methods=['GET', 'POST'])
def editar_pdf():
    """Tela principal e processamento de edição de PDF."""
    if request.method == 'GET':
        return render_template('editar_pdf.html')

    pdf_file = request.files.get('pdf_file')
    edit_type = request.form.get('edit_type', 'watermark')

    if not pdf_file or pdf_file.filename == '':
        flash('Envie um arquivo PDF válido para edição.', 'danger')
        return redirect(url_for('nexuspdf_editar_pdf.editar_pdf'))

    filename = secure_filename(pdf_file.filename)
    if not filename.lower().endswith('.pdf'):
        flash('Apenas arquivos PDF são aceitos.', 'danger')
        return redirect(url_for('nexuspdf_editar_pdf.editar_pdf'))

    temp_input_path = os.path.join(tempfile.gettempdir(), filename)
    pdf_file.save(temp_input_path)

    result = None

    try:
        if edit_type == 'watermark':
            watermark_text = request.form.get('watermark_text', 'CONFIDENCIAL')
            opacity = float(request.form.get('opacity', 0.3))
            output_path, output_filename = add_watermark_to_pdf(temp_input_path, watermark_text, opacity)
            result = {
                'type': 'watermark',
                'filename': output_filename,
                'watermark_text': watermark_text,
            }

        elif edit_type == 'page_numbers':
            start_page = int(request.form.get('start_page', 1))
            position = request.form.get('position', 'bottom_right')
            output_path, output_filename = add_page_numbers_to_pdf(temp_input_path, start_page, position)
            result = {
                'type': 'page_numbers',
                'filename': output_filename,
                'start_page': start_page,
                'position': position,
            }

        elif edit_type == 'rotate':
            rotation = int(request.form.get('rotation', 90))
            output_path, output_filename = rotate_pdf_pages(temp_input_path, rotation)
            result = {
                'type': 'rotate',
                'filename': output_filename,
                'rotation': rotation,
            }

    except Exception as e:
        flash(f'Erro ao editar PDF: {str(e)}', 'danger')
        return redirect(url_for('nexuspdf_editar_pdf.editar_pdf'))
    finally:
        if os.path.exists(temp_input_path):
            try:
                os.remove(temp_input_path)
            except OSError:
                pass

    return render_template('editar_pdf.html', result=result)


@editar_pdf_bp.route('/download/<path:filename>')
def editar_pdf_download(filename: str):
    """Download do PDF editado."""
    output_path = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(output_path):
        flash('Arquivo editado não encontrado. Gere novamente a edição.', 'danger')
        return redirect(url_for('nexuspdf_editar_pdf.editar_pdf'))

    return send_file(
        output_path,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf',
    )

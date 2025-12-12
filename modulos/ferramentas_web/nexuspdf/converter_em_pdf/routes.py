from flask import Blueprint, render_template


converter_em_pdf_bp = Blueprint(
    'nexuspdf_converter_em_pdf',
    __name__,
    template_folder='templates',
    static_folder='static',
)


@converter_em_pdf_bp.route('/', methods=['GET'])
def converter_em_pdf():
    return render_template('converter_em_pdf.html')

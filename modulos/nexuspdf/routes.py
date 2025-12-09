from flask import Blueprint, render_template


nexuspdf_bp = Blueprint('nexuspdf', __name__, template_folder='templates', static_folder='static')


@nexuspdf_bp.route('/')
def nexuspdf_home():
    return render_template('nexuspdf_home.html', module_name='NexusPDF - Ferramentas de PDF e Texto')

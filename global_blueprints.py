from flask import Blueprint, render_template
from ferramentas.conversor_imagens.routes import conversor_bp
from ferramentas.gerador_de_qr_code.routes import gerador_de_qr_code_bp
from administrador.routes import administrador_bp


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template('home.html')


def register_blueprints(app):
    """Registra todos os blueprints globais da aplicação."""
    # Home / página principal
    app.register_blueprint(main_bp)
    
    # Admin
    app.register_blueprint(administrador_bp)
    
    # Conversor de imagens

    # Gerador De Qr Code
    app.register_blueprint(gerador_de_qr_code_bp, url_prefix="/gerador-de-qr-code")
    app.register_blueprint(conversor_bp, url_prefix="/conversor-imagens")
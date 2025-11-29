import os
from flask import Flask
from ferramentas.conversor_imagens.config import Config
from global_blueprints import register_blueprints
from menu_helpers import build_sidebar_menu

from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

def create_app():

    # Configurar pastas de templates e static
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template_global')
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config.from_object(Config)

    
    # Configurar chave secreta para sessões
    app.secret_key = os.getenv('SECRET_KEY', 'chave_padrao_insegura')

    # Registrar todos os blueprints da aplicação
    register_blueprints(app)

    @app.context_processor
    def inject_sidebar_menu():
        return {'sidebar_menu': build_sidebar_menu()}

    return app

# Instância global usada pelo Gunicorn/Render
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
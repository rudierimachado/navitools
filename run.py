import os
import click
from flask import Flask
from modulos.ferramentas_web.conversor_imagens.config import Config
from global_blueprints import register_blueprints
from menu_helpers import build_sidebar_menu
from extensions import db

from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

def create_app():

    # Configurar pastas de templates e static
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template_global')
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config.from_object(Config)

    # Banco de dados
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///nexusrdr.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    # Configurações Supabase (autenticação SaaS)
    app.config['SUPABASE_URL'] = os.getenv('SUPABASE_URL', 'https://wimpmajjgqgehsxspzgv.supabase.co')
    app.config['SUPABASE_ANON_KEY'] = os.getenv('SUPABASE_ANON_KEY', os.getenv('SUPABASE_KEY'))

    # Configurar chave secreta para sessões
    app.secret_key = os.getenv('SECRET_KEY', 'chave_padrao_insegura')

    # Registrar todos os blueprints da aplicação
    register_blueprints(app)

    @app.context_processor
    def inject_sidebar_menu():
        return {'sidebar_menu': build_sidebar_menu()}

    @app.cli.command('init-db')
    def init_db_command():
        """Cria as tabelas no banco configurado."""
        from models import User, LoginAudit  # noqa: F401
        with app.app_context():
            db.create_all()
        click.echo('Banco inicializado com sucesso.')

    return app

# Instância global usada pelo Gunicorn/Render
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
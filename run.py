import os
import click
from flask import Flask
from modulos.ferramentas_web.conversor_imagens.config import Config
from global_blueprints import register_blueprints
from menu_helpers import build_sidebar_menu
from extensions import db, migrate, get_current_db_url, init_database

from dotenv import load_dotenv
from jinja2 import ChoiceLoader, FileSystemLoader

# Importar detecção de dispositivo
from device_detector import device_detection_middleware, device_helper

# Carregar variáveis de ambiente
load_dotenv()

def create_app():

    # Configurar pastas de templates e static
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template_global')
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config.from_object(Config)

    # Configurar loader para múltiplas pastas de templates (admin > demais)
    default_loader = app.jinja_loader
    template_dirs = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'administrador', 'templates'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'modulos', 'gerenciamento_financeiro', 'templates'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'modulos', 'ferramentas_web', 'conversor_imagens', 'templates'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'modulos', 'ferramentas_web', 'gerador_de_qr_code', 'templates'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'modulos', 'ferramentas_web', 'removedor_de_fundo', 'templates'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'modulos', 'ferramentas_web', 'youtub_downloader', 'templates'),
    ]
    loaders = [FileSystemLoader(dir_path) for dir_path in template_dirs if os.path.exists(dir_path)]
    loaders.append(default_loader)
    app.jinja_loader = ChoiceLoader(loaders)

    # Configuração do banco usando config_db.py
    app.config['SQLALCHEMY_DATABASE_URI'] = get_current_db_url()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Inicializar extensões
    db.init_app(app)
    migrate.init_app(app, db)

    # Configurações Supabase (removido - não usado)
    # app.config['SUPABASE_URL'] = os.getenv('SUPABASE_URL', 'https://wimpmajjgqgehsxspzgv.supabase.co')
    # app.config['SUPABASE_ANON_KEY'] = os.getenv('SUPABASE_ANON_KEY', os.getenv('SUPABASE_KEY'))

    # Configurar chave secreta para sessões
    app.secret_key = os.getenv('SECRET_KEY', 'chave_padrao_insegura')

    # Registrar todos os blueprints da aplicação
    register_blueprints(app)

    # Adicionar middleware de detecção de dispositivo
    app = device_detection_middleware(app)

    @app.context_processor
    def inject_sidebar_menu():
        return {'sidebar_menu': build_sidebar_menu()}

    @app.context_processor
    def inject_device_info():
        """Injetar informações de dispositivo nos templates"""
        from device_detector import get_device_context
        return get_device_context()

    @app.cli.command('init-db')
    def init_db_command():
        """Cria as tabelas no banco configurado e popula dados iniciais."""
        with app.app_context():
            init_database()
        click.echo('✅ Banco inicializado com sucesso!')
        click.echo('📧 Admin: admin@nexusrdr.com / admin123')

    @app.cli.command('db-stats')
    def db_stats_command():
        """Mostra estatísticas do banco de dados."""
        from config_db import get_db_stats
        stats = get_db_stats()
        click.echo(f"📊 Estatísticas do Banco: {stats['type']}")
        click.echo(f"🔗 Status: {stats['status']}")
        if stats.get('tables'):
            click.echo(f"📋 Tabelas: {', '.join(stats['tables'])}")
        if stats.get('connections'):
            click.echo(f"🔗 Conexões: {stats['connections']}")

    return app

# Instância global usada pelo Gunicorn/Render
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
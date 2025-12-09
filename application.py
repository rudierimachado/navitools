# application.py
"""
Arquivo de entrada para AWS Elastic Beanstalk
AWS procura especificamente por uma variável chamada 'application'
"""

import os
import click
from flask import Flask
from modulos.ferramentas_web.conversor_imagens.config import Config
from global_blueprints import register_blueprints
from menu_helpers import build_sidebar_menu
from extensions import db, migrate, get_current_db_url, init_database
from email_service import init_mail
from apscheduler.schedulers.background import BackgroundScheduler

from dotenv import load_dotenv
from jinja2 import ChoiceLoader, FileSystemLoader

# Importar detecção de dispositivo
from device_detector import device_detection_middleware, device_helper

# Carregar variáveis de ambiente
load_dotenv()

# Desabilita ops OneDNN do TensorFlow para evitar incompatibilidades locais
os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')


def create_app() -> Flask:

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
    init_mail(app)

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

    # Scheduler para o robô de blog (intervalo configurável via ROBO_TIME em minutos)
    def _iniciar_scheduler_robo(app: Flask):
        """Inicia o scheduler em background que chama o robô de blog periodicamente.

        Se rodar_robo estiver desligado no .env, o scheduler NÃO é iniciado.
        """

        # Verificar flag global do robô antes de qualquer coisa
        rodar_robo_raw = (os.getenv("rodar_robo", "0") or "0").strip().lower()
        rodar_robo_ativo = rodar_robo_raw in {"1", "true", "yes", "sim"}

        if not rodar_robo_ativo:
            # Em desenvolvimento/produção com robô desligado, não iniciar scheduler
            print("[robo_blog] rodar_robo desativado. Scheduler não será iniciado.")
            return

        # Evitar múltiplos schedulers quando o reloader do Flask está ativo em debug
        if os.environ.get("WERKZEUG_RUN_MAIN") not in (None, "true", "True") and app.debug:
            # Processo filho já cuida do scheduler em modo debug
            pass

        scheduler = BackgroundScheduler(timezone="UTC")

        # Importação dentro da função para evitar problemas de import circular
        from robo_blog import main as robo_main

        # Intervalo em minutos (ROBO_TIME), padrão 60 se não definido ou inválido
        try:
            intervalo_min = int(os.getenv("ROBO_TIME", "60").strip())
            if intervalo_min <= 0:
                intervalo_min = 60
        except Exception:
            intervalo_min = 60

        def _job_robo_blog():
            """Wrapper que garante contexto da aplicação ao rodar o robô."""
            with app.app_context():
                robo_main()

        scheduler.add_job(
            _job_robo_blog,
            "interval",
            minutes=intervalo_min,
            id="robo_blog_job",
            replace_existing=True,
        )
        scheduler.start()

    _iniciar_scheduler_robo(app)

    return app


# Instância global usada por WSGI/Gunicorn/Elastic Beanstalk
application: Flask = create_app()

# Alias para compatibilidade com código que usa "app"
app = application


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(debug=True, host='0.0.0.0', port=port)
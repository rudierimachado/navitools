"""Ponto de entrada WSGI para o NEXUSRDR.

Exponde a variável ``application`` que o servidor (uWSGI/Gunicorn/EB) procura.
Mantém apenas logs mínimos de erro para não poluir a saída em produção.
"""
import os
import sys
import traceback
from datetime import datetime

def log_debug(message: str) -> None:
    """Log simples usado apenas para erros críticos de inicialização."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[NEXUSRDR {timestamp}] {message}")
    sys.stdout.flush()

# Variáveis globais para imports opcionais
Config = None
register_blueprints = None
build_sidebar_menu = None
db = migrate = get_current_db_url = init_database = None
init_mail = None
device_detection_middleware = device_helper = get_device_context = None
ChoiceLoader = FileSystemLoader = None

try:
    import click
    from flask import Flask

    from dotenv import load_dotenv
    _dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    load_dotenv(dotenv_path=_dotenv_path)
    load_dotenv()

    os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')

    # Config da ferramenta de conversão de imagens (SECRET_KEY, etc.)
    try:
        from modulos.ferramentas_web.conversor_imagens.config import Config
    except Exception as e:
        log_debug(f"❌ ERRO ao importar Config: {e}")
        log_debug(f"Traceback Config: {traceback.format_exc()}")
    
    try:
        from global_blueprints import register_blueprints
    except Exception as e:
        log_debug(f"❌ ERRO ao importar global_blueprints: {e}")
        log_debug(f"Traceback blueprints: {traceback.format_exc()}")
    
    try:
        from menu_helpers import build_sidebar_menu
    except Exception as e:
        log_debug(f"❌ ERRO ao importar menu_helpers: {e}")
        log_debug(f"Traceback menu: {traceback.format_exc()}")
    
    try:
        from extensions import db, migrate, get_current_db_url, init_database
    except Exception as e:
        log_debug(f"❌ ERRO ao importar extensions: {e}")
        log_debug(f"Traceback extensions: {traceback.format_exc()}")
    
    try:
        from email_service import init_mail
    except Exception as e:
        log_debug(f"❌ ERRO ao importar email_service: {e}")
        log_debug(f"Traceback email: {traceback.format_exc()}")
    
    try:
        from jinja2 import ChoiceLoader, FileSystemLoader
    except Exception as e:
        log_debug(f"❌ ERRO ao importar Jinja2: {e}")
        log_debug(f"Traceback jinja: {traceback.format_exc()}")
    
    try:
        from device_detector import device_detection_middleware, device_helper
    except Exception as e:
        log_debug(f"❌ ERRO ao importar device_detector: {e}")
        log_debug(f"Traceback device: {traceback.format_exc()}")

except Exception as e:
    log_debug(f"🚨 ERRO CRÍTICO nos imports iniciais: {e}")
    log_debug(f"Traceback completo: {traceback.format_exc()}")

def create_app():

    try:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template_global')
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
        
        app = Flask(__name__, 
                   template_folder=template_dir if os.path.exists(template_dir) else None, 
                   static_folder=static_dir if os.path.exists(static_dir) else None)

        if Config:
            app.config.from_object(Config)
            log_debug("✅ Config aplicado via from_object")
        else:
            app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'chave_padrao_insegura')
            app.config['DEBUG'] = False
        
        if ChoiceLoader and FileSystemLoader:

            try:
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

            except Exception as e:
                log_debug(f"❌ ERRO ao configurar Jinja2: {e}")
        else:
            log_debug("⚠️ Jinja2 não disponível, usando configuração padrão")
        
        if get_current_db_url:

            try:
                app.config['SQLALCHEMY_DATABASE_URI'] = get_current_db_url()
                app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
                app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
                    'pool_pre_ping': True,
                    'pool_recycle': 300,
                }

            except Exception as e:
                log_debug(f"❌ ERRO ao configurar banco: {e}")
        else:
            log_debug("⚠️ get_current_db_url não disponível")
        
        if db and migrate:

            try:
                db.init_app(app)
                migrate.init_app(app, db)

            except Exception as e:
                log_debug(f"❌ ERRO ao inicializar db/migrate: {e}")
        else:
            log_debug("⚠️ db/migrate não disponíveis")
        
        if init_mail:
            try:
                init_mail(app)
            except Exception as e:
                log_debug(f"❌ ERRO ao inicializar mail: {e}")

        app.secret_key = os.getenv('SECRET_KEY', 'chave_padrao_insegura')

        if register_blueprints:
            try:
                register_blueprints(app)

            except Exception as e:
                log_debug(f"❌ ERRO ao registrar blueprints: {e}")
                log_debug(f"Traceback blueprints: {traceback.format_exc()}")
        else:
            log_debug("⚠️ register_blueprints não disponível")
        
        if device_detection_middleware:
            try:
                app = device_detection_middleware(app)
            except Exception as e:
                log_debug(f"❌ ERRO ao aplicar device detection: {e}")

        else:
            log_debug("⚠️ device_detection_middleware não disponível")
        
        @app.context_processor
        def inject_sidebar_menu():
            if build_sidebar_menu:
                try:
                    return {'sidebar_menu': build_sidebar_menu()}
                except Exception as e:
                    log_debug(f"❌ ERRO em build_sidebar_menu: {e}")
                    return {'sidebar_menu': []}

            return {'sidebar_menu': []}
        
        @app.context_processor
        def inject_device_info():
            try:
                from device_detector import get_device_context
                return get_device_context()
            except Exception as e:
                log_debug(f"❌ ERRO em get_device_context: {e}")
                return {}

        @app.cli.command('init-db')
        def init_db_command():
            if init_database:
                try:
                    with app.app_context():
                        init_database()
                    click.echo('✅ Banco inicializado com sucesso!')
                    click.echo('🔧 Admin: admin@nexusrdr.com / admin123')
                except Exception as e:
                    click.echo(f'❌ Erro: {e}')
            else:
                click.echo('❌ init_database não disponível')

        @app.cli.command('db-stats')
        def db_stats_command():
            try:
                from config_db import get_db_stats
                stats = get_db_stats()
                click.echo(f"📊 Estatísticas do Banco: {stats['type']}")
                click.echo(f"🔗 Status: {stats['status']}")
                if stats.get('tables'):
                    click.echo(f"📋 Tabelas: {', '.join(stats['tables'])}")
                if stats.get('connections'):
                    click.echo(f"🔗 Conexões: {stats['connections']}")
            except Exception as e:
                click.echo(f'❌ Erro: {e}')

        # Health check simples
        @app.route('/health')
        def health():
            return "OK"
        
        return app
        
    except Exception as e:
        log_debug(f"🚨 ERRO CRÍTICO em create_app(): {e}")
        log_debug(f"Traceback create_app: {traceback.format_exc()}")
        
        # App de fallback
        fallback_app = Flask(__name__)
        
        @fallback_app.route('/')
        def error_page():
            return f"""
            <h1>❌ Erro de Inicialização</h1>
            <p><strong>Erro:</strong> {str(e)}</p>
            <pre>{traceback.format_exc()}</pre>
            """
        
        return fallback_app

try:
    application = create_app()
    app = application  # Alias para compatibilidade

except Exception as e:  # pragma: no cover - fallback de segurança
    log_debug(f"🚨 ERRO CRÍTICO ao criar application: {e}")
    log_debug(f"Traceback final: {traceback.format_exc()}")

    from flask import Flask
    application = Flask(__name__)
    app = application

    @application.route('/')
    def emergency():  # type: ignore[misc]
        return f"<h1>Erro crítico:</h1><pre>{str(e)}\n\n{traceback.format_exc()}</pre>"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Sem modo debug para não expor informações sensíveis/extras
    application.run(debug=False, host='0.0.0.0', port=port)
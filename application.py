# application.py
"""
Arquivo de entrada para AWS Elastic Beanstalk com logs detalhados
AWS procura especificamente por uma variável chamada 'application'
"""

import os
import sys
import traceback
from datetime import datetime

def log_debug(message):
    """Log personalizado que aparece nos logs do EB"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[NEXUSRDR-DEBUG {timestamp}] {message}")
    sys.stdout.flush()

# Variáveis globais para imports opcionais
Config = None
register_blueprints = None
build_sidebar_menu = None
db = migrate = get_current_db_url = init_database = None
init_mail = None
device_detection_middleware = device_helper = get_device_context = None
BackgroundScheduler = None
ChoiceLoader = FileSystemLoader = None

try:
    log_debug("1. Importando módulos básicos...")
    import click
    from flask import Flask
    log_debug("✅ Flask e click importados")
    
    log_debug("2. Carregando dotenv...")
    from dotenv import load_dotenv
    load_dotenv()
    log_debug("✅ dotenv carregado")
    
    log_debug("3. Configurando variável TensorFlow...")
    os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')
    log_debug("✅ TF_ENABLE_ONEDNN_OPTS configurado")
    
    log_debug("4. Importando Config...")
    try:
        from modulos.ferramentas_web.conversor_imagens.config import Config
        log_debug("✅ Config importado com sucesso")
    except Exception as e:
        log_debug(f"❌ ERRO ao importar Config: {e}")
        log_debug(f"Traceback Config: {traceback.format_exc()}")
    
    log_debug("5. Importando global_blueprints...")
    try:
        from global_blueprints import register_blueprints
        log_debug("✅ global_blueprints importado com sucesso")
    except Exception as e:
        log_debug(f"❌ ERRO ao importar global_blueprints: {e}")
        log_debug(f"Traceback blueprints: {traceback.format_exc()}")
    
    log_debug("6. Importando menu_helpers...")
    try:
        from menu_helpers import build_sidebar_menu
        log_debug("✅ menu_helpers importado com sucesso")
    except Exception as e:
        log_debug(f"❌ ERRO ao importar menu_helpers: {e}")
        log_debug(f"Traceback menu: {traceback.format_exc()}")
    
    log_debug("7. Importando extensions...")
    try:
        from extensions import db, migrate, get_current_db_url, init_database
        log_debug("✅ extensions importado com sucesso")
    except Exception as e:
        log_debug(f"❌ ERRO ao importar extensions: {e}")
        log_debug(f"Traceback extensions: {traceback.format_exc()}")
    
    log_debug("8. Importando email_service...")
    try:
        from email_service import init_mail
        log_debug("✅ email_service importado com sucesso")
    except Exception as e:
        log_debug(f"❌ ERRO ao importar email_service: {e}")
        log_debug(f"Traceback email: {traceback.format_exc()}")
    
    log_debug("9. Importando APScheduler...")
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        log_debug("✅ APScheduler importado com sucesso")
    except Exception as e:
        log_debug(f"❌ ERRO ao importar APScheduler: {e}")
        log_debug(f"Traceback scheduler: {traceback.format_exc()}")
    
    log_debug("10. Importando Jinja2...")
    try:
        from jinja2 import ChoiceLoader, FileSystemLoader
        log_debug("✅ Jinja2 importado com sucesso")
    except Exception as e:
        log_debug(f"❌ ERRO ao importar Jinja2: {e}")
        log_debug(f"Traceback jinja: {traceback.format_exc()}")
    
    log_debug("11. Importando device_detector...")
    try:
        from device_detector import device_detection_middleware, device_helper
        log_debug("✅ device_detector importado com sucesso")
    except Exception as e:
        log_debug(f"❌ ERRO ao importar device_detector: {e}")
        log_debug(f"Traceback device: {traceback.format_exc()}")

except Exception as e:
    log_debug(f"🚨 ERRO CRÍTICO nos imports iniciais: {e}")
    log_debug(f"Traceback completo: {traceback.format_exc()}")

def create_app():
    log_debug("=== INICIANDO create_app() ===")
    
    try:
        log_debug("12. Configurando diretórios de templates e static...")
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template_global')
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
        
        log_debug(f"Template dir: {template_dir}")
        log_debug(f"Static dir: {static_dir}")
        log_debug(f"Template dir exists: {os.path.exists(template_dir)}")
        log_debug(f"Static dir exists: {os.path.exists(static_dir)}")
        
        log_debug("13. Criando instância Flask...")
        app = Flask(__name__, 
                   template_folder=template_dir if os.path.exists(template_dir) else None, 
                   static_folder=static_dir if os.path.exists(static_dir) else None)
        log_debug("✅ Instância Flask criada")
        
        log_debug("14. Configurando Flask com Config...")
        if Config:
            app.config.from_object(Config)
            log_debug("✅ Config aplicado via from_object")
        else:
            log_debug("⚠️ Config não disponível, usando configuração básica")
            app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'chave_padrao_insegura')
            app.config['DEBUG'] = False
        
        log_debug("15. Configurando Jinja2 loaders...")
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
                log_debug("✅ Jinja2 loaders configurados")
            except Exception as e:
                log_debug(f"❌ ERRO ao configurar Jinja2: {e}")
        else:
            log_debug("⚠️ Jinja2 não disponível, usando configuração padrão")
        
        log_debug("16. Configurando banco de dados...")
        if get_current_db_url:
            try:
                app.config['SQLALCHEMY_DATABASE_URI'] = get_current_db_url()
                app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
                app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
                    'pool_pre_ping': True,
                    'pool_recycle': 300,
                }
                log_debug("✅ Configuração do banco aplicada")
            except Exception as e:
                log_debug(f"❌ ERRO ao configurar banco: {e}")
        else:
            log_debug("⚠️ get_current_db_url não disponível")
        
        log_debug("17. Inicializando extensões...")
        if db and migrate:
            try:
                db.init_app(app)
                migrate.init_app(app, db)
                log_debug("✅ SQLAlchemy e Migrate inicializados")
            except Exception as e:
                log_debug(f"❌ ERRO ao inicializar db/migrate: {e}")
        else:
            log_debug("⚠️ db/migrate não disponíveis")
        
        if init_mail:
            try:
                init_mail(app)
                log_debug("✅ Mail inicializado")
            except Exception as e:
                log_debug(f"❌ ERRO ao inicializar mail: {e}")
        else:
            log_debug("⚠️ init_mail não disponível")
        
        log_debug("18. Configurando chave secreta...")
        app.secret_key = os.getenv('SECRET_KEY', 'chave_padrao_insegura')
        log_debug("✅ Chave secreta configurada")
        
        log_debug("19. Registrando blueprints...")
        if register_blueprints:
            try:
                register_blueprints(app)
                log_debug("✅ Blueprints registrados")
            except Exception as e:
                log_debug(f"❌ ERRO ao registrar blueprints: {e}")
                log_debug(f"Traceback blueprints: {traceback.format_exc()}")
        else:
            log_debug("⚠️ register_blueprints não disponível")
        
        log_debug("20. Configurando device detection...")
        if device_detection_middleware:
            try:
                app = device_detection_middleware(app)
                log_debug("✅ Device detection aplicado")
            except Exception as e:
                log_debug(f"❌ ERRO ao aplicar device detection: {e}")
        else:
            log_debug("⚠️ device_detection_middleware não disponível")
        
        log_debug("21. Configurando context processors...")
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
        
        log_debug("✅ Context processors configurados")
        
        log_debug("22. Configurando comandos CLI...")
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
        
        log_debug("✅ Comandos CLI configurados")
        
        log_debug("23. Configurando scheduler...")
        def _iniciar_scheduler_robo(app):
            try:
                rodar_robo_raw = (os.getenv("rodar_robo", "0") or "0").strip().lower()
                rodar_robo_ativo = rodar_robo_raw in {"1", "true", "yes", "sim"}
                
                if not rodar_robo_ativo:
                    log_debug("[robo_blog] rodar_robo desativado. Scheduler não será iniciado.")
                    return
                
                if not BackgroundScheduler:
                    log_debug("❌ BackgroundScheduler não disponível")
                    return
                
                if os.environ.get("WERKZEUG_RUN_MAIN") not in (None, "true", "True") and app.debug:
                    pass
                
                scheduler = BackgroundScheduler(timezone="UTC")
                
                try:
                    from robo_blog import main as robo_main
                    
                    intervalo_min = int(os.getenv("ROBO_TIME", "60").strip())
                    if intervalo_min <= 0:
                        intervalo_min = 60
                    
                    def _job_robo_blog():
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
                    log_debug("✅ Scheduler iniciado")
                    
                except Exception as e:
                    log_debug(f"❌ ERRO ao configurar scheduler: {e}")
                    
            except Exception as e:
                log_debug(f"❌ ERRO geral no scheduler: {e}")
        
        _iniciar_scheduler_robo(app)
        
        # Rotas básicas para debug
        @app.route('/')
        def index():
            return """
            <h1>🎉 NEXUSRDR FUNCIONANDO NA AWS!</h1>
            <p>Aplicação carregada com sucesso!</p>
            <a href="/debug">Ver informações de debug</a><br>
            <a href="/health">Health check</a>
            """
        
        @app.route('/debug')
        def debug_info():
            return f"""
            <h2>🔍 Informações de Debug:</h2>
            <p><strong>Python:</strong> {sys.version}</p>
            <p><strong>Diretório:</strong> {os.getcwd()}</p>
            <p><strong>Arquivos:</strong> {os.listdir('.')}</p>
            <p><strong>Environment PORT:</strong> {os.environ.get('PORT', 'Not set')}</p>
            <p><strong>Config loaded:</strong> {Config is not None}</p>
            <p><strong>Blueprints loaded:</strong> {register_blueprints is not None}</p>
            <p><strong>Database loaded:</strong> {db is not None}</p>
            """
        
        @app.route('/health')
        def health():
            return "OK"
        
        log_debug("✅ Rotas básicas configuradas")
        log_debug("=== create_app() FINALIZADO COM SUCESSO ===")
        
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
    log_debug("24. Criando instância da aplicação...")
    application = create_app()
    app = application  # Alias para compatibilidade
    log_debug("✅ Instância 'application' criada com sucesso")
    
except Exception as e:
    log_debug(f"🚨 ERRO CRÍTICO ao criar application: {e}")
    log_debug(f"Traceback final: {traceback.format_exc()}")
    
    # Aplicação de emergência
    from flask import Flask
    application = Flask(__name__)
    app = application
    
    @application.route('/')
    def emergency():
        return f"<h1>Erro crítico:</h1><pre>{str(e)}\n\n{traceback.format_exc()}</pre>"

log_debug("=== INICIALIZAÇÃO COMPLETA ===")

if __name__ == '__main__':
    log_debug("Iniciando servidor local...")
    port = int(os.environ.get('PORT', 5000))
    application.run(debug=True, host='0.0.0.0', port=port)
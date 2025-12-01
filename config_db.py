"""
Configuração Centralizada do Banco de Dados - NEXUSRDR
====================================================

Este arquivo centraliza todas as configurações de banco de dados,
credenciais e conexões utilizadas pela aplicação.

Suporte a múltiplos bancos:
- PostgreSQL (produção - Render)
- SQLite (desenvolvimento/local)

Uso:
    from config_db import get_db_config, create_engine, init_database

    # Configuração completa
    config = get_db_config()

    # Engine SQLAlchemy
    engine = create_engine()

    # Inicialização do banco
    init_database()
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# Base para modelos SQLAlchemy
Base = declarative_base()

# Configurações padrão
DEFAULT_CONFIG = {
    # PostgreSQL (Produção)
    'postgresql': {
        'host': 'localhost',
        'port': 5432,
        'database': 'nexusrdr',
        'username': 'postgres',
        'password': '',
        'sslmode': 'require'
    },

    # SQLite (Desenvolvimento)
    'sqlite': {
        'database': 'nexusrdr.db',
        'path': './instance/nexusrdr.db'
    },

    # Supabase (SaaS)
    'supabase': {
        'url': 'https://wimpmajjgqgehsxspzgv.supabase.co',
        'anon_key': '',
        'service_role_key': ''
    }
}


def get_db_config(db_type: str = 'auto') -> Dict[str, Any]:
    """
    Retorna configuração completa do banco de dados.

    Args:
        db_type: Tipo de banco ('postgresql', 'sqlite', 'auto')

    Returns:
        Dicionário com configurações do banco
    """

    # Detectar tipo de banco automaticamente
    if db_type == 'auto':
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            parsed = urlparse(database_url)
            if parsed.scheme.startswith('postgres'):
                actual_db_type = 'postgresql'
            elif parsed.scheme == 'sqlite':
                actual_db_type = 'sqlite'
            else:
                # Fallback para PostgreSQL se não reconhecer
                actual_db_type = 'postgresql'
        else:
            # Sem DATABASE_URL, usar SQLite por padrão
            actual_db_type = 'sqlite'
    else:
        actual_db_type = db_type

    # Agora pegar a configuração para o tipo detectado
    config = DEFAULT_CONFIG.get(actual_db_type, {}).copy()

    # Sobrescrever com variáveis de ambiente
    if actual_db_type == 'postgresql':
        config.update({
            'host': os.getenv('DB_HOST', config.get('host')),
            'port': int(os.getenv('DB_PORT', config.get('port'))),
            'database': os.getenv('DB_NAME', config.get('database')),
            'username': os.getenv('DB_USER', config.get('username')),
            'password': os.getenv('DB_PASSWORD', config.get('password')),
            'sslmode': os.getenv('DB_SSLMODE', config.get('sslmode'))
        })

    elif actual_db_type == 'sqlite':
        config.update({
            'database': os.getenv('SQLITE_DB', config.get('database')),
            'path': os.getenv('SQLITE_PATH', config.get('path'))
        })

    return config


def get_database_url(db_type: str = 'auto') -> str:
    """
    Retorna a URL de conexão completa para o banco.

    Args:
        db_type: Tipo de banco desejado

    Returns:
        String com URL de conexão SQLAlchemy
    """

    # Se db_type for 'auto' e houver DATABASE_URL, usar diretamente
    if db_type == 'auto':
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            return database_url

    # Caso contrário, construir a URL normalmente
    config = get_db_config(db_type)

    if db_type in ['postgresql', 'auto'] and 'host' in config:
        # PostgreSQL
        return f"postgresql://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"

    elif db_type == 'sqlite' or (db_type == 'auto' and 'database' in config and config.get('database', '').endswith('.db')):
        # SQLite
        db_path = config.get('path', f"./instance/{config['database']}")
        return f"sqlite:///{db_path}"

    elif db_type == 'supabase':
        # Supabase usa PostgreSQL, mas com URL especial
        return os.getenv('DATABASE_URL', f"postgresql://postgres:password@localhost:54322/postgres")

    # Fallback para SQLite
    return "sqlite:///instance/nexusrdr.db"


def create_engine(db_type: str = 'auto', echo: bool = False):
    """
    Cria engine SQLAlchemy configurada.

    Args:
        db_type: Tipo de banco
        echo: Se deve imprimir queries SQL

    Returns:
        Engine SQLAlchemy configurada
    """

    database_url = get_database_url(db_type)

    return create_engine(database_url, echo=echo)


def create_session_factory(engine):
    """
    Cria factory de sessões SQLAlchemy.

    Args:
        engine: Engine SQLAlchemy

    Returns:
        Session factory configurada
    """
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _create_engine_direct(database_url: str, echo: bool = False):
    """
    Cria engine SQLAlchemy diretamente com URL já resolvida.
    """
    return create_engine(database_url, echo=echo)


def init_database(db_type: str = 'auto', create_tables: bool = True):
    """
    Inicializa o banco de dados criando tabelas e dados iniciais.

    Args:
        db_type: Tipo de banco
        create_tables: Se deve criar tabelas automaticamente
    """

    # Determinar tipo de banco
    if db_type == 'auto':
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            parsed = urlparse(database_url)
            if parsed.scheme.startswith('postgres'):
                actual_db_type = 'postgresql'
            elif parsed.scheme == 'sqlite':
                actual_db_type = 'sqlite'
            else:
                actual_db_type = 'postgresql'
        else:
            actual_db_type = 'sqlite'
            database_url = 'sqlite:///instance/nexusrdr.db'
    else:
        actual_db_type = db_type
        if db_type == 'sqlite':
            database_url = 'sqlite:///instance/nexusrdr.db'
        else:
            database_url = get_database_url(db_type)

    if create_tables:
        # Importar todos os modelos para criar tabelas
        try:
            from models import User, LoginAudit, AdminUser, MenuItem

            # Criar engine diretamente
            engine = _create_engine_direct(database_url, echo=False)

            # Criar todas as tabelas
            Base.metadata.create_all(bind=engine)

            print("✅ Tabelas criadas/atualizadas com sucesso!")

            # Popular dados iniciais
            _seed_initial_data_direct(engine, actual_db_type)

        except ImportError as e:
            print(f"⚠️  Aviso: Não foi possível importar modelos: {e}")
            print("   Execute manualmente: from models import User, LoginAudit, AdminUser, MenuItem")

    # Testar conexão
    try:
        engine = _create_engine_direct(database_url, echo=False)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ Conexão com banco estabelecida com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao conectar com banco: {e}")
        raise


def _seed_initial_data_direct(engine, db_type):
    """
    Popula dados iniciais no banco usando engine diretamente.
    """

    SessionLocal = create_session_factory(engine)
    session = SessionLocal()

    try:
        # Verificar se já existem dados
        from models import MenuItem

        # Menu items iniciais
        if session.query(MenuItem).count() == 0:
            menu_items = [
                MenuItem(nome="Ferramentas Web", nivel=1, ordem=1, ativo=True, icone="tools", url="/"),
                MenuItem(nome="Sistemas", nivel=1, ordem=2, ativo=True, icone="server", url="/"),
                MenuItem(nome="Conversor de Imagens", nivel=2, ordem=1, ativo=True, icone="image", url="/conversor-imagens", parent_id=1),
                MenuItem(nome="Removedor de Fundo", nivel=2, ordem=2, ativo=True, icone="image", url="/removedor-de-fundo", parent_id=1),
                MenuItem(nome="Gerador de QR Code", nivel=2, ordem=3, ativo=True, icone="qr-code", url="/gerador-de-qr-code", parent_id=1),
                MenuItem(nome="YouTube Downloader", nivel=2, ordem=4, ativo=True, icone="youtube", url="/youtube-downloader", parent_id=1),
                MenuItem(nome="Gestão Financeira Familiar", nivel=2, ordem=1, ativo=True, icone="cash-coin", url="/gerenciamento-financeiro/login", parent_id=2),
            ]

            session.add_all(menu_items)
            print("✅ Menu inicial populado!")

        session.commit()

    except Exception as e:
        session.rollback()
        print(f"⚠️  Erro ao popular dados iniciais: {e}")

    finally:
        session.close()


def _seed_initial_data(engine):
    """
    Popula dados iniciais no banco (menus)
    """

    SessionLocal = create_session_factory(engine)
    session = SessionLocal()

    try:
        # Verificar se já existem dados
        from models import MenuItem

        # Menu items iniciais
        if session.query(MenuItem).count() == 0:
            menu_items = [
                MenuItem(nome="Ferramentas Web", nivel=1, ordem=1, ativo=True, icone="tools", url="/"),
                MenuItem(nome="Sistemas", nivel=1, ordem=2, ativo=True, icone="server", url="/"),
                MenuItem(nome="Conversor de Imagens", nivel=2, ordem=1, ativo=True, icone="image", url="/conversor-imagens", parent_id=1),
                MenuItem(nome="Removedor de Fundo", nivel=2, ordem=2, ativo=True, icone="image", url="/removedor-de-fundo", parent_id=1),
                MenuItem(nome="Gerador de QR Code", nivel=2, ordem=3, ativo=True, icone="qr-code", url="/gerador-de-qr-code", parent_id=1),
                MenuItem(nome="YouTube Downloader", nivel=2, ordem=4, ativo=True, icone="youtube", url="/youtube-downloader", parent_id=1),
                MenuItem(nome="Gestão Financeira Familiar", nivel=2, ordem=1, ativo=True, icone="cash-coin", url="/gerenciamento-financeiro/login", parent_id=2),
            ]

            session.add_all(menu_items)
            print("✅ Menu inicial populado!")

        session.commit()

    except Exception as e:
        session.rollback()
        print(f"⚠️  Erro ao popular dados iniciais: {e}")

    finally:
        session.close()


def get_db_stats(db_type: str = 'auto') -> Dict[str, Any]:
    """
    Retorna estatísticas do banco de dados.

    Returns:
        Dicionário com estatísticas
    """

    # Determinar tipo de banco
    if db_type == 'auto':
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            parsed = urlparse(database_url)
            if parsed.scheme.startswith('postgres'):
                actual_db_type = 'postgresql'
                # Usar URL diretamente para PostgreSQL
                actual_url = database_url
            elif parsed.scheme == 'sqlite':
                actual_db_type = 'sqlite'
                actual_url = database_url
            else:
                actual_db_type = 'postgresql'
                actual_url = database_url
        else:
            actual_db_type = 'sqlite'
            actual_url = 'sqlite:///instance/nexusrdr.db'
    else:
        actual_db_type = db_type
        actual_url = get_database_url(db_type)

    stats = {
        'type': actual_db_type,
        'url': actual_url.replace(actual_url.split('@')[0].split(':')[2] if '@' in actual_url else '', '***') if actual_url.startswith('postgresql') else actual_url,
        'tables': [],
        'connections': 0
    }

    try:
        if actual_db_type == 'postgresql':
            # Usar psycopg2 diretamente com a URL
            import psycopg2
            conn = psycopg2.connect(actual_url)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT schemaname, tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
            stats['tables'] = [row[1] for row in cursor.fetchall()]

            cursor.execute("SELECT count(*) FROM pg_stat_activity")
            stats['connections'] = cursor.fetchone()[0]

            cursor.close()
            conn.close()

        elif actual_db_type == 'sqlite':
            import sqlite3
            db_path = actual_url.replace('sqlite:///', '')
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            stats['tables'] = [row[0] for row in cursor.fetchall()]

            cursor.close()
            conn.close()

        stats['status'] = 'connected'

    except Exception as e:
        stats['status'] = f'error: {str(e)}'

    return stats

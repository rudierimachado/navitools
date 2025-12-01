"""
Extensões Flask - Configuração Centralizada
==========================================

Este arquivo contém todas as extensões Flask configuradas
para uso em toda a aplicação NEXUSRDR.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

# Instância global do SQLAlchemy
db = SQLAlchemy()

# Instância global do Flask-Migrate
migrate = Migrate()

# Importar funções de configuração (lazy loading)
from config_db import get_db_config, get_database_url, create_engine, init_database, get_db_stats

# Função para obter configuração atual
def get_current_db_config():
    """Retorna configuração atual do banco"""
    return get_db_config('auto')

def get_current_db_url():
    """Retorna URL atual do banco"""
    return get_database_url('auto')

# Exportar configurações para uso global
__all__ = [
    'db',
    'migrate',
    'get_current_db_config',
    'get_current_db_url',
    'init_database'
]

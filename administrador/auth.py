from functools import wraps
import hmac
import os
from flask import session, redirect, url_for, request
from sqlalchemy import func
from werkzeug.security import check_password_hash

from models import AdminUser

def login_required(f):
    """Decorator para proteger rotas que precisam de autenticação"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('administrador.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def check_credentials(username, password):
    """Verifica credenciais contra a tabela admin_users"""
    username = (username or '').strip().lower()
    password = password or ''

    if not username or not password:
        return False

    env_username = (os.getenv('ADMIN_USERNAME') or '').strip().lower()
    env_password = os.getenv('ADMIN_PASSWORD') or ''

    # Se credenciais estiverem definidas no ambiente, elas são a fonte de verdade
    # para login do painel admin (sem depender do banco).
    if env_username and env_password:
        return hmac.compare_digest(username, env_username) and hmac.compare_digest(password, env_password)

    admin = AdminUser.query.filter(
        func.lower(AdminUser.username) == username,
        AdminUser.is_active.is_(True)
    ).first()

    if not admin:
        return False

    try:
        return check_password_hash(admin.password_hash, password) if admin.password_hash else False
    except ValueError:
        return False

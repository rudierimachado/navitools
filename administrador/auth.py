import os
from functools import wraps
from flask import session, redirect, url_for, request
from dotenv import load_dotenv

# Carregar variáveis do .env
load_dotenv()

def login_required(f):
    """Decorator para proteger rotas que precisam de autenticação"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('administrador.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def check_credentials(username, password):
    """Verifica se as credenciais estão corretas"""
    admin_username = os.getenv('ADMIN_USERNAME')
    admin_password = os.getenv('ADMIN_PASSWORD')
    
    return username == admin_username and password == admin_password

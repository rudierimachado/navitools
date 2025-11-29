import os
import json
from flask import Blueprint, render_template, abort

from ferramentas.conversor_imagens.routes import conversor_bp
from ferramentas.gerador_de_qr_code.routes import gerador_de_qr_code_bp
from administrador.routes import administrador_bp


main_bp = Blueprint("main", __name__)

def load_content_data():
    """Carrega dados de conteúdo do arquivo JSON"""
    content_file = os.path.join(os.path.dirname(__file__), 'administrador', 'content_data.json')
    try:
        with open(content_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "posts": []
        }

@main_bp.route("/")
def index():
    content_data = load_content_data()
    posts = [post for post in content_data.get('posts', []) if post.get('active', False)]

    # Ordenar por data (mais recente primeiro)
    def post_sort_key(post):
        return post.get('date') or ''

    novidades_posts = sorted(
        [p for p in posts if p.get('section') == 'novidades'],
        key=post_sort_key,
        reverse=True
    )
    dicas_posts = sorted(
        [p for p in posts if p.get('section') == 'dicas'],
        key=post_sort_key,
        reverse=True
    )

    return render_template('home.html', novidades_posts=novidades_posts, dicas_posts=dicas_posts)

@main_bp.route("/ia-hub")
def ia_hub():
    content_data = load_content_data()
    return render_template('ia_hub.html', content_data=content_data)

@main_bp.route("/blog")
def blog_list():
    content_data = load_content_data()
    posts = sorted(
        [post for post in content_data.get('posts', []) if post.get('active', False)],
        key=lambda p: p.get('date') or '',
        reverse=True
    )
    return render_template('blog_list.html', posts=posts)

@main_bp.route("/blog/<int:post_id>")
def blog_detail(post_id):
    content_data = load_content_data()
    posts = content_data.get('posts', [])
    post = next((p for p in posts if p.get('id') == post_id and p.get('active', False)), None)

    if not post:
        abort(404)

    return render_template('blog_detail.html', post=post)

def register_blueprints(app):
    """Registra todos os blueprints globais da aplicação."""
    # Home / página principal
    app.register_blueprint(main_bp)
    
    # Admin
    app.register_blueprint(administrador_bp)
    
    # Conversor de imagens

    # Gerador De Qr Code
    app.register_blueprint(gerador_de_qr_code_bp, url_prefix="/gerador-de-qr-code")
    app.register_blueprint(conversor_bp, url_prefix="/conversor-imagens")
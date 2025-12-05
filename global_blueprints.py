import os
import smtplib
import ssl
from email.message import EmailMessage

from dotenv import load_dotenv
from flask import (
    Blueprint,
    render_template,
    abort,
    send_from_directory,
    g,
    request,
)
from sqlalchemy import case, or_

from administrador.routes import administrador_bp
from extensions import db
from modulos.gerenciamento_financeiro.routes import gerenciamento_financeiro_bp
from modulos.ferramentas_web.youtub_downloader.routes import youtube_bp
from modulos.ferramentas_web.conversor_imagens.routes import conversor_bp
from modulos.ferramentas_web.gerador_de_qr_code.routes import gerador_de_qr_code_bp
from modulos.ferramentas_web.removedor_de_fundo.routes import removedor_de_fundo_bp
from models import BlogPost

load_dotenv()

main_bp = Blueprint("main", __name__)

BLOG_CATEGORIES = [
    ("tecnologia", "Tecnologia & Ferramentas"),
    ("inteligencia-artificial", "Inteligência Artificial"),
    ("tutoriais", "Tutoriais & Guias"),
    ("produtividade", "Produtividade"),
    ("design", "Design & Criatividade"),
    ("marketing", "Marketing Digital"),
    ("programacao", "Programação"),
    ("novidades", "Novidades & Updates"),
    ("dicas", "Dicas & Truques"),
]

BLOG_SECTIONS = [
    ("novidades", "Novidades"),
    ("dicas", "Dicas"),
    ("destaque", "Destaques"),
    ("geral", "Geral"),
]

def _priority_order():
    return case(
        (BlogPost.priority == 'pinned', 3),
        (BlogPost.priority == 'featured', 2),
        else_=1
    )

def get_category_info(category):
    """Helper para informações das categorias"""
    categories = {
        'tecnologia': {'name': 'Tecnologia & Ferramentas', 'emoji': '🔧', 'color': 'primary', 'icon': 'gear'},
        'inteligencia-artificial': {'name': 'Inteligência Artificial', 'emoji': '🤖', 'color': 'info', 'icon': 'robot'},
        'tutoriais': {'name': 'Tutoriais & Guias', 'emoji': '📚', 'color': 'warning', 'icon': 'book'},
        'produtividade': {'name': 'Produtividade', 'emoji': '⚡', 'color': 'success', 'icon': 'lightning'},
        'design': {'name': 'Design & Criatividade', 'emoji': '🎨', 'color': 'danger', 'icon': 'palette'},
        'marketing': {'name': 'Marketing Digital', 'emoji': '📈', 'color': 'info', 'icon': 'graph-up'},
        'programacao': {'name': 'Programação', 'emoji': '💻', 'color': 'dark', 'icon': 'code'},
        'novidades': {'name': 'Novidades & Updates', 'emoji': '🆕', 'color': 'primary', 'icon': 'star'},
        'dicas': {'name': 'Dicas & Truques', 'emoji': '💡', 'color': 'success', 'icon': 'lightbulb'}
    }
    return categories.get(category, {'name': 'Geral', 'emoji': '📄', 'color': 'secondary', 'icon': 'file-text'})

def render_markdown(content):
    """Converte markdown simples para HTML"""
    if not content:
        return ""
    
    import re
    
    # Converter markdown básico para HTML
    html = content
    
    # Títulos
    html = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.*?)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.*?)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    
    # Negrito e itálico
    html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.*?)\*', r'<em>\1</em>', html)
    
    # Links
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', html)
    
    # Listas
    lines = html.split('\n')
    in_list = False
    result_lines = []
    
    for line in lines:
        if line.strip().startswith('- '):
            if not in_list:
                result_lines.append('<ul>')
                in_list = True
            result_lines.append(f'<li>{line.strip()[2:]}</li>')
        else:
            if in_list:
                result_lines.append('</ul>')
                in_list = False
            result_lines.append(line)
    
    if in_list:
        result_lines.append('</ul>')
    
    html = '\n'.join(result_lines)
    
    # Quebras de linha
    html = html.replace('\n\n', '</p><p>')
    html = html.replace('\n', '<br>')
    html = f'<p>{html}</p>'
    
    # Limpar parágrafos vazios
    html = re.sub(r'<p>\s*</p>', '', html)
    html = re.sub(r'<p>\s*<(h[1-6]|ul)', r'<\1', html)
    html = re.sub(r'</(h[1-6]|ul)>\s*</p>', r'</\1>', html)
    
    return html

@main_bp.route('/logos/<filename>')
def serve_logo(filename):
    """Servir arquivos da pasta logos"""
    logos_dir = os.path.join(os.path.dirname(__file__), 'logos')
    return send_from_directory(logos_dir, filename)

@main_bp.route("/")
def index():
    priority_order = _priority_order()
    active_posts = (
        BlogPost.query
        .filter_by(active=True)
        .order_by(priority_order.desc(), BlogPost.created_at.desc())
        .all()
    )

    novidades_posts = [p for p in active_posts if p.section == 'novidades']
    dicas_posts = [p for p in active_posts if p.section == 'dicas']
    destaque_posts = [
        p for p in active_posts
        if p.section == 'destaque' or p.priority in ('featured', 'pinned')
    ]

    return render_template(
        'home.html',
        novidades_posts=novidades_posts,
        dicas_posts=dicas_posts,
        destaque_posts=destaque_posts,
        get_category_info=get_category_info,
    )

@main_bp.route("/ia-hub")
def ia_hub():
    posts = (
        BlogPost.query
        .filter_by(active=True)
        .order_by(BlogPost.created_at.desc())
        .limit(6)
        .all()
    )
    return render_template('ia_hub.html', posts=posts)

def send_contact_email(name: str, email: str, message: str) -> tuple[bool, str]:
    gmail_user = os.getenv('GMAIL_USER') or os.getenv('CONTACT_EMAIL') or 'rudirimachado@gmail.com'
    gmail_password = os.getenv('GMAIL_PASSWORD')
    recipient = os.getenv('CONTACT_DEST_EMAIL', gmail_user)

    if not gmail_password:
        return False, 'Configuração de e-mail ausente. Defina GMAIL_USER e GMAIL_PASSWORD.'

    email_message = EmailMessage()
    email_message['Subject'] = f'[NEXUSRDR] Novo contato de {name}'
    email_message['From'] = gmail_user
    email_message['To'] = recipient
    email_message.set_content(
        f"Nome: {name}\nE-mail: {email}\n\nMensagem:\n{message}"
    )

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(email_message)
        return True, 'Mensagem enviada com sucesso. Vou responder em breve!'
    except smtplib.SMTPException as exc:
        return False, f'Não foi possível enviar o e-mail: {exc}'

@main_bp.route("/contact", methods=["GET", "POST"])
def contact():
    form_status = None

    if request.method == 'POST':
        name = request.form.get('Nome', '').strip()
        email = request.form.get('E-mail', '').strip()
        message = request.form.get('Mensagem', '').strip()

        if not all([name, email, message]):
            form_status = {
                'type': 'danger',
                'message': 'Preencha nome, e-mail e mensagem antes de enviar.'
            }
        else:
            success, feedback = send_contact_email(name, email, message)
            form_status = {
                'type': 'success' if success else 'danger',
                'message': feedback
            }

    return render_template('contact.html', form_status=form_status)

@main_bp.route("/privacy")
def privacy():
    return render_template('privacy.html')

@main_bp.route("/terms")
def terms():
    from datetime import datetime
    return render_template('terms.html', current_year=datetime.now().strftime('%Y'))

@main_bp.route("/blog")
def blog_list():
    section_filter = request.args.get('section')
    category_filter = request.args.get('category')
    search_query = request.args.get('search', '').strip()

    query = BlogPost.query.filter(BlogPost.active.is_(True))

    if section_filter:
        query = query.filter(BlogPost.section == section_filter)

    if category_filter:
        query = query.filter(BlogPost.category == category_filter)

    if search_query:
        like_pattern = f"%{search_query}%"
        query = query.filter(
            or_(
                BlogPost.title.ilike(like_pattern),
                BlogPost.summary.ilike(like_pattern),
                BlogPost.content.ilike(like_pattern),
                BlogPost.tags.ilike(like_pattern),
            )
        )

    posts = query.order_by(_priority_order().desc(), BlogPost.created_at.desc()).all()

    return render_template(
        'blog.html',
        posts=posts,
        categories=BLOG_CATEGORIES,
        sections=BLOG_SECTIONS,
        get_category_info=get_category_info,
        current_section=section_filter,
        current_category=category_filter,
        search_query=search_query,
    )

@main_bp.route("/blog/<int:post_id>")
def blog_detail_by_id(post_id):
    post = BlogPost.query.filter_by(id=post_id, active=True).first_or_404()
    return blog_detail(post.slug)

@main_bp.route("/blog/<slug>")
def blog_detail(slug):
    post = BlogPost.query.filter_by(slug=slug, active=True).first_or_404()
    post.views = (post.views or 0) + 1
    db.session.commit()

    related_posts = (
        BlogPost.query
        .filter(BlogPost.active.is_(True), BlogPost.id != post.id)
        .order_by(_priority_order().desc(), BlogPost.created_at.desc())
        .limit(3)
        .all()
    )

    return render_template(
        'blog_detail.html',
        post=post,
        related_posts=related_posts,
        get_category_info=get_category_info,
        render_markdown=render_markdown,
    )

def register_blueprints(app):
    """Registra todos os blueprints globais da aplicação."""
    # Home / página principal
    app.register_blueprint(main_bp)
    
    # Admin
    app.register_blueprint(administrador_bp)

    # Gerenciamento Financeiro
    app.register_blueprint(gerenciamento_financeiro_bp, url_prefix="/gerenciamento-financeiro")

    # Conversor de imagens

    # Gerador De Qr Code
    app.register_blueprint(gerador_de_qr_code_bp, url_prefix="/gerador-de-qr-code")

    # YouTube Downloader
    app.register_blueprint(youtube_bp, url_prefix="/youtube-downloader")

    # Removedor De Fundo
    app.register_blueprint(removedor_de_fundo_bp, url_prefix="/removedor-de-fundo")
    app.register_blueprint(conversor_bp, url_prefix="/conversor-imagens")
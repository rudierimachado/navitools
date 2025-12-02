import os
import json
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

from administrador.routes import administrador_bp
from modulos.gerenciamento_financeiro.routes import gerenciamento_financeiro_bp
from modulos.ferramentas_web.youtub_downloader.routes import youtube_bp
from modulos.ferramentas_web.conversor_imagens.routes import conversor_bp
from modulos.ferramentas_web.gerador_de_qr_code.routes import gerador_de_qr_code_bp
from modulos.ferramentas_web.removedor_de_fundo.routes import removedor_de_fundo_bp

load_dotenv()

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
    content_data = load_content_data()
    posts = [post for post in content_data.get('posts', []) if post.get('active', False)]

    # Ordenar por prioridade e data
    def post_sort_key(post):
        priority_order = {'pinned': 3, 'featured': 2, 'normal': 1}
        priority = priority_order.get(post.get('priority', 'normal'), 1)
        date = post.get('date', '')
        return (priority, date)

    # Separar posts por seção
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
    destaque_posts = sorted(
        [p for p in posts if p.get('section') == 'destaque' or p.get('priority') in ['featured', 'pinned']],
        key=post_sort_key,
        reverse=True
    )

    # Decidir qual template usar baseado no dispositivo
    template_name = 'home_mobile.html' if getattr(g, 'is_mobile', False) else 'home.html'

    return render_template(template_name, 
                         novidades_posts=novidades_posts, 
                         dicas_posts=dicas_posts,
                         destaque_posts=destaque_posts,
                         get_category_info=get_category_info)

@main_bp.route("/ia-hub")
def ia_hub():
    content_data = load_content_data()
    return render_template('ia_hub.html', content_data=content_data)

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
    from flask import request
    content_data = load_content_data()
    posts = [post for post in content_data.get('posts', []) if post.get('active', False)]
    
    # Filtros
    section_filter = request.args.get('section')
    category_filter = request.args.get('category')
    search_query = request.args.get('search', '').strip()
    
    # Aplicar filtros
    if section_filter:
        posts = [p for p in posts if p.get('section') == section_filter]
    
    if category_filter:
        posts = [p for p in posts if p.get('category') == category_filter]
    
    if search_query:
        search_lower = search_query.lower()
        posts = [p for p in posts if 
                search_lower in p.get('title', '').lower() or 
                search_lower in p.get('summary', '').lower() or 
                search_lower in p.get('content', '').lower() or
                any(search_lower in tag.lower() for tag in p.get('tags', []))]
    
    # Ordenar por prioridade e data
    def post_sort_key(post):
        priority_order = {'pinned': 3, 'featured': 2, 'normal': 1}
        priority = priority_order.get(post.get('priority', 'normal'), 1)
        date = post.get('date', '')
        return (priority, date)
    
    posts = sorted(posts, key=post_sort_key, reverse=True)
    
    # Obter categorias únicas para filtros
    all_posts = content_data.get('posts', [])
    categories = list(set(p.get('category') for p in all_posts if p.get('category')))
    categories.sort()
    
    return render_template('blog_list.html', 
                         posts=posts, 
                         categories=categories,
                         get_category_info=get_category_info,
                         current_section=section_filter,
                         current_category=category_filter,
                         search_query=search_query)

@main_bp.route("/blog/<int:post_id>")
def blog_detail_by_id(post_id):
    content_data = load_content_data()
    posts = content_data.get('posts', [])
    post = next((p for p in posts if p.get('id') == post_id and p.get('active', False)), None)

    if not post:
        abort(404)
    
    # Incrementar visualizações
    post['views'] = post.get('views', 0) + 1
    
    # Salvar dados atualizados
    with open(os.path.join(os.path.dirname(__file__), 'administrador', 'content_data.json'), 'w', encoding='utf-8') as f:
        json.dump(content_data, f, indent=4, ensure_ascii=False)

    # Obter categorias para o menu
    all_posts = content_data.get('posts', [])
    categories = list(set(p.get('category') for p in all_posts if p.get('category')))
    categories.sort()
    
    return render_template('blog_detail.html', post=post, get_category_info=get_category_info, render_markdown=render_markdown, categories=categories)

@main_bp.route("/blog/<slug>")
def blog_detail_by_slug(slug):
    content_data = load_content_data()
    posts = content_data.get('posts', [])
    post = next((p for p in posts if p.get('slug') == slug and p.get('active', False)), None)

    if not post:
        # Tentar encontrar por ID se slug não funcionar (compatibilidade)
        try:
            post_id = int(slug)
            return blog_detail_by_id(post_id)
        except ValueError:
            abort(404)
    
    # Incrementar visualizações
    post['views'] = post.get('views', 0) + 1
    
    # Salvar dados atualizados
    with open(os.path.join(os.path.dirname(__file__), 'administrador', 'content_data.json'), 'w', encoding='utf-8') as f:
        json.dump(content_data, f, indent=4, ensure_ascii=False)

    # Obter categorias para o menu
    all_posts = content_data.get('posts', [])
    categories = list(set(p.get('category') for p in all_posts if p.get('category')))
    categories.sort()
    
    return render_template('blog_detail.html', post=post, get_category_info=get_category_info, render_markdown=render_markdown, categories=categories)

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
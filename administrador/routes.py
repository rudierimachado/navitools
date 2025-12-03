import base64
import json
import re

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

from .auth import login_required, check_credentials
from models import MenuItem, BlogPost, db

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

administrador_bp = Blueprint(
    'administrador',
    __name__,
    url_prefix='/administrador',
    template_folder='templates',
)

@administrador_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if check_credentials(username, password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            next_page = request.args.get('next')
            return redirect(next_page or url_for('administrador.dashboard'))
        else:
            return render_template('login.html', error='Usuário ou senha incorretos')

    return render_template('login.html')

@administrador_bp.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    flash('Logout realizado com sucesso', 'success')
    return redirect(url_for('main.index'))

@administrador_bp.route('/')
@administrador_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('administrador.html')


def _slugify(value: str) -> str:
    value = (value or "post").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip('-')
    return value or "post"


def _generate_unique_slug(source: str) -> str:
    base_slug = _slugify(source)
    slug = base_slug
    counter = 1

    while BlogPost.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


def _encode_cover_file(file_storage) -> str | None:
    if not file_storage or not file_storage.filename:
        return None

    data = file_storage.read()
    if not data:
        return None

    mime_type = file_storage.mimetype or 'image/png'
    encoded = base64.b64encode(data).decode('utf-8')
    return f"data:{mime_type};base64,{encoded}"


@administrador_bp.route('/blog', methods=['GET', 'POST'])
@login_required
def blog_manager():
    editing_post = None

    if request.method == 'POST':
        post_id = request.form.get('post_id')
        title = (request.form.get('title') or '').strip()
        summary = (request.form.get('summary') or '').strip()
        content = (request.form.get('content') or '').strip()
        cover_file = request.files.get('cover_file')

        if not title or not content:
            flash('Título e conteúdo são obrigatórios.', 'error')
        else:
            try:
                slug_input = (request.form.get('slug') or '').strip()
                slug = slug_input if slug_input else _generate_unique_slug(title)

                tags_raw = request.form.get('tags', '')
                tags_list = [tag.strip() for tag in tags_raw.split(',') if tag.strip()]
                new_cover_data = _encode_cover_file(cover_file)

                if post_id:
                    post = BlogPost.query.get_or_404(int(post_id))
                    if slug != post.slug and BlogPost.query.filter(BlogPost.slug == slug, BlogPost.id != post.id).first():
                        slug = _generate_unique_slug(slug)

                    post.title = title
                    post.subtitle = request.form.get('subtitle')
                    post.slug = slug
                    post.category = request.form.get('category') or None
                    post.section = request.form.get('section') or None
                    post.tags = json.dumps(tags_list, ensure_ascii=False)
                    if new_cover_data:
                        post.cover = new_cover_data
                    post.summary = summary
                    post.content = content
                    post.priority = request.form.get('priority') or 'normal'
                    post.active = request.form.get('active') == 'on'
                    post.reading_time = request.form.get('reading_time')
                    post.meta_description = request.form.get('meta_description')
                    message = 'Post atualizado com sucesso!'
                else:
                    if BlogPost.query.filter_by(slug=slug).first():
                        slug = _generate_unique_slug(slug)

                    new_post = BlogPost(
                        title=title,
                        subtitle=request.form.get('subtitle'),
                        slug=slug,
                        category=request.form.get('category') or None,
                        section=request.form.get('section') or None,
                        tags=json.dumps(tags_list, ensure_ascii=False),
                        cover=new_cover_data,
                        summary=summary,
                        content=content,
                        priority=request.form.get('priority') or 'normal',
                        active=request.form.get('active') == 'on',
                        reading_time=request.form.get('reading_time'),
                        meta_description=request.form.get('meta_description'),
                    )

                    db.session.add(new_post)
                    message = 'Post criado com sucesso!'

                db.session.commit()
                flash(message, 'success')
                return redirect(url_for('administrador.blog_manager'))
            except Exception as exc:
                db.session.rollback()
                flash(f'Erro ao salvar post: {exc}', 'error')

    posts = BlogPost.query.order_by(BlogPost.created_at.desc()).all()

    edit_id = request.args.get('edit', type=int)
    if edit_id:
        editing_post = BlogPost.query.get_or_404(edit_id)

    stats = {
        'total': len(posts),
        'published': len([p for p in posts if p.active]),
        'drafts': len([p for p in posts if not p.active]),
        'featured': len([p for p in posts if p.priority in ('featured', 'pinned')]),
    }

    return render_template(
        'blog_manager.html',
        posts=posts,
        stats=stats,
        categories=BLOG_CATEGORIES,
        sections=BLOG_SECTIONS,
        editing_post=editing_post,
    )


@administrador_bp.route('/blog/<int:post_id>/toggle', methods=['POST'])
@login_required
def toggle_blog_status(post_id):
    post = BlogPost.query.get_or_404(post_id)
    post.active = not post.active
    db.session.commit()
    flash('Status do post atualizado.', 'success')
    return redirect(url_for('administrador.blog_manager'))


@administrador_bp.route('/blog/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_blog_post(post_id):
    post = BlogPost.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash('Post removido com sucesso.', 'success')
    return redirect(url_for('administrador.blog_manager'))


@administrador_bp.route('/blog/<int:post_id>/edit')
@login_required
def edit_blog_post(post_id):
    """Convenience route so links like /administrador/blog/<id>/edit work."""
    BlogPost.query.get_or_404(post_id)
    return redirect(url_for('administrador.blog_manager', edit=post_id))

@administrador_bp.route('/menus')
@login_required
def menus():
    """Página de gerenciamento de menus"""
    menu_items = MenuItem.query.order_by(MenuItem.nivel.asc(), MenuItem.ordem.asc()).all()
    return render_template('menu_manager.html', menu_items=menu_items)

@administrador_bp.route('/menus/create', methods=['GET', 'POST'])
@login_required
def create_menu():
    """Criar novo item de menu"""
    if request.method == 'POST':
        try:
            nome = request.form.get('nome')
            nivel = int(request.form.get('nivel'))
            ordem = int(request.form.get('ordem', 0))
            icone = request.form.get('icone')
            url = request.form.get('url')
            parent_id = request.form.get('parent_id')
            ativo = request.form.get('ativo') == 'on'
            
            if parent_id and parent_id.strip():
                parent_id = int(parent_id)
            else:
                parent_id = None
            
            new_item = MenuItem(
                nome=nome,
                nivel=nivel,
                ordem=ordem,
                icone=icone,
                url=url,
                parent_id=parent_id,
                ativo=ativo
            )
            
            db.session.add(new_item)
            db.session.commit()
            
            flash('Item de menu criado com sucesso!', 'success')
            return redirect(url_for('administrador.menus'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar item: {str(e)}', 'error')
    
    # Para GET, buscar possíveis pais (todos os itens ativos)
    parent_options = MenuItem.query.filter_by(ativo=True).order_by(MenuItem.nivel.asc(), MenuItem.nome.asc()).all()
    return render_template('menu_form.html', parent_options=parent_options)

@administrador_bp.route('/menus/edit/<int:menu_id>', methods=['GET', 'POST'])
@login_required
def edit_menu(menu_id):
    """Editar item de menu"""
    menu_item = MenuItem.query.get_or_404(menu_id)
    
    if request.method == 'POST':
        try:
            menu_item.nome = request.form.get('nome')
            menu_item.nivel = int(request.form.get('nivel'))
            menu_item.ordem = int(request.form.get('ordem', 0))
            menu_item.icone = request.form.get('icone')
            menu_item.url = request.form.get('url')
            menu_item.ativo = request.form.get('ativo') == 'on'
            
            parent_id = request.form.get('parent_id')
            if parent_id and parent_id.strip():
                menu_item.parent_id = int(parent_id)
            else:
                menu_item.parent_id = None
            
            db.session.commit()
            
            flash('Item de menu atualizado com sucesso!', 'success')
            return redirect(url_for('administrador.menus'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar item: {str(e)}', 'error')
    
    # Para GET, buscar possíveis pais (todos os itens ativos, exceto o próprio item)
    parent_options = MenuItem.query.filter_by(ativo=True).filter(MenuItem.id != menu_id).order_by(MenuItem.nivel.asc(), MenuItem.nome.asc()).all()
    return render_template('menu_form.html', menu_item=menu_item, parent_options=parent_options)

@administrador_bp.route('/menus/delete/<int:menu_id>', methods=['POST'])
@login_required
def delete_menu(menu_id):
    """Deletar item de menu"""
    try:
        menu_item = MenuItem.query.get_or_404(menu_id)
        
        # Verificar se tem filhos
        children = MenuItem.query.filter_by(parent_id=menu_id).count()
        if children > 0:
            flash('Não é possível deletar um item que possui filhos. Delete os filhos primeiro.', 'error')
            return redirect(url_for('administrador.menus'))
        
        db.session.delete(menu_item)
        db.session.commit()
        
        flash('Item de menu deletado com sucesso!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar item: {str(e)}', 'error')
    
    return redirect(url_for('administrador.menus'))

@administrador_bp.route('/menus/reorder', methods=['POST'])
@login_required
def reorder_menus():
    """Reordenar itens de menu via AJAX"""
    try:
        data = request.get_json()
        
        for item_data in data:
            menu_item = MenuItem.query.get(item_data['id'])
            if menu_item:
                menu_item.ordem = item_data['ordem']
        
        db.session.commit()
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from .auth import login_required, check_credentials
from models import MenuItem, db

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

import os
import shutil
import json
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from .auth import login_required, check_credentials

BASE_PATH = os.path.dirname(os.path.dirname(__file__))
MODULOS_PATH = os.path.join(BASE_PATH, 'modulos')
FERRAMENTAS_CONTAINER = 'ferramentas_web'
FERRAMENTAS_PATH = os.path.join(MODULOS_PATH, FERRAMENTAS_CONTAINER)
LEGACY_FERRAMENTAS_PATH = os.path.join(BASE_PATH, 'ferramentas')

administrador_bp = Blueprint('administrador', __name__, url_prefix='/administrador', template_folder='templates')

@administrador_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
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

def load_module_config():
    """Carrega configurações dos módulos do arquivo JSON"""
    config_file = os.path.join(os.path.dirname(__file__), 'module_config.json')
    data = {}
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    # Normalizar chaves legadas
    if 'admin' in data and 'administrador' not in data:
        data['administrador'] = data.pop('admin')
    if 'ferramentas' in data and FERRAMENTAS_CONTAINER not in data:
        data[FERRAMENTAS_CONTAINER] = data.pop('ferramentas')

    for module in data.values():
        parent = module.get('parent_module')
        if parent == 'ferramentas':
            module['parent_module'] = FERRAMENTAS_CONTAINER
        elif parent == 'admin':
            module['parent_module'] = 'administrador'

    defaults = {
        'administrador': {"display_name": "Administrador", "icon": "shield-lock", "version": "1.0.0"},
        FERRAMENTAS_CONTAINER: {"display_name": "Ferramentas Web", "icon": "tools", "version": "1.0.0"}
    }
    for key, value in defaults.items():
        data.setdefault(key, value)

    return data

def save_module_config(config):
    """Salva configurações dos módulos no arquivo JSON"""
    config_file = os.path.join(os.path.dirname(__file__), 'module_config.json')
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def validate_module_name(new_name, current_name, module_type):
    """Valida se o novo nome de exibição pode ser usado (SEM verificar pastas)"""
    # Apenas verificar se nome de exibição já está em uso
    module_config = load_module_config()
    for module_name, config in module_config.items():
        if module_name != current_name and config.get('display_name', '').lower() == new_name.lower():
            return False, f'Já existe um módulo com o nome de exibição "{new_name}"'
    
    return True, ""

@administrador_bp.route('/')
@administrador_bp.route('/dashboard')
@login_required
def dashboard():
    # Carregar configurações personalizadas
    module_config = load_module_config()
    
    # Listar módulos do sistema com hierarquia correta
    modules = []
    
    # 1. Módulos Superiores (fixos do sistema)
    admin_config = module_config.get('admin', {'display_name': 'Admin', 'icon': 'shield-lock', 'version': '1.0.0'})
    modules.append({
        'name': 'admin',
        'display_name': admin_config['display_name'],
        'type': 'superior',
        'location': 'Menu Superior',
        'parent': None,
        'has_routes': True,
        'has_config': True,
        'has_templates': True,
        'status': 'Completo',
        'icon': admin_config['icon'],
        'version': admin_config.get('version', '1.0.0')
    })
    
    # 2. Módulos Laterais Principais
    ferramentas_config = module_config.get('ferramentas', {'display_name': 'Ferramentas', 'icon': 'tools', 'version': '1.0.0'})
    modules.append({
        'name': 'ferramentas',
        'display_name': ferramentas_config['display_name'],
        'type': 'lateral_main',
        'location': 'Menu Lateral',
        'parent': None,
        'has_routes': False,  # É um container
        'has_config': False,
        'has_templates': False,
        'status': 'Container',
        'icon': ferramentas_config['icon'],
        'version': ferramentas_config.get('version', '1.0.0')
    })
    
    # 3. Submódulos (dentro de ferramentas)
    ferramentas_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ferramentas')
    
    if os.path.exists(ferramentas_path):
        for item in os.listdir(ferramentas_path):
            item_path = os.path.join(ferramentas_path, item)
            if os.path.isdir(item_path) and not item.startswith('__'):
                # Verificar se tem os arquivos básicos
                has_routes = os.path.exists(os.path.join(item_path, 'routes.py'))
                has_config = os.path.exists(os.path.join(item_path, 'config.py'))
                has_templates = os.path.exists(os.path.join(item_path, 'templates'))
                
                # Usar configuração personalizada se existir
                item_config = module_config.get(item, {
                    'display_name': item.replace('_', ' ').title(),
                    'icon': 'image' if 'conversor' in item else 'gear',
                    'version': '1.0.0'
                })
                
                modules.append({
                    'name': item,
                    'display_name': item_config['display_name'],
                    'type': 'submódulo',
                    'location': 'Submódulo de Ferramentas',
                    'parent': 'ferramentas',
                    'has_routes': has_routes,
                    'has_config': has_config,
                    'has_templates': has_templates,
                    'status': 'Completo' if (has_routes and has_config) else 'Incompleto',
                    'icon': item_config['icon'],
                    'version': item_config.get('version', '1.0.0')
                })
    
    return render_template('administrador.html', modules=modules)

@administrador_bp.route('/create-module', methods=['POST'])
@login_required
def create_module():
    module_name = request.form['module_name'].strip().lower().replace(' ', '_')
    display_name = request.form['display_name'].strip()
    description = request.form['description'].strip()
    url_prefix = request.form['url_prefix'].strip()
    module_type = request.form['module_type']
    menu_location = request.form.get('menu_location', 'lateral')
    parent_module = request.form.get('parent_module', '')
    icon = request.form.get('icon', 'gear').strip()
    
    if not module_name or not display_name:
        flash('Nome do módulo e nome de exibição são obrigatórios', 'error')
        return redirect(url_for('administrador.dashboard'))
    
    if module_type == 'sub' and not parent_module:
        flash('Submódulos precisam de um módulo pai', 'error')
        return redirect(url_for('administrador.dashboard'))
    
    # Criar estrutura do módulo
    try:
        create_module_structure(
            module_name, display_name, description, url_prefix, 
            module_type, menu_location, parent_module, icon
        )
        
        module_type_text = 'Submódulo' if module_type == 'sub' else 'Módulo'
        flash(f'{module_type_text} "{display_name}" criado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao criar módulo: {str(e)}', 'error')
        return redirect(url_for('administrador.dashboard'))
    
    return redirect(url_for('administrador.dashboard'))

@administrador_bp.route('/edit-module', methods=['POST'])
@login_required
def edit_module():
    module_name = request.form['module_name'].strip()
    new_display_name = request.form['display_name'].strip()
    module_type = request.form['module_type']
    new_icon = request.form.get('icon', '').strip()
    new_version = request.form.get('version', '1.0.0').strip()
    
    if not new_display_name:
        flash('Nome de exibição é obrigatório', 'error')
        return redirect(url_for('administrador.dashboard'))
    
    # Validar se o novo nome pode ser usado
    is_valid, error_msg = validate_module_name(new_display_name, module_name, module_type)
    if not is_valid:
        flash(f'Erro: {error_msg}', 'error')
        return redirect(url_for('administrador.dashboard'))
    
    try:
        # Carregar configuração atual
        module_config = load_module_config()
        
        # Salvar configuração do módulo
        module_config = load_module_config()
        module_config[module_name] = {
            'display_name': new_display_name,
            'icon': new_icon,
            'version': new_version
        }
        save_module_config(module_config)
        
        # Atualizar global_blueprints.py
        add_to_global_blueprints(module_name, new_display_name.lower().replace(' ', '-'))
        
        # Adicionar ao menu lateral
        add_to_sidebar_menu(module_name, new_display_name.lower().replace(' ', '-'), new_display_name, new_icon)
        
        # Atualizar apenas nomes de exibição (SEM renomear pastas - muito perigoso!)
        if module_name == 'admin':
            update_admin_config(new_display_name, new_icon, new_version)
            flash(f'{new_display_name} v{new_version} - Nome de exibição atualizado!', 'success')
        elif module_name == 'ferramentas':
            update_ferramentas_config(new_display_name, new_icon, new_version)
            flash(f'Container "{new_display_name}" v{new_version} - Nome de exibição atualizado!', 'success')
        else:
            # Para submódulos, apenas atualizar nome de exibição (SEM renomear pasta)
            update_module_files(module_name, new_display_name, new_icon, new_version)
            flash(f'Módulo "{new_display_name}" v{new_version} - Nome de exibição atualizado!', 'success')
            
    except Exception as e:
        flash(f'Erro ao atualizar módulo: {str(e)}', 'error')
        return redirect(url_for('administrador.dashboard'))
    
    return redirect(url_for('administrador.dashboard'))

@administrador_bp.route('/delete-module', methods=['POST'])
@login_required
def delete_module():
    module_name = request.form['module_name'].strip()
    module_type = request.form['module_type'].strip()
    
    # Apenas submódulos podem ser excluídos (segurança)
    if module_type != 'submódulo':
        flash('Apenas submódulos podem ser excluídos por segurança', 'error')
        return redirect(url_for('administrador.dashboard'))
    
    try:
        # Carregar configuração atual
        module_config = load_module_config()
        
        # Verificar se módulo existe
        if module_name not in module_config:
            flash(f'Módulo "{module_name}" não encontrado', 'error')
            return redirect(url_for('administrador.dashboard'))
        
        display_name = module_config[module_name].get('display_name', module_name)
        
        # Excluir módulo completamente
        delete_module_completely(module_name)
        
        # Remover da configuração
        del module_config[module_name]
        save_module_config(module_config)
        
        flash(f'Módulo "{display_name}" excluído com sucesso!', 'success')
        
    except Exception as e:
        flash(f'Erro ao excluir módulo: {str(e)}', 'error')
    
    return redirect(url_for('administrador.dashboard'))

def delete_module_completely(module_name):
    """Exclui completamente um módulo: pasta, imports, referências"""
    base_path = os.path.dirname(os.path.dirname(__file__))
    module_path = os.path.join(base_path, 'ferramentas', module_name)
    
    import re
    
    # 1. Remover pasta física
    if os.path.exists(module_path):
        shutil.rmtree(module_path)
    
    # 2. Remover do global_blueprints.py
    global_blueprints = os.path.join(base_path, 'global_blueprints.py')
    if os.path.exists(global_blueprints):
        with open(global_blueprints, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Remover import
        import_pattern = f"from ferramentas\\.{module_name}\\.routes import {module_name}_bp"
        content = re.sub(import_pattern + r'\n?', '', content)
        
        # Remover registro do blueprint
        register_pattern = f"\\s*app\\.register_blueprint\\({module_name}_bp[^\\n]*\\n?"
        content = re.sub(register_pattern, '', content)
        
        # Remover comentário se existir
        comment_pattern = f"\\s*# {module_name.replace('_', ' ').title()}\\n?"
        content = re.sub(comment_pattern, '', content)
        
        with open(global_blueprints, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 3. Remover do base.html (menu lateral)
    base_template = os.path.join(base_path, 'template_global', 'base.html')
    if os.path.exists(base_template):
        with open(base_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Remover link do submenu
        url_prefix = module_name.replace('_', '-')
        link_pattern = f'\\s*<li class="nav-item">\\s*<a class="nav-link submenu-link" href="/{url_prefix}">.*?</a>\\s*</li>'
        content = re.sub(link_pattern, '', content, flags=re.DOTALL)
        
        with open(base_template, 'w', encoding='utf-8') as f:
            f.write(content)

def update_module_files(module_name, new_display_name, new_icon, new_version='1.0.0'):
    """Atualiza arquivos do módulo com novo nome e ícone"""
    base_path = os.path.dirname(os.path.dirname(__file__))
    module_path = os.path.join(base_path, 'ferramentas', module_name)
    
    if not os.path.exists(module_path):
        raise Exception(f'Módulo {module_name} não encontrado')
    
    # 1. Atualizar routes.py
    routes_file = os.path.join(module_path, 'routes.py')
    if os.path.exists(routes_file):
        with open(routes_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar título na rota principal
        content = content.replace(
            f"return render_template('{module_name}.html')",
            f"return render_template('{module_name}.html')"
        )
        
        with open(routes_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 2. Atualizar template HTML
    template_file = os.path.join(module_path, 'templates', f'{module_name}.html')
    if os.path.exists(template_file):
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar título e ícone no template
        old_title_pattern = r'<h1[^>]*>.*?</h1>'
        new_title = f'<h1 class="mb-3" style="color: var(--primary-color);"><i class="bi bi-{new_icon}"></i> {new_display_name}</h1>'
        
        import re
        content = re.sub(old_title_pattern, new_title, content, flags=re.DOTALL)
        
        # Atualizar block title
        content = re.sub(
            r'{%\s*block\s+title\s*%}.*?{%\s*endblock\s*%}',
            f'{{% block title %}}{new_display_name} - NEXUSRDR{{% endblock %}}',
            content
        )
        
        with open(template_file, 'w', encoding='utf-8') as f:
            f.write(content)

def update_admin_config(new_display_name, new_icon, new_version='1.0.0'):
    """Atualiza configurações do módulo Administrador"""
    base_path = os.path.dirname(os.path.dirname(__file__))
    import re
    
    # 1. Atualizar template admin.html
    admin_template = os.path.join(base_path, 'admin', 'templates', 'admin.html')
    if os.path.exists(admin_template):
        with open(admin_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar título do painel administrativo
        content = re.sub(
            r'<h1[^>]*>.*?</h1>',
            f'<h1 class="mb-3" style="color: var(--primary-color);"><i class="bi bi-{new_icon}"></i> {new_display_name}</h1>',
            content,
            flags=re.DOTALL
        )
        
        # Atualizar block title
        content = re.sub(
            r'{%\s*block\s+title\s*%}.*?{%\s*endblock\s*%}',
            f'{{% block title %}}{new_display_name} - NEXUSRDR{{% endblock %}}',
            content
        )
        
        with open(admin_template, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 2. Atualizar base.html (menu superior)
    base_template = os.path.join(base_path, 'template_global', 'base.html')
    if os.path.exists(base_template):
        with open(base_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar link do admin no menu superior
        content = re.sub(
            r'<a class="nav-link text-white" href="/admin">\s*<i class="bi bi-[^"]*"></i>\s*[^<]*</a>',
            f'<a class="nav-link text-white" href="/admin"><i class="bi bi-{new_icon}"></i> {new_display_name}</a>',
            content
        )
        
        with open(base_template, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 3. Atualizar routes.py do admin (comentários e referências)
    admin_routes = os.path.join(base_path, 'admin', 'routes.py')
    if os.path.exists(admin_routes):
        with open(admin_routes, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar comentários que mencionam "Admin"
        content = re.sub(
            r'"""[^"]*Admin[^"]*"""',
            f'"""Atualiza configurações do módulo {new_display_name}"""',
            content
        )
        
        # Atualizar blueprint name se necessário
        content = re.sub(
            r"Blueprint\('admin'",
            f"Blueprint('administrador'",  # Manter 'admin' técnico
            content
        )
        
        with open(admin_routes, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 4. Atualizar global_blueprints.py
    global_blueprints = os.path.join(base_path, 'global_blueprints.py')
    if os.path.exists(global_blueprints):
        with open(global_blueprints, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar comentários sobre admin
        content = re.sub(
            r'# .*[Aa]dmin.*',
            f'# {new_display_name}',
            content
        )
        
        with open(global_blueprints, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 5. Atualizar login.html
    login_template = os.path.join(base_path, 'admin', 'templates', 'login.html')
    if os.path.exists(login_template):
        with open(login_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar título da página de login
        content = re.sub(
            r'{%\s*block\s+title\s*%}.*?{%\s*endblock\s*%}',
            f'{{% block title %}}Login - {new_display_name}{{% endblock %}}',
            content
        )
        
        # Atualizar cabeçalho do login
        content = re.sub(
            r'<h2[^>]*>.*?</h2>',
            f'<h2 class="text-center mb-4"><i class="bi bi-{new_icon}"></i> {new_display_name}</h2>',
            content,
            flags=re.DOTALL
        )
        
        with open(login_template, 'w', encoding='utf-8') as f:
            f.write(content)

def rename_admin_completely(old_name, new_name, new_display_name, new_icon, new_version):
    """Renomeia completamente a pasta admin: pasta, imports, URLs"""
    base_path = os.path.dirname(os.path.dirname(__file__))
    old_path = os.path.join(base_path, old_name)
    new_path = os.path.join(base_path, new_name)
    
    import re
    
    # 1. Verificar se nova pasta já existe
    if os.path.exists(new_path):
        raise Exception(f'Pasta "{new_name}" já existe!')
    
    # 2. Renomear pasta física
    if os.path.exists(old_path):
        shutil.move(old_path, new_path)
    
    # 3. Atualizar run.py
    run_file = os.path.join(base_path, 'run.py')
    if os.path.exists(run_file):
        with open(run_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar imports
        content = re.sub(
            f'from {old_name}',
            f'from {new_name}',
            content
        )
        
        with open(run_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 4. Atualizar global_blueprints.py
    global_blueprints = os.path.join(base_path, 'global_blueprints.py')
    if os.path.exists(global_blueprints):
        with open(global_blueprints, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar imports
        content = re.sub(
            f'from {old_name}',
            f'from {new_name}',
            content
        )
        
        # Atualizar blueprint registration
        content = re.sub(
            f'{old_name}_bp',
            f'{new_name}_bp',
            content
        )
        
        with open(global_blueprints, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 5. Atualizar routes.py interno
    routes_file = os.path.join(new_path, 'routes.py')
    if os.path.exists(routes_file):
        with open(routes_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar blueprint name
        content = re.sub(
            f"Blueprint\\('{old_name}'",
            f"Blueprint('{new_name}'",
            content
        )
        
        # Atualizar URL prefix
        content = re.sub(
            f"url_prefix='/{old_name}'",
            f"url_prefix='/{new_name}'",
            content
        )
        
        with open(routes_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 6. Atualizar base.html (URLs)
    base_template = os.path.join(base_path, 'template_global', 'base.html')
    if os.path.exists(base_template):
        with open(base_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar URLs
        content = re.sub(
            f'href="/{old_name}"',
            f'href="/{new_name}"',
            content
        )
        
        # Atualizar texto do link
        content = re.sub(
            f'<i class="bi bi-[^"]*"></i> [^<]*</a>',
            f'<i class="bi bi-{new_icon}"></i> {new_display_name}</a>',
            content
        )
        
        with open(base_template, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 7. Atualizar templates internos
    for template_name in ['admin.html', 'login.html']:
        template_file = os.path.join(new_path, 'templates', template_name)
        if os.path.exists(template_file):
            with open(template_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Atualizar títulos e ícones
            content = re.sub(
                r'<h[1-6][^>]*>.*?</h[1-6]>',
                f'<h1 class="mb-3" style="color: var(--primary-color);"><i class="bi bi-{new_icon}"></i> {new_display_name}</h1>',
                content,
                flags=re.DOTALL
            )
            
            # Atualizar block title
            content = re.sub(
                r'{%\s*block\s+title\s*%}.*?{%\s*endblock\s*%}',
                f'{{% block title %}}{new_display_name} - NEXUSRDR{{% endblock %}}',
                content
            )
            
            with open(template_file, 'w', encoding='utf-8') as f:
                f.write(content)

def update_ferramentas_config(new_display_name, new_icon, new_version='1.0.0'):
    """Atualiza configurações do container Ferramentas"""
    base_path = os.path.dirname(os.path.dirname(__file__))
    import re
    
    # 1. Atualizar template base.html
    base_template = os.path.join(base_path, 'template_global', 'base.html')
    if os.path.exists(base_template):
        with open(base_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar nome e ícone no menu lateral
        content = re.sub(
            r'<i class="bi bi-[^"]*"></i>\s*[^<]*(?=<i class="bi bi-chevron-down)',
            f'<i class="bi bi-{new_icon}"></i> {new_display_name}',
            content
        )
        
        with open(base_template, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 2. Atualizar global_blueprints.py
    global_blueprints = os.path.join(base_path, 'global_blueprints.py')
    if os.path.exists(global_blueprints):
        with open(global_blueprints, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar imports e referências
        content = re.sub(
            r'from ferramentas\.',
            'from ferramentas.',
            content
        )
        
        with open(global_blueprints, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 3. Atualizar run.py se houver referências
    run_file = os.path.join(base_path, 'run.py')
    if os.path.exists(run_file):
        with open(run_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar comentários que mencionam "Ferramentas"
        content = re.sub(
            r'# .*[Ff]erramentas.*',
            f'# {new_display_name}',
            content
        )
        
        with open(run_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 4. Atualizar home.html se houver referências
    home_template = os.path.join(base_path, 'template_global', 'home.html')
    if os.path.exists(home_template):
        with open(home_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar referências visuais a "Ferramentas"
        content = re.sub(
            r'[Ff]erramentas(?!\w)',
            new_display_name,
            content
        )
        
        with open(home_template, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 5. Atualizar admin.html se houver referências
    admin_template = os.path.join(base_path, 'admin', 'templates', 'admin.html')
    if os.path.exists(admin_template):
        with open(admin_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualizar referências no dropdown de módulos pai
        content = re.sub(
            r'<option value="ferramentas">[^<]*</option>',
            f'<option value="ferramentas">{new_display_name}</option>',
            content
        )
        
        with open(admin_template, 'w', encoding='utf-8') as f:
            f.write(content)

def create_module_structure(module_name, display_name, description, url_prefix, module_type='main', menu_location='lateral', parent_module='', icon='gear'):
    """Cria estrutura básica de módulo com template 'Em Desenvolvimento'"""
    base_path = os.path.dirname(os.path.dirname(__file__))
    module_path = os.path.join(base_path, 'ferramentas', module_name)
    
    # Criar diretórios
    os.makedirs(module_path, exist_ok=True)
    os.makedirs(os.path.join(module_path, 'templates'), exist_ok=True)
    
    # Criar __init__.py simples
    init_content = f'# Módulo {display_name} - Em Desenvolvimento\n'
    with open(os.path.join(module_path, '__init__.py'), 'w', encoding='utf-8') as f:
        f.write(init_content)
    
    # Criar config.py básico
    config_content = f'''# Configuração do módulo {display_name}

class Config:
    """Configurações básicas do módulo"""
    # Adicione configurações específicas aqui quando necessário
    pass

# Adicione funções específicas do módulo aqui
'''
    
    with open(os.path.join(module_path, 'config.py'), 'w', encoding='utf-8') as f:
        f.write(config_content)
    
    # Criar routes.py simples
    routes_content = f'''from flask import Blueprint, render_template

{module_name}_bp = Blueprint('{module_name}', __name__, url_prefix='/{url_prefix}', template_folder='templates')

@{module_name}_bp.route('/')
def index():
    """Página principal do {display_name}"""
    return render_template('{module_name}.html')
'''
    
    with open(os.path.join(module_path, 'routes.py'), 'w', encoding='utf-8') as f:
        f.write(routes_content)
    
    # Criar template HTML com mensagem "Em Desenvolvimento"
    template_content = f'''{{% extends 'base.html' %}}

{{% block title %}}{display_name} - NEXUSRDR{{% endblock %}}

{{% block module_name %}}{display_name}{{% endblock %}}
{{% block module_version %}}1.0.0{{% endblock %}}

{{% block content %}}
<div class="container-fluid">
    <div class="row mb-4">
        <div class="col-12">
            <h1 class="mb-3" style="color: var(--primary-color);">
                <i class="bi bi-{icon}"></i> {display_name}
            </h1>
            <p class="text-muted">{description}</p>
        </div>
    </div>

    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card tool-card text-center">
                <div class="card-body py-5">
                    <div class="mb-4">
                        <i class="bi bi-tools display-1 text-warning"></i>
                    </div>
                    <h3 class="text-warning mb-3">🚧 Em Desenvolvimento</h3>
                    <p class="lead text-muted mb-4">
                        Este módulo está sendo desenvolvido e estará disponível em breve.
                    </p>
                    <div class="alert alert-info">
                        <i class="bi bi-info-circle"></i>
                        <strong>Módulo:</strong> {display_name}<br>
                        <strong>Status:</strong> Em construção<br>
                        <strong>Previsão:</strong> Próximas atualizações
                    </div>
                    <a href="/" class="btn btn-primary">
                        <i class="bi bi-house-door"></i> Voltar ao Início
                    </a>
                </div>
            </div>
        </div>
    </div>
</div>
{{% endblock %}}
'''
    
    with open(os.path.join(module_path, 'templates', f'{module_name}.html'), 'w', encoding='utf-8') as f:
        f.write(template_content)
    
    # Salvar configuração do módulo
    module_config = load_module_config()
    module_config[module_name] = {
        'display_name': display_name,
        'description': description,
        'icon': icon,
        'location': menu_location,
        'parent_module': parent_module if module_type == 'sub' else None,
        'version': '1.0.0'  # Versão padrão para novos módulos
    }
    save_module_config(module_config)
    
    # Atualizar global_blueprints.py
    add_to_global_blueprints(module_name, url_prefix)
    
    # Adicionar ao menu lateral
    add_to_sidebar_menu(module_name, url_prefix, display_name, icon)

def add_to_global_blueprints(module_name, url_prefix):
    """Adiciona módulo ao global_blueprints.py"""
    base_path = os.path.dirname(os.path.dirname(__file__))
    global_blueprints_path = os.path.join(base_path, 'global_blueprints.py')
    
    if os.path.exists(global_blueprints_path):
        with open(global_blueprints_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Adicionar import se não existir
        import_line = f"from ferramentas.{module_name}.routes import {module_name}_bp"
        if import_line not in content:
            lines = content.split('\n')
            # Adicionar após o último import de ferramentas
            insert_index = 2  # Após conversor_imagens
            lines.insert(insert_index, import_line)
            content = '\n'.join(lines)
        
        # Adicionar registro se não existir
        register_line = f"    app.register_blueprint({module_name}_bp, url_prefix=\"/{url_prefix}\")"
        if register_line not in content:
            lines = content.split('\n')
            # Adicionar antes da linha vazia final
            lines.insert(-1, "")
            lines.insert(-1, f"    # {module_name.replace('_', ' ').title()}")
            lines.insert(-1, register_line)
            content = '\n'.join(lines)
        
        with open(global_blueprints_path, 'w', encoding='utf-8') as f:
            f.write(content)

def add_to_sidebar_menu(module_name, url_prefix, display_name, icon):
    """Mantido por compatibilidade; menu agora é gerado dinamicamente."""
    return

# ==================== GERENCIAMENTO DE CONTEÚDO ====================

def load_content_data():
    """Carrega dados de conteúdo do arquivo JSON"""
    content_file = os.path.join(os.path.dirname(__file__), 'content_data.json')
    try:
        with open(content_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "posts": []
        }

def save_content_data(data):
    """Salva dados de conteúdo no arquivo JSON"""
    content_file = os.path.join(os.path.dirname(__file__), 'content_data.json')
    with open(content_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

@administrador_bp.route('/content')
@login_required
def content_manager():
    """Página principal de gerenciamento de conteúdo"""
    content_data = load_content_data()
    posts = sorted(content_data.get('posts', []), key=lambda p: p.get('date', ''), reverse=True)
    return render_template('content_manager.html', posts=posts)

@administrador_bp.route('/content/post/add', methods=['GET', 'POST'])
@login_required
def add_post():
    """Adicionar novo post"""
    if request.method == 'POST':
        content_data = load_content_data()
        posts = content_data.get('posts', [])

        new_id = max([post.get('id', 0) for post in posts], default=0) + 1
        
        # Gerar slug automaticamente se não fornecido
        title = request.form['title']
        slug = request.form.get('slug', '').strip()
        if not slug:
            slug = generate_slug(title)
        
        # Gerar meta description se não fornecida
        meta_description = request.form.get('meta_description', '').strip()
        if not meta_description:
            summary = request.form.get('summary', '')
            meta_description = summary[:160] if summary else title[:160]
        
        # Processar tags
        tags = request.form.get('tags', '').strip()
        tags_list = [tag.strip() for tag in tags.split(',') if tag.strip()] if tags else []
        
        # Determinar status de publicação
        status = request.form.get('status', 'publish')
        is_active = status == 'publish'

        new_post = {
            'id': new_id,
            'title': title,
            'subtitle': request.form.get('subtitle', ''),
            'category': request.form.get('category', ''),
            'tags': tags_list,
            'section': request.form.get('section', 'novidades'),
            'priority': request.form.get('priority', 'normal'),
            'date': request.form['date'],
            'reading_time': request.form.get('reading_time', ''),
            'summary': request.form.get('summary', ''),
            'content': request.form.get('content', ''),
            'cover': request.form.get('cover', ''),
            'cta_text': request.form.get('cta_text', ''),
            'cta_link': request.form.get('cta_link', ''),
            'slug': slug,
            'meta_description': meta_description,
            'active': is_active,
            'views': 0,  # Contador de visualizações
            'created_at': request.form['date'],
            'updated_at': request.form['date']
        }

        posts.append(new_post)
        content_data['posts'] = posts
        save_content_data(content_data)

        status_message = 'Post publicado com sucesso!' if is_active else 'Rascunho salvo com sucesso!'
        flash(status_message, 'success')
        return redirect(url_for('administrador.content_manager'))

    return render_template('add_post.html')

def generate_slug(title):
    """Gera slug amigável a partir do título"""
    import re
    import unicodedata
    
    # Normalizar caracteres especiais
    slug = unicodedata.normalize('NFKD', title)
    slug = slug.encode('ascii', 'ignore').decode('ascii')
    
    # Converter para minúsculas e substituir espaços
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', slug.lower())
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    
    return slug.strip('-')

@administrador_bp.route('/content/post/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    """Editar post existente"""
    content_data = load_content_data()
    posts = content_data.get('posts', [])
    post = next((p for p in posts if p['id'] == post_id), None)

    if not post:
        flash('Post não encontrado!', 'error')
        return redirect(url_for('administrador.content_manager'))

    if request.method == 'POST':
        # Gerar slug automaticamente se não fornecido
        title = request.form['title']
        slug = request.form.get('slug', '').strip()
        if not slug:
            slug = generate_slug(title)
        
        # Gerar meta description se não fornecida
        meta_description = request.form.get('meta_description', '').strip()
        if not meta_description:
            summary = request.form.get('summary', '')
            meta_description = summary[:160] if summary else title[:160]
        
        # Processar tags
        tags = request.form.get('tags', '').strip()
        tags_list = [tag.strip() for tag in tags.split(',') if tag.strip()] if tags else []
        
        # Determinar status de publicação
        status = request.form.get('status', 'publish')
        is_active = status == 'publish'

        post.update({
            'title': title,
            'subtitle': request.form.get('subtitle', ''),
            'category': request.form.get('category', ''),
            'tags': tags_list,
            'section': request.form.get('section', post.get('section', 'novidades')),
            'priority': request.form.get('priority', 'normal'),
            'date': request.form['date'],
            'reading_time': request.form.get('reading_time', ''),
            'summary': request.form.get('summary', ''),
            'content': request.form.get('content', ''),
            'cover': request.form.get('cover', ''),
            'cta_text': request.form.get('cta_text', ''),
            'cta_link': request.form.get('cta_link', ''),
            'slug': slug,
            'meta_description': meta_description,
            'active': is_active,
            'updated_at': request.form['date']
        })

        save_content_data(content_data)
        status_message = 'Post atualizado com sucesso!' if is_active else 'Rascunho atualizado com sucesso!'
        flash(status_message, 'success')
        return redirect(url_for('administrador.content_manager'))

    return render_template('edit_post.html', post=post)

@administrador_bp.route('/content/post/delete/<int:post_id>')
@login_required
def delete_post(post_id):
    """Excluir post"""
    content_data = load_content_data()
    posts = content_data.get('posts', [])
    content_data['posts'] = [p for p in posts if p['id'] != post_id]
    save_content_data(content_data)

    flash('Post removido.', 'success')
    return redirect(url_for('administrador.content_manager'))

import json
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / 'administrador' / 'module_config.json'
FERRAMENTAS_DIR = BASE_DIR / 'ferramentas'


def load_module_config() -> dict:
    """Load module configuration saved by the admin panel."""
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open('r', encoding='utf-8') as config_file:
                return json.load(config_file)
        except json.JSONDecodeError:
            return {}
    return {}


def _slugify(value: str) -> str:
    return value.strip().replace(' ', '-').replace('_', '-').lower()


def _default_location(module_key: str) -> str:
    if module_key in {'administrador', 'admin'}:
        return 'superior'
    if module_key == 'ferramentas':
        return 'lateral'
    return 'lateral'


def _normalize_module(module_key: str, module_info: dict, *, parent: str | None = None,
                      location: str | None = None, icon_default: str = 'gear') -> dict:
    display_name = module_info.get('display_name', module_key.replace('_', ' ').title())
    icon = module_info.get('icon', icon_default)
    version = module_info.get('version', '1.0.0')
    raw_prefix = module_info.get('url_prefix') or module_info.get('url') or _slugify(module_key)
    url_prefix = raw_prefix.strip('/')
    normalized_location = module_info.get('location', location or _default_location(module_key))
    normalized_parent = module_info.get('parent_module', parent)

    return {
        'key': module_key,
        'display_name': display_name,
        'icon': icon,
        'version': version,
        'url_prefix': url_prefix,
        'url': f"/{url_prefix}" if url_prefix else '/',
        'location': normalized_location,
        'parent': normalized_parent
    }


def build_sidebar_menu() -> dict:
    """Build metadata for both top navigation and sidebar groups."""
    module_config = load_module_config()
    modules: dict[str, dict] = {}

    # Primeiro, carregar todos os módulos conhecidos na configuração
    for module_key, module_info in module_config.items():
        modules[module_key] = _normalize_module(module_key, module_info)

    # Garantir entradas padrão para administrador e container de ferramentas
    for required in ('administrador', 'ferramentas'):
        if required not in modules:
            modules[required] = _normalize_module(required, module_config.get(required, {}))

    # Detectar submódulos existentes fisicamente em ferramentas/
    if FERRAMENTAS_DIR.exists():
        for entry in sorted(FERRAMENTAS_DIR.iterdir()):
            if not entry.is_dir() or entry.name.startswith('__'):
                continue

            module_key = entry.name
            module_info = module_config.get(module_key, {})

            if module_key not in modules:
                modules[module_key] = _normalize_module(
                    module_key,
                    module_info,
                    parent='ferramentas',
                    location='sub'
                )
            else:
                modules[module_key]['parent'] = (
                    modules[module_key].get('parent')
                    or module_info.get('parent_module')
                    or 'ferramentas'
                )
                modules[module_key]['location'] = modules[module_key].get('location') or 'sub'

    # Construir hierarquia de filhos
    children_map: defaultdict[str, list] = defaultdict(list)
    for module in modules.values():
        parent = module.get('parent')
        if parent:
            children_map[parent].append(module)

    def sort_key(item: dict) -> str:
        return item['display_name'].lower()

    top_menu = []
    side_groups = []

    for module in modules.values():
        if module.get('parent'):
            continue

        location = module.get('location') or _default_location(module['key'])
        group_children = sorted(children_map.get(module['key'], []), key=sort_key)

        if location == 'superior':
            top_menu.append(module)
        else:
            side_groups.append({
                'key': module['key'],
                'display_name': module['display_name'],
                'icon': module['icon'],
                'url': module['url'],
                'children': group_children
            })

    return {
        'top_menu': sorted(top_menu, key=sort_key),
        'side_groups': sorted(side_groups, key=sort_key)
    }

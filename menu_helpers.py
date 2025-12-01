import json
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / 'administrador' / 'module_config.json'
MODULOS_DIR = BASE_DIR / 'modulos'


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
    if module_key in {'ferramentas_web', 'youtub_downloader'}:
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
    """Build metadata for both top navigation and sidebar groups based on modulos/ structure."""
    module_config = load_module_config()
    modules: dict[str, dict] = {}

    # Garantir entrada para administrador
    if 'administrador' not in modules:
        modules['administrador'] = _normalize_module('administrador', {
            'display_name': 'Administrador',
            'icon': 'shield-lock',
            'url_prefix': 'administrador',
            'location': 'superior'
        })

    special_main_defaults = {
        'ferramentas_web': {
            'display_name': 'Ferramentas Web',
            'icon': 'tools',
            'url_prefix': '#',
            'location': 'lateral'
        },
        'youtub_downloader': {
            'display_name': 'YouTube Downloader',
            'icon': 'youtube',
            'url_prefix': 'youtube-downloader',
            'location': 'lateral'
        },
        'gerenciamento_financeiro': {
            'display_name': 'Gestão Financeira Familiar',
            'icon': 'cash-coin',
            'url_prefix': 'gerenciamento-financeiro/login',
            'location': 'lateral'
        }
    }

    # Escanear pasta modulos/ para detectar módulos principais e filhos
    if MODULOS_DIR.exists():
        for main_dir in sorted(MODULOS_DIR.iterdir()):
            if not main_dir.is_dir() or main_dir.name.startswith('__'):
                continue

            main_key = main_dir.name
            default_info = special_main_defaults.get(main_key, {
                'display_name': main_key.replace('_', ' ').title(),
                'icon': 'gear',
                'url_prefix': main_key.replace('_', '-'),
                'location': 'lateral'
            })
            merged_info = {**default_info, **module_config.get(main_key, {})}
            modules[main_key] = _normalize_module(main_key, merged_info)

            # submódulos (apenas diretórios com routes.py)
            for sub_dir in sorted(main_dir.iterdir()):
                if not sub_dir.is_dir() or sub_dir.name.startswith('__'):
                    continue

                routes_file = sub_dir / 'routes.py'
                if not routes_file.exists():
                    continue

                sub_key = sub_dir.name
                if sub_key == 'gerador_de_qr_code':
                    sub_defaults = {
                        'display_name': 'Gerador de QR Code',
                        'icon': 'qr-code',
                        'url_prefix': 'gerador-de-qr-code'
                    }
                elif sub_key == 'conversor_imagens':
                    sub_defaults = {
                        'display_name': 'Conversor de Imagens',
                        'icon': 'image',
                        'url_prefix': 'conversor-imagens'
                    }
                else:
                    sub_defaults = {
                        'display_name': sub_key.replace('_', ' ').title(),
                        'icon': 'gear',
                        'url_prefix': sub_key.replace('_', '-')
                    }

                sub_overrides = module_config.get(f"{main_key}.{sub_key}", {})
                sub_info = {**sub_defaults, **sub_overrides}
                modules[sub_key] = _normalize_module(
                    sub_key,
                    sub_info,
                    parent=main_key,
                    location='sub'
                )

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
            # Se não tem filhos, é um link direto
            # Se tem filhos, é um grupo expansível
            side_groups.append({
                'key': module['key'],
                'display_name': module['display_name'],
                'icon': module['icon'],
                'url': module['url'],
                'children': group_children,
                'is_direct_link': len(group_children) == 0  # Novo campo para identificar links diretos
            })

    return {
        'top_menu': sorted(top_menu, key=sort_key),
        'side_groups': sorted(side_groups, key=sort_key)
    }

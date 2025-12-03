from collections import defaultdict

from models import MenuItem

DEFAULT_SIDE_GROUPS = [
    {
        "key": "default_tools",
        "display_name": "Ferramentas Web",
        "icon": "grid-3x3-gap",
        "url": "/",
        "is_direct_link": False,
        "children": [
            {
                "key": "default_qr",
                "display_name": "Gerador de QR Code",
                "icon": "qr-code",
                "url": "/gerador-de-qr-code",
            },
            {
                "key": "default_converter",
                "display_name": "Conversor de Imagens",
                "icon": "images",
                "url": "/conversor-imagens",
            },
            {
                "key": "default_remove_bg",
                "display_name": "Removedor de Fundo",
                "icon": "eraser",
                "url": "/removedor-de-fundo",
            },
            {
                "key": "default_youtube",
                "display_name": "YouTube Downloader",
                "icon": "play-btn",
                "url": "/youtube-downloader",
            },
        ],
    },
    {
        "key": "default_extra",
        "display_name": "Outros Recursos",
        "icon": "stars",
        "url": "/",
        "is_direct_link": False,
        "children": [
            {
                "key": "default_blog",
                "display_name": "Blog",
                "icon": "journal-richtext",
                "url": "/blog",
            },
            {
                "key": "default_contact",
                "display_name": "Contato",
                "icon": "envelope",
                "url": "/contact",
            },
        ],
    },
]


def build_sidebar_menu() -> dict:
    """Monta o menu usando a tabela menu_items.

    - nivel 1: grupos principais (ex.: Ferramentas Web, Gestão Financeira)
    - nivel 2: itens dentro de um grupo (ex.: Conversor, YouTube Downloader)

    Mantém o formato esperado por base.html:
      {
        'top_menu': [...],
        'side_groups': [...]
      }
    """

    # Buscar todos os itens ativos ordenados
    items: list[MenuItem] = (
        MenuItem.query
        .filter(MenuItem.ativo.is_(True))
        .order_by(MenuItem.nivel.asc(), MenuItem.ordem.asc(), MenuItem.id.asc())
        .all()
    )

    # Por enquanto: tudo é menu lateral (nenhum top_menu dinâmico)
    # Se um dia quiser nível 0 para top_menu, dá pra separar aqui.

    # Construir mapa de filhos por parent_id
    children_map: dict[int | None, list[MenuItem]] = {}
    for it in items:
        children_map.setdefault(it.parent_id, []).append(it)

    side_groups: list[dict] = []

    # Criar grupos a partir dos itens de nível 1 (parent_id is None)
    raiz_items = children_map.get(None, [])
    for g in raiz_items:
        grupo = {
            'key': f"menu_{g.id}",
            'display_name': g.nome,
            'icon': g.icone or 'grid-3x3-gap',
            'url': g.url,
            'children': [],
            'is_direct_link': False,
        }

        # Filhos diretos deste grupo (nivel 2)
        filhos = children_map.get(g.id, [])
        for item in filhos:
            child = {
                'key': f"menu_{item.id}",
                'display_name': item.nome,
                'icon': item.icone or 'gear',
                'url': item.url,
            }
            grupo['children'].append(child)

        # Ordenar filhos por nome
        grupo['children'] = sorted(grupo['children'], key=lambda c: c['display_name'].lower())
        side_groups.append(grupo)

    if not side_groups:
        side_groups = DEFAULT_SIDE_GROUPS

    return {
        'top_menu': [],
        'side_groups': side_groups,
    }

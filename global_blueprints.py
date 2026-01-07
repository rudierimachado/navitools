import os
import smtplib
import ssl
from email.message import EmailMessage

from dotenv import load_dotenv
from flask import (
    Blueprint,
    current_app,
    render_template,
    abort,
    send_from_directory,
    g,
    request,
    Response,
    flash,
    redirect,
    url_for,
)
from sqlalchemy import case, or_
from datetime import datetime

from administrador.routes import administrador_bp
from extensions import db
from modulos.App_financeiro.routes import gerenciamento_financeiro_bp
from modulos.App_financeiro.api import api_financeiro_bp
from modulos.ferramentas_web.youtub_downloader.routes import youtube_bp
from modulos.ferramentas_web.conversor_imagens.routes import conversor_bp
from modulos.ferramentas_web.gerador_de_qr_code.routes import gerador_de_qr_code_bp
from modulos.ferramentas_web.removedor_de_fundo.routes import removedor_de_fundo_bp
from modulos.ferramentas_web.nexuspdf.routes import nexuspdf_bp
from modulos.ferramentas_web.nexuspdf.comprimir_pdf.routes import comprimir_pdf_bp
from modulos.ferramentas_web.nexuspdf.converter_em_pdf.routes import converter_em_pdf_bp
from modulos.ferramentas_web.nexuspdf.ocr_pdf.routes import ocr_pdf_bp
from modulos.ferramentas_web.nexuspdf.editar_pdf.routes import editar_pdf_bp
from modulos.ferramentas_web.nexuspdf.word_em_pdf.routes import word_em_pdf_bp

from models import BlogPost, NewsletterSubscriber, BlogComment

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

SITE_TOOLS = [
    {
        "key": "finance",
        "name": "Gerenciamento Financeiro",
        "url": "/gerenciamento-financeiro/apresentacao",
        "icon_class": "bi bi-cash-stack",
        "description": "Controle receitas e despesas com dashboards, recorrências e workspaces.",
        "variant": "featured",
        "home": {
            "card_class": "tool-card tool-card-finance tool-card-link",
            "badge_class": "tool-badge tool-badge-finance",
            "badge_icon_class": "bi bi-stars",
            "badge_text": "App Android",
            "button_text": "Ver apresentação",
            "points": [
                "Dashboards e relatórios",
                "Categorias, recorrências e lançamentos",
                "Workspaces e compartilhamento",
            ],
        },
    },
    {
        "key": "qr",
        "name": "Gerador de QR Code",
        "url": "/gerador-de-qr-code",
        "icon_class": "bi bi-qr-code",
        "description": "Crie QR Codes personalizados para links, WiFi, vCards e muito mais.",
        "variant": "simple",
        "home": {
            "button_text": "Abrir Ferramenta",
        },
    },
    {
        "key": "images",
        "name": "Conversor de Imagens",
        "url": "/conversor-imagens",
        "icon_class": "bi bi-image",
        "description": "Converta entre JPG, PNG, WEBP, AVIF e PDF. Processamento em lote com compressão.",
        "variant": "simple",
        "home": {
            "button_text": "Abrir Ferramenta",
        },
    },
    {
        "key": "youtube",
        "name": "YouTube Downloader",
        "url": "/youtube-downloader",
        "icon_class": "fab fa-youtube",
        "description": "Baixe vídeos e áudios do YouTube em alta qualidade com múltiplas resoluções.",
        "variant": "simple",
        "home": {
            "button_text": "Abrir Ferramenta",
        },
    },
    {
        "key": "bg_remove",
        "name": "Removedor de Fundo",
        "url": "/removedor-de-fundo",
        "icon_class": "bi bi-scissors",
        "description": "Remova o fundo de imagens com IA em segundos.",
        "variant": "simple",
        "home": {
            "button_text": "Abrir Ferramenta",
        },
    },
    {
        "key": "nexuspdf",
        "name": "NexusPDF",
        "url": "/nexuspdf",
        "icon_class": "bi bi-file-pdf",
        "description": "Suíte completa de ferramentas para PDF: comprimir, converter, OCR e editar.",
        "variant": "simple",
        "home": {
            "button_text": "Abrir NexusPDF",
        },
    },
]

TOOL_PAGES = {
    "finance": {
        "what_is": (
            "O Gerenciamento Financeiro do NEXUSRDR é um sistema para organizar receitas, despesas e contas com foco em clareza e controle. "
            "Ele foi pensado para uso pessoal, familiar ou de pequenos negócios, reunindo lançamentos, categorias, recorrências e dashboards em um único lugar. "
            "Em vez de planilhas espalhadas, você centraliza tudo e acompanha o que entra, o que sai e para onde o dinheiro está indo.\n\n"
            "Além do básico de entradas e saídas, o sistema trabalha com workspaces, permitindo separar contextos (por exemplo: Casa, Empresa, Projeto) e compartilhar com outras pessoas quando necessário. "
            "Isso melhora a governança e evita misturar informações de diferentes objetivos.\n\n"
            "O objetivo é te dar rapidez no registro e previsibilidade no acompanhamento: você entende seu saldo, identifica gastos recorrentes, acompanha tendências por período e toma decisões melhores. "
            "Tudo isso com uma interface moderna, acessível e integrada ao ecossistema de ferramentas do NEXUSRDR."
        ),
        "how_steps": [
            "Crie seu workspace (ex.: Casa ou Empresa) e defina as categorias que você usa no dia a dia.",
            "Cadastre receitas e despesas com data, valor, descrição e categoria.",
            "Configure recorrências (salário, aluguel, assinaturas) para economizar tempo.",
            "Acompanhe dashboards e relatórios para ver total por categoria, mês e tendência de gastos.",
        ],
        "advantages": [
            "Workspaces para separar vida pessoal, família e negócios sem confusão.",
            "Recorrências e organização por categorias para manter consistência.",
            "Dashboards rápidos para decisão (sem planilhas complexas).",
            "Interface moderna, leve e pensada para produtividade.",
            "Evolução contínua junto ao blog com tutoriais e novidades.",
        ],
        "faq": [
            {
                "q": "Preciso pagar para usar?",
                "a": "Você pode usar as funcionalidades básicas gratuitamente. Algumas partes podem evoluir para planos/recursos premium conforme o projeto cresce.",
            },
            {
                "q": "Funciona para família e para empresa?",
                "a": "Sim. A ideia dos workspaces é justamente separar cenários e facilitar o compartilhamento.",
            },
            {
                "q": "Posso registrar despesas recorrentes?",
                "a": "Sim. Recorrências ajudam a automatizar lançamentos como aluguel, assinaturas e mensalidades.",
            },
            {
                "q": "Tem relatórios e dashboards?",
                "a": "Sim. Você consegue visualizar totais por período e por categoria para entender seus gastos.",
            },
            {
                "q": "Consigo separar contas por objetivo?",
                "a": "Sim. Você cria workspaces diferentes (ex.: Casa, Viagem, Empresa) e mantém tudo organizado.",
            },
            {
                "q": "Meus dados ficam seguros?",
                "a": "O sistema usa banco de dados e boas práticas de aplicação. Evite compartilhar senhas e utilize um e-mail de acesso seguro.",
            },
            {
                "q": "Posso acessar pelo celular?",
                "a": "Sim. Há integração com aplicativo e também acesso via navegador, dependendo do módulo.",
            },
            {
                "q": "Como começo mais rápido?",
                "a": "Crie um workspace, adicione as categorias principais e comece registrando os gastos mais frequentes primeiro.",
            },
        ],
    },
    "qr": {
        "what_is": (
            "O Gerador de QR Code do NEXUSRDR é uma ferramenta online para criar QR Codes de forma rápida, gratuita e personalizável. "
            "Você pode gerar códigos para links (URL), textos, redes Wi‑Fi, contatos (vCard) e até mensagens de WhatsApp, ideal para divulgação, cardápios, placas, materiais de marketing e eventos.\n\n"
            "Diferente de geradores limitados, aqui você tem formatos prontos para casos reais: conectar na rede Wi‑Fi sem digitar senha, abrir um link direto do celular, salvar um contato com um toque ou direcionar alguém para uma conversa no WhatsApp. "
            "Isso acelera o acesso e reduz atrito para o usuário final.\n\n"
            "O processo é simples: você escolhe o tipo, preenche os dados, ajusta aparência (cores/tamanho) e baixa o arquivo para usar onde quiser. "
            "O objetivo é te entregar um QR Code funcional, bonito e confiável em poucos segundos, com interface moderna e sem burocracia."
        ),
        "how_steps": [
            "Escolha o tipo de QR Code (URL, Wi‑Fi, Texto, WhatsApp ou vCard).",
            "Preencha as informações necessárias e valide os dados.",
            "Personalize cores e tamanho para combinar com seu material.",
            "Gere o QR Code e faça o download da imagem para usar em impressos ou no digital.",
        ],
        "advantages": [
            "Modelos prontos para URL, Wi‑Fi, WhatsApp e vCard (não só texto).",
            "Personalização visual simples (cores e tamanho).",
            "Geração rápida e interface moderna.",
            "Ideal para marketing, cardápios, eventos e uso corporativo.",
            "Funciona bem em mobile e desktop.",
        ],
        "faq": [
            {
                "q": "O QR Code expira?",
                "a": "Não. O QR Code não expira. O que pode mudar é o conteúdo apontado (ex.: uma URL que deixa de existir).",
            },
            {
                "q": "Posso criar QR Code para Wi‑Fi?",
                "a": "Sim. Informe o nome da rede, senha e tipo de segurança e o QR Code conecta automaticamente.",
            },
            {
                "q": "Consigo gerar para WhatsApp?",
                "a": "Sim. Você pode direcionar para um número e até definir uma mensagem inicial.",
            },
            {
                "q": "Qual tamanho ideal para impressão?",
                "a": "Depende da distância. Em geral, use tamanhos maiores para leitura à distância e teste antes de imprimir em lote.",
            },
            {
                "q": "Posso mudar as cores?",
                "a": "Sim. Você pode escolher cor do código e do fundo, mantendo contraste suficiente.",
            },
            {
                "q": "O QR funciona em qualquer celular?",
                "a": "A maioria dos celulares modernos lê QR Code pela câmera. Para modelos antigos, pode ser necessário app leitor.",
            },
            {
                "q": "O que é vCard?",
                "a": "É um formato de contato. Ao escanear, a pessoa pode salvar nome, telefone e e-mail diretamente.",
            },
            {
                "q": "Posso usar para texto grande?",
                "a": "Sim, mas QR Codes muito densos podem ficar difíceis de ler. Para textos longos, prefira uma URL.",
            },
        ],
    },
    "images": {
        "what_is": (
            "O Conversor de Imagens do NEXUSRDR é uma ferramenta online para converter arquivos entre formatos como JPG, PNG, WEBP, AVIF e PDF, com foco em qualidade e otimização. "
            "Ele é útil tanto para uso pessoal quanto para profissionais que precisam padronizar imagens para sites, e-commerce, redes sociais e documentos.\n\n"
            "Além de converter, a ferramenta oferece ajustes como qualidade e otimização para web, ajudando a reduzir tamanho do arquivo sem destruir a aparência. "
            "Isso melhora performance de páginas, diminui tempo de carregamento e pode contribuir para SEO, principalmente quando você tem muitas imagens.\n\n"
            "O fluxo é simples: você seleciona as imagens, escolhe o formato de saída, define a qualidade desejada e baixa os arquivos convertidos individualmente ou em lote. "
            "O objetivo é economizar tempo e evitar depender de programas pesados, entregando conversões rápidas e consistentes diretamente no navegador."
        ),
        "how_steps": [
            "Envie uma ou várias imagens (lote).",
            "Escolha o formato de saída (ex.: WEBP, PNG, JPG ou PDF).",
            "Ajuste qualidade e opções de otimização quando necessário.",
            "Converta e faça download individual ou em ZIP com tudo pronto.",
        ],
        "advantages": [
            "Conversão em lote para ganhar tempo.",
            "Suporte a formatos modernos (WEBP/AVIF) para web mais rápida.",
            "Controle de qualidade para equilibrar tamanho e aparência.",
            "Download em ZIP para organizar entregas.",
            "Fluxo simples sem instalar programas.",
        ],
        "faq": [
            {
                "q": "Qual formato é melhor para web?",
                "a": "Em geral, WEBP e AVIF entregam boa qualidade com tamanho menor. Depende do suporte do seu público e do seu site.",
            },
            {
                "q": "Posso converter várias imagens de uma vez?",
                "a": "Sim. A ferramenta suporta processamento em lote e permite baixar tudo em um ZIP.",
            },
            {
                "q": "A qualidade cai muito?",
                "a": "Você controla o nível de qualidade. Para muitas imagens, a perda é imperceptível quando bem configurada.",
            },
            {
                "q": "Converte para PDF?",
                "a": "Sim, dependendo do formato de saída selecionado.",
            },
            {
                "q": "Funciona no celular?",
                "a": "Sim, mas para muitos arquivos grandes o desktop costuma ser mais confortável.",
            },
            {
                "q": "Qual o tamanho máximo?",
                "a": "Existe limite prático por upload. Se uma imagem não converter, tente reduzir resolução ou enviar menos arquivos por vez.",
            },
            {
                "q": "Posso manter transparência?",
                "a": "Sim. Use PNG ou WEBP para manter fundo transparente (JPG não suporta transparência).",
            },
            {
                "q": "Por que usar WEBP/AVIF?",
                "a": "São formatos modernos que reduzem o tamanho e aceleram páginas sem perder muita qualidade.",
            },
        ],
    },
    "youtube": {
        "what_is": (
            "O YouTube Downloader do NEXUSRDR permite baixar vídeos ou extrair áudio de links do YouTube de forma simples, com opções de qualidade. "
            "Ele é útil para uso educacional e produtividade, como salvar aulas para assistir offline, organizar referências e baixar áudio para estudo.\n\n"
            "A ferramenta analisa o link, identifica informações do vídeo (título, duração e miniatura) e oferece o download no formato disponível. "
            "Quando você escolhe áudio, o sistema tenta converter para MP3, facilitando consumo em players e dispositivos diversos.\n\n"
            "O foco do NEXUSRDR é manter o processo direto e confiável: colou o link, escolheu a qualidade, baixou. "
            "Como a plataforma muda com frequência, o serviço é mantido com ajustes contínuos para melhorar estabilidade e compatibilidade, sempre buscando uma experiência moderna e sem fricção."
        ),
        "how_steps": [
            "Cole a URL do YouTube e confirme.",
            "Selecione a qualidade (ou melhor disponível) e escolha vídeo ou áudio.",
            "Aguarde a análise e o processamento.",
            "Baixe o arquivo final quando estiver pronto.",
        ],
        "advantages": [
            "Interface rápida: link → escolher → baixar.",
            "Opção de áudio com tentativa de conversão para MP3.",
            "Feedback de erros mais claro (vídeo privado, indisponível, etc.).",
            "Processo direto sem etapas confusas.",
            "Integração com outras ferramentas e conteúdos do NEXUSRDR.",
        ],
        "faq": [
            {
                "q": "Consigo baixar apenas o áudio?",
                "a": "Sim. Selecione a opção de áudio e o sistema tenta gerar MP3 quando possível.",
            },
            {
                "q": "Por que alguns vídeos falham?",
                "a": "Alguns são privados, bloqueados por região ou têm restrições. Nesses casos, o download pode não ser possível.",
            },
            {
                "q": "Qual qualidade devo escolher?",
                "a": "Para a maioria dos casos, “melhor disponível” é suficiente. Se quiser arquivos menores, escolha 360p/480p.",
            },
            {
                "q": "Funciona com Shorts?",
                "a": "Em muitos casos sim. Se falhar, tente copiar a URL completa do vídeo.",
            },
            {
                "q": "O download é instantâneo?",
                "a": "Depende do tamanho do vídeo e do processamento. Vídeos longos podem levar mais tempo.",
            },
            {
                "q": "Preciso instalar algo?",
                "a": "Não. O download é feito pelo navegador.",
            },
            {
                "q": "Posso usar no celular?",
                "a": "Sim, mas dependendo do navegador e do sistema, o comportamento de download pode variar.",
            },
            {
                "q": "O arquivo sai em qual formato?",
                "a": "Vídeos geralmente em MP4 e áudio em MP3 quando a conversão é possível.",
            },
        ],
    },
    "bg_remove": {
        "what_is": (
            "O Removedor de Fundo do NEXUSRDR é uma ferramenta com IA para recortar pessoas, produtos e objetos, removendo o background de imagens em poucos segundos. "
            "Ele é ideal para e-commerce, catálogos, redes sociais, thumbnails e materiais de divulgação, onde um recorte limpo faz diferença na apresentação.\n\n"
            "A ferramenta permite escolher modelos e configurações para diferentes tipos de imagem, ajudando a obter melhor resultado em fotos de produto, retratos e cenas mais complexas. "
            "Após remover o fundo, você pode manter transparência (PNG) ou aplicar um fundo sólido, preparando o arquivo para uso imediato.\n\n"
            "O objetivo é acelerar tarefas que normalmente exigiriam editores como Photoshop: você faz upload, processa, confere o preview e baixa o resultado. "
            "Com isso, você ganha produtividade e mantém padrão visual consistente em seus materiais."
        ),
        "how_steps": [
            "Envie a imagem (ou um lote de imagens).",
            "Escolha o modelo de IA e a qualidade conforme seu caso.",
            "Selecione o tipo de fundo (transparente ou cor sólida).",
            "Processe, visualize o resultado e faça o download do arquivo final.",
        ],
        "advantages": [
            "Recorte com IA em segundos.",
            "Opções de modelo e qualidade para diferentes cenários.",
            "Suporte a processamento em lote para produtividade.",
            "Resultado pronto para e-commerce e marketing.",
            "Preview e download direto, sem editor pesado.",
        ],
        "faq": [
            {
                "q": "O fundo sai transparente?",
                "a": "Sim. Você pode gerar PNG com transparência e usar em qualquer design.",
            },
            {
                "q": "Dá para colocar uma cor de fundo?",
                "a": "Sim. Você pode escolher um fundo sólido para padronizar imagens de produto.",
            },
            {
                "q": "Qual modelo devo usar?",
                "a": "Depende da imagem. Para retratos, modelos gerais funcionam bem; para produtos, use configurações que preservem bordas.",
            },
            {
                "q": "Funciona com várias imagens?",
                "a": "Sim. O modo em lote permite processar várias imagens e baixar o resultado em pacote.",
            },
            {
                "q": "Por que algumas bordas ficam ruins?",
                "a": "Imagens com baixa qualidade, sombras fortes ou fundo muito parecido com o objeto podem exigir ajustes de modelo/qualidade.",
            },
            {
                "q": "Tem limite de tamanho?",
                "a": "Há limite de upload por performance. Se falhar, reduza a imagem ou tente novamente com menos arquivos.",
            },
            {
                "q": "Posso usar para e-commerce?",
                "a": "Sim. É um dos melhores usos: padronizar imagens de produto com fundo branco ou transparente.",
            },
            {
                "q": "O arquivo final sai em qual formato?",
                "a": "Normalmente PNG para manter transparência e qualidade.",
            },
        ],
    },
}

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
    
    # Imagens em markdown ![alt](url)
    html = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1" style="max-width:100%;height:auto;border-radius:16px;margin:1.5rem 0;" />', html)
    
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
        site_tools=SITE_TOOLS,
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

@main_bp.route("/sobre")
def about():
    return render_template('about.html')

@main_bp.route("/cookies")
def cookies():
    return render_template('cookies.html')

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
        site_tools=SITE_TOOLS,
        hide_back_button=True,
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

    comments = (
        BlogComment.query
        .filter_by(post_id=post.id, approved=True)
        .order_by(BlogComment.created_at.desc())
        .all()
    )

    return render_template(
        'blog_detail.html',
        post=post,
        related_posts=related_posts,
        comments=comments,
        site_tools=SITE_TOOLS,
        hide_back_button=True,
        get_category_info=get_category_info,
        render_markdown=render_markdown,
    )

@main_bp.route("/blog/<slug>/comentar", methods=["POST"])
def blog_comment_submit(slug):
    post = BlogPost.query.filter_by(slug=slug, active=True).first_or_404()

    author_name = (request.form.get("author_name") or "").strip()
    author_email = (request.form.get("author_email") or "").strip()
    content = (request.form.get("content") or "").strip()
    honeypot = (request.form.get("website") or "").strip()

    if honeypot:
        return redirect(url_for("main.blog_detail", slug=slug) + "#comentarios")

    if not author_name or not content:
        return redirect(url_for("main.blog_detail", slug=slug, comment="error") + "#comentarios")

    if len(content) > 2000:
        content = content[:2000]

    approved = True
    content_lower = content.lower()
    if "http://" in content_lower or "https://" in content_lower or "www." in content_lower:
        approved = False

    forwarded_for = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    ip_address = forwarded_for or request.remote_addr
    user_agent = (request.headers.get("User-Agent") or "").strip() or None

    comment = BlogComment(
        post_id=post.id,
        author_name=author_name,
        author_email=author_email or None,
        content=content,
        approved=approved,
        ip_address=ip_address,
        user_agent=user_agent[:255] if user_agent else None,
    )

    try:
        db.session.add(comment)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return redirect(url_for("main.blog_detail", slug=slug, comment="error") + "#comentarios")

    status = "ok" if approved else "pending"
    return redirect(url_for("main.blog_detail", slug=slug, comment=status) + "#comentarios")

@main_bp.route("/newsletter-inscrever", methods=["POST"])
def newsletter_subscribe():
    """Recebe inscrições de newsletter a partir do blog e páginas relacionadas."""

    email = (request.form.get("email") or "").strip().lower()
    source = (request.form.get("source") or "").strip() or None
    next_url = request.form.get("next") or request.referrer or url_for("main.blog_list")

    if not email or "@" not in email:
        flash("Informe um e-mail válido para se inscrever na newsletter.", "danger")
        return redirect(next_url)

    try:
        existing = NewsletterSubscriber.query.filter_by(email=email).first()
        if existing:
            if not existing.active:
                existing.active = True
                if source and existing.source != source:
                    existing.source = source
        else:
            subscriber = NewsletterSubscriber(email=email, source=source)
            db.session.add(subscriber)

        db.session.commit()
        flash("Inscrição realizada com sucesso! Você receberá novidades do NEXUSRDR por e-mail.", "success")
    except Exception:
        db.session.rollback()
        flash("Não foi possível salvar sua inscrição agora. Tente novamente em alguns instantes.", "danger")

    return redirect(next_url)

@main_bp.route("/robots.txt")
def robots_txt():
    """Servir o arquivo robots.txt dinamicamente."""
    base_url = os.getenv("APP_BASE_URL", "https://nexusrdr.com.br").rstrip("/")
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {base_url}/sitemap.xml",
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain")

@main_bp.route("/sitemap.xml")
def sitemap():
    """Gera sitemap.xml dinâmico e otimizado para SEO."""

    base_url = os.getenv("APP_BASE_URL", "https://nexusrdr.com.br").rstrip("/")

    pages: list[dict] = []

    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    # Home
    pages.append({
        "loc": f"{base_url}/",
        "lastmod": now_iso,
        "changefreq": "daily",
        "priority": "1.0",
    })

    # Ferramentas do SITE_TOOLS (Dinâmico)
    for tool in SITE_TOOLS:
        pages.append({
            "loc": f"{base_url}{tool['url']}",
            "lastmod": now_iso,
            "changefreq": "daily" if tool.get("variant") == "featured" else "weekly",
            "priority": "0.9",
        })

    # Sub-ferramentas NexusPDF
    nexuspdf_tools = [
        "/nexuspdf/comprimir-pdf",
        "/nexuspdf/converter-em-pdf",
        "/nexuspdf/ocr-pdf",
        "/nexuspdf/editar-pdf",
        "/nexuspdf/documentos-para-pdf",
    ]
    for path in nexuspdf_tools:
        pages.append({
            "loc": f"{base_url}{path}",
            "lastmod": now_iso,
            "changefreq": "weekly",
            "priority": "0.8",
        })

    # Páginas estáticas importantes
    static_pages = [
        ("/blog", "0.9", "daily"),
        ("/sobre", "0.6", "monthly"),
        ("/contact", "0.6", "monthly"),
        ("/privacy", "0.5", "yearly"),
        ("/cookies", "0.5", "yearly"),
        ("/terms", "0.5", "yearly"),
        ("/ia-hub", "0.8", "weekly"),
    ]

    for path, priority, changefreq in static_pages:
        pages.append({
            "loc": f"{base_url}{path}",
            "lastmod": now_iso,
            "changefreq": changefreq,
            "priority": priority,
        })

    # Posts do blog (dinâmicos)
    priority_order = _priority_order()
    posts = (
        BlogPost.query
        .filter(BlogPost.active.is_(True))
        .order_by(priority_order.desc(), BlogPost.created_at.desc())
        .all()
    )

    for post in posts:
        if not post.slug:
            continue

        # Prioridade baseada em destaque
        if getattr(post, "priority", None) == "pinned":
            prio = "0.9"
        elif getattr(post, "priority", None) == "featured":
            prio = "0.85"
        else:
            prio = "0.8"

        last_dt = getattr(post, "updated_at", None) or getattr(post, "created_at", None)
        if last_dt is not None:
            lastmod = last_dt.replace(microsecond=0).isoformat() + "Z"
        else:
            lastmod = now_iso

        pages.append({
            "loc": f"{base_url}/blog/{post.slug}",
            "lastmod": lastmod,
            "changefreq": "weekly",
            "priority": prio,
        })

    # Montar XML
    xml_lines: list[str] = []
    xml_lines.append("<?xml version=\"1.0\" encoding=\"UTF-8\"?>")
    xml_lines.append("<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">")

    for page in pages:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{page['loc']}</loc>")
        xml_lines.append(f"    <lastmod>{page['lastmod']}</lastmod>")
        xml_lines.append(f"    <changefreq>{page['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{page['priority']}</priority>")
        xml_lines.append("  </url>")

    xml_lines.append("</urlset>")

    xml_content = "\n".join(xml_lines)
    return Response(xml_content, mimetype="application/xml")

def register_blueprints(app):
    """Registra todos os blueprints globais da aplicação."""
    # Home / página principal
    app.register_blueprint(main_bp)
    
    # Admin
    app.register_blueprint(administrador_bp)

    # Gerenciamento Financeiro (Web + API)
    app.register_blueprint(gerenciamento_financeiro_bp, url_prefix="/gerenciamento-financeiro")
    app.register_blueprint(api_financeiro_bp, url_prefix="/gerenciamento-financeiro")

    # Conversor de imagens

    # Gerador De Qr Code
    app.register_blueprint(gerador_de_qr_code_bp, url_prefix="/gerador-de-qr-code")

    # YouTube Downloader
    app.register_blueprint(youtube_bp, url_prefix="/youtube-downloader")

    # Removedor De Fundo
    app.register_blueprint(removedor_de_fundo_bp, url_prefix="/removedor-de-fundo")
    app.register_blueprint(conversor_bp, url_prefix="/conversor-imagens")

    # NexusPDF - suíte de ferramentas PDF e texto
    app.register_blueprint(nexuspdf_bp, url_prefix="/nexuspdf")
    app.register_blueprint(comprimir_pdf_bp, url_prefix="/nexuspdf/comprimir-pdf")
    app.register_blueprint(converter_em_pdf_bp, url_prefix="/nexuspdf/converter-em-pdf")
    app.register_blueprint(ocr_pdf_bp, url_prefix="/nexuspdf/ocr-pdf")
    app.register_blueprint(editar_pdf_bp, url_prefix="/nexuspdf/editar-pdf")
    app.register_blueprint(word_em_pdf_bp, url_prefix="/nexuspdf/documentos-para-pdf")
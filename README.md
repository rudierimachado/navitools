# NAVITOOLS

Plataforma web modular construída em Flask para reunir ferramentas online (atualmente com foco no Conversor de Imagens) com layout moderno, responsivo e preparado para monetização.

## ✨ Principais Recursos
- **Arquitetura modular:** blueprints separados para cada ferramenta (`ferramentas/`), além de painel administrativo em `administrador/`.
- **Layout global unificado:** `template_global/base.html` fornece header fixo, sidebar com dropdowns, slots de anúncios e rodapé dinâmico.
- **Conversor de Imagens completo:** upload múltiplo, suporte a diversos formatos (JPG, PNG, WEBP, AVIF, etc.), drag & drop e notificações.
- **Slots de propaganda prontos:**
  - `top_banner`, `bottom_banner` e `sidebar_ad` nos templates.
  - Estilos padrão (`.ad-slot`, `.ad-slot--banner`, `.ad-slot--sidebar`) já previstos em `base.html`.
- **Deploy pronto para Render:** `requirements.txt`, `Procfile` e `run.py` expõem `app` para o Gunicorn.

## 🗂 Estrutura Básica
```
rdr ferramentas/
├── administrador/
├── ferramentas/
│   └── conversor_imagens/
├── static/
├── template_global/
│   ├── base.html
│   ├── home.html
│   └── ...
├── run.py
├── requirements.txt
├── Procfile
└── README.md
```

## 🔧 Como executar localmente
1. **Clonar o repositório:**
   ```bash
   git clone https://github.com/rudierimachado/navitools.git
   cd navitools
   ```
2. **Criar ambiente virtual (opcional, mas recomendado):**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
3. **Instalar dependências:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Configurar variáveis de ambiente:**
   - Criar um `.env` com pelo menos `SECRET_KEY="sua_chave_segura"`.
5. **Rodar o servidor Flask:**
   ```bash
   python run.py
   ```
   O app ficará disponível em `http://localhost:5000`.

## 🚀 Deploy no Render
1. Fazer push do código para o GitHub (`git commit && git push`).
2. No painel do [Render](https://render.com):
   - Criar **Web Service** conectado ao repositório `navitools`.
   - **Build Command:** `pip install -r requirements.txt` (default).
   - **Start Command:** `gunicorn run:app` (o `Procfile` também já contém essa instrução).
   - Adicionar `SECRET_KEY` (e demais variáveis necessárias) em **Environment Variables**.
3. Salvar e iniciar o deploy. O Render utilizará o `gunicorn` para servir o app.

## 📣 Como usar os slots de anúncios
- **Banner superior:** sobrescreva `{% block top_banner %}` em qualquer template que estenda `base.html`.
- **Banner inferior:** use `{% block bottom_banner %}`.
- **Banner lateral:** sobrescreva `{% block sidebar_ad %}` para definir anúncios específicos por página.
- Os estilos `.ad-slot`, `.ad-slot--banner` e `.ad-slot--sidebar` podem ser reutilizados ou substituídos conforme a necessidade.

## 🧭 Próximos passos sugeridos
- Adicionar novas ferramentas em `ferramentas/` reaproveitando a estrutura existente.
- Conectar provedores de anúncios reais (AdSense, banners próprios ou afiliados) substituindo os placeholders.
- Expandir o painel administrativo para gerenciar módulos e métricas.

---
Projeto desenvolvido por **Rudieri Machado**. Sinta-se à vontade para abrir issues ou sugestões no repositório.

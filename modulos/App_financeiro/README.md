# App Financeiro - Módulo de Gerenciamento Financeiro

## 📋 Visão Geral

Este módulo fornece funcionalidades de gestão financeira pessoal e familiar para o NEXUSRDR, incluindo:

- **API REST** para aplicativo mobile Flutter
- **Interface Web** para navegador
- Controle de receitas e despesas
- Workspaces colaborativos
- Categorias e subcategorias personalizáveis
- Relatórios e dashboards

## 🏗️ Estrutura do Módulo

```
App_financeiro/
├── __init__.py          # Inicialização do módulo
├── api.py               # Endpoints JSON para Flutter (API REST)
├── routes.py            # Rotas web (HTML) para navegador
├── templates/           # Templates HTML (Jinja2)
└── README.md            # Esta documentação
```

## 🔌 Endpoints da API (Flutter)

Todos os endpoints estão sob o prefixo `/gerenciamento-financeiro/api/`

### Autenticação

#### POST `/gerenciamento-financeiro/api/login`
Login de usuário via app mobile.

**Request:**
```json
{
  "email": "usuario@exemplo.com",
  "password": "senha123",
  "remember_me": true  // opcional
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Login realizado com sucesso",
  "user": {
    "id": 1,
    "email": "usuario@exemplo.com"
  }
}
```

**Response (401):**
```json
{
  "success": false,
  "message": "E-mail ou senha inválidos."
}
```

---

#### POST `/gerenciamento-financeiro/api/register`
Criação de nova conta via app mobile.

**Request (JSON ou form-urlencoded):**
```json
{
  "email": "novo@exemplo.com",
  "password": "senha123",
  "confirm_password": "senha123"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Conta criada com sucesso! Faça login para continuar."
}
```

**Response (400):**
```json
{
  "success": false,
  "message": "Este e-mail já está cadastrado."
}
```

---

#### POST `/gerenciamento-financeiro/api/logout`
Logout da sessão atual.

**Response (200):**
```json
{
  "success": true,
  "message": "Logout realizado com sucesso"
}
```

---

#### GET `/gerenciamento-financeiro/api/me`
Retorna dados do usuário logado.

**Response (200):**
```json
{
  "success": true,
  "user": {
    "id": 1,
    "email": "usuario@exemplo.com",
    "is_email_verified": true,
    "created_at": "2025-01-15T10:30:00"
  }
}
```

**Response (401):**
```json
{
  "success": false,
  "message": "Não autenticado"
}
```

## 🌐 Rotas Web (Navegador)

- `/gerenciamento-financeiro/` - Página inicial (em desenvolvimento)
- `/gerenciamento-financeiro/apresentacao` - Apresentação do sistema (em desenvolvimento)

## 🔧 Integração com o Sistema

### Como funciona

1. **`run.py`** inicia o servidor Flask
2. **`global_blueprints.py`** registra os blueprints:
   - `gerenciamento_financeiro_bp` (rotas web)
   - `api_financeiro_bp` (API REST)
3. Ambos usam o prefixo `/gerenciamento-financeiro`
4. Compartilham:
   - Banco de dados (`extensions.db`)
   - Modelos (`models.py`)
   - Sessões Flask
   - Serviços de email

### Dependências

- **Flask** - Framework web
- **SQLAlchemy** - ORM para banco de dados
- **Werkzeug** - Utilitários (hash de senha, etc.)
- **models.py** - User, Workspace, LoginAudit, etc.
- **extensions.py** - db, migrate

## 📱 Configuração do Flutter

No app Flutter, configure a URL base:

**Debug (local):**
```dart
const String apiBaseUrl = 'http://localhost:5000';
```

**Production:**
```dart
const String apiBaseUrl = 'https://nexusrdr.com.br';
```

## 🚀 Deploy

O módulo roda na **mesma instância** do servidor principal (Render free tier).

**Não é necessário:**
- ❌ Subir nova instância
- ❌ Configurar novo banco de dados
- ❌ Duplicar código

**Tudo compartilhado:**
- ✅ Mesmo servidor (`run.py`)
- ✅ Mesmo banco de dados
- ✅ Mesmos usuários e workspaces
- ✅ Mesmas sessões

## 🔐 Segurança

- Senhas armazenadas com hash (Werkzeug)
- Sessões Flask com cookies seguros
- CORS configurado para permitir Flutter
- Validações no backend (não confiar no frontend)
- Audit log de tentativas de login

## 📝 Próximos Passos

1. **Migrar rotas do `finance_app/backend/routes.py`** para `routes.py`
2. **Adicionar endpoints de dashboard** em `api.py`
3. **Criar templates HTML** na pasta `templates/`
4. **Implementar gestão de transações** (receitas/despesas)
5. **Adicionar relatórios e gráficos**

## 🐛 Debug

Para testar os endpoints localmente:

```bash
# Iniciar servidor
cd navitools
python run.py

# Testar login
curl -X POST http://localhost:5000/gerenciamento-financeiro/api/login \
  -H "Content-Type: application/json" \
  -d '{"email":"teste@exemplo.com","password":"senha123"}'
```

## 📚 Documentação Adicional

- **Models:** Ver `navitools/models.py`
- **Extensions:** Ver `navitools/extensions.py`
- **Email Service:** Ver `navitools/email_service.py`
- **Config DB:** Ver `navitools/config_db.py`

---

**Versão:** 1.0.0  
**Última atualização:** 18/12/2025

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    send_file,
    make_response,
    current_app,
)
from io import BytesIO
from sqlalchemy import func, extract, and_, or_, inspect, text, case, desc
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
import calendar
import math
import json
import os
import time
import hashlib
import requests
import re

from extensions import db
from email_service import send_share_invitation, send_share_accepted, send_verification_code, send_password_reset, send_workspace_invitation
from models import (
    User,
    LoginAudit,
    FinanceConfig,
    FamilyMember,
    Category,
    SubCategory,
    Transaction,
    RecurringTransaction,
    MonthlyClosure,
    MonthlyFixedExpense,
    SystemShare,
    EmailVerification,
    PasswordReset,
    Workspace,
    WorkspaceMember,
    WorkspaceInvite,
)
import random
import secrets

gerenciamento_financeiro_bp = Blueprint(
    "gerenciamento_financeiro",
    __name__,
    template_folder="templates",
)


@gerenciamento_financeiro_bp.after_request
def _finance_no_cache_headers(resp):
    try:
        p = request.path or ""
        if "/gerenciamento-financeiro/api/" in p:
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp

_AI_RECOMMENDATION_CACHE = {}
_AI_TOKEN_USAGE = {}

_CATEGORIES_WORKSPACE_COLUMN_READY = False
_TRANSACTIONS_CLOSE_COLUMNS_READY = False
_TRANSACTIONS_SUBCATEGORY_TEXT_READY = False
_RECURRING_SUBCATEGORY_TEXT_READY = False

class IconGenerationError(Exception):
    """Raised when the AI icon generation process cannot complete."""
    pass


def _log_debug(msg: str) -> None:
    try:
        if current_app and getattr(current_app, "debug", False):
            current_app.logger.info(msg)
    except Exception:
        pass


def _log_exception(msg: str) -> None:
    try:
        if current_app:
            current_app.logger.exception(msg)
    except Exception:
        pass


def _ensure_categories_workspace_column() -> None:
    """Garante que a coluna categories.workspace_id exista.

    Como o projeto pode estar rodando sem migrations aplicadas, fazemos um ALTER TABLE
    seguro (coluna nullable) na primeira chamada.
    """
    global _CATEGORIES_WORKSPACE_COLUMN_READY
    if _CATEGORIES_WORKSPACE_COLUMN_READY:
        return

    try:
        cols = [c.get("name") for c in inspect(db.engine).get_columns("categories")]
        if "workspace_id" not in cols:
            db.session.execute(text("ALTER TABLE categories ADD COLUMN workspace_id INTEGER"))
            try:
                db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_categories_workspace_id ON categories (workspace_id)"))
            except Exception:
                pass
            db.session.commit()
        _CATEGORIES_WORKSPACE_COLUMN_READY = True
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        _log_exception(f"[CATEGORIES] Erro ao garantir coluna workspace_id: {e}")
        # não marcar como ready para tentar novamente depois


def _ensure_transactions_close_columns() -> None:
    """Garante que as colunas para fechamento de despesas existam."""
    global _TRANSACTIONS_CLOSE_COLUMNS_READY
    if _TRANSACTIONS_CLOSE_COLUMNS_READY:
        return

    try:
        cols = [c.get("name") for c in inspect(db.engine).get_columns("transactions")]
        dialect = getattr(db.engine, "dialect", None)
        dialect_name = getattr(dialect, "name", "") if dialect else ""
        blob_type = "BYTEA" if dialect_name == "postgresql" else "BLOB"
        columns_to_add = {
            "is_closed": "BOOLEAN DEFAULT FALSE",
            "proof_document_url": "VARCHAR(500)",
            "proof_document_data": blob_type,
            "proof_document_name": "VARCHAR(255)",
            "proof_document_storage_name": "VARCHAR(255)",
            "proof_document_mime": "VARCHAR(255)",
            "proof_document_size": "INTEGER",
            "closed_date": "DATE",
            "closed_by_user_id": "INTEGER",
        }
        
        for col_name, col_def in columns_to_add.items():
            if col_name not in cols:
                db.session.execute(text(f"ALTER TABLE transactions ADD COLUMN {col_name} {col_def}"))
        
        # Add foreign key constraint for closed_by_user_id if it was added
        if "closed_by_user_id" not in cols:
            try:
                db.session.execute(text("ALTER TABLE transactions ADD CONSTRAINT fk_transactions_closed_by_user FOREIGN KEY (closed_by_user_id) REFERENCES users (id)"))
            except Exception:
                pass  # Constraint may already exist or fail silently
        
        db.session.commit()
        _TRANSACTIONS_CLOSE_COLUMNS_READY = True
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        _log_exception(f"[TRANSACTIONS] Erro ao garantir colunas de fechamento: {e}")
        # não marcar como ready para tentar novamente depois


def _ensure_transactions_subcategory_text_column() -> None:
    """Garante que a coluna transactions.subcategory_text exista."""
    global _TRANSACTIONS_SUBCATEGORY_TEXT_READY
    if _TRANSACTIONS_SUBCATEGORY_TEXT_READY:
        return

    try:
        cols = [c.get("name") for c in inspect(db.engine).get_columns("transactions")]
        if "subcategory_text" not in cols:
            db.session.execute(text("ALTER TABLE transactions ADD COLUMN subcategory_text VARCHAR(255)"))
            db.session.commit()
        _TRANSACTIONS_SUBCATEGORY_TEXT_READY = True
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        _log_exception(f"[TRANSACTIONS] Erro ao garantir coluna subcategory_text: {e}")


def _ensure_recurring_subcategory_text_column() -> None:
    """Garante que a coluna recurring_transactions.subcategory_text exista."""
    global _RECURRING_SUBCATEGORY_TEXT_READY
    if _RECURRING_SUBCATEGORY_TEXT_READY:
        return

    try:
        cols = [c.get("name") for c in inspect(db.engine).get_columns("recurring_transactions")]
        if "subcategory_text" not in cols:
            db.session.execute(text("ALTER TABLE recurring_transactions ADD COLUMN subcategory_text VARCHAR(255)"))
            db.session.commit()
        _RECURRING_SUBCATEGORY_TEXT_READY = True
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        _log_exception(f"[RECURRING] Erro ao garantir coluna subcategory_text: {e}")


_RECURRING_EXCLUSIONS_READY = False


def _ensure_recurring_exclusions_table() -> None:
    """Garante a tabela de exclusões de recorrências (para não recriar ocorrências deletadas)."""
    global _RECURRING_EXCLUSIONS_READY
    if _RECURRING_EXCLUSIONS_READY:
        return

    try:
        dialect = getattr(db.engine, "dialect", None)
        dialect_name = getattr(dialect, "name", "") if dialect else ""

        if dialect_name == "postgresql":
            pk = "SERIAL PRIMARY KEY"
            created_at = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        else:
            pk = "INTEGER PRIMARY KEY AUTOINCREMENT"
            created_at = "DATETIME DEFAULT CURRENT_TIMESTAMP"

        db.session.execute(text(
            "CREATE TABLE IF NOT EXISTS recurring_transaction_exclusions ("
            f"id {pk}, "
            "workspace_id INTEGER NOT NULL, "
            "recurring_transaction_id INTEGER NOT NULL, "
            "transaction_date DATE NOT NULL, "
            f"created_at {created_at}, "
            "UNIQUE(workspace_id, recurring_transaction_id, transaction_date)"
            ")"
        ))
        try:
            db.session.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_rte_ws_series_date ON recurring_transaction_exclusions (workspace_id, recurring_transaction_id, transaction_date)"
            ))
        except Exception:
            pass
        db.session.commit()
        _RECURRING_EXCLUSIONS_READY = True
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        _log_exception(f"[RECURRING_EXCLUSIONS] Erro ao garantir tabela: {e}")
        # não marcar como ready para tentar novamente depois


def _ensure_default_subcategories(category_id: int) -> None:
    """Cria subcategorias padrão para uma categoria específica se não existirem."""
    try:
        cat = Category.query.get(category_id)
        if not cat:
            return

        presets = {
            "Contas": [
                {"name": "Internet", "icon": "🌐", "color": "#3b82f6"},
                {"name": "Energia", "icon": "💡", "color": "#f59e0b"},
                {"name": "Água", "icon": "🚰", "color": "#06b6d4"},
                {"name": "Gás", "icon": "🔥", "color": "#ef4444"},
                {"name": "Telefone", "icon": "📱", "color": "#6366f1"},
            ],
            "Moradia": [
                {"name": "Aluguel", "icon": "🏠", "color": "#14b8a6"},
                {"name": "Condomínio", "icon": "🏢", "color": "#64748b"},
                {"name": "Manutenção", "icon": "🛠️", "color": "#f97316"},
            ],
            "Transporte": [
                {"name": "Combustível", "icon": "⛽", "color": "#f59e0b"},
                {"name": "Aplicativos", "icon": "🚕", "color": "#3b82f6"},
                {"name": "Ônibus/Metro", "icon": "🚇", "color": "#10b981"},
            ],
        }

        if cat.name not in presets:
            return
            
        # Verificar se já existem subcategorias para esta categoria
        exists = SubCategory.query.filter_by(category_id=category_id).count()
        if exists > 0:
            return
            
        # Criar subcategorias padrão
        for sc in presets[cat.name]:
            db.session.add(SubCategory(
                config_id=cat.config_id,
                workspace_id=cat.workspace_id,
                category_id=category_id,
                name=sc["name"],
                icon=sc.get("icon"),
                color=sc.get("color"),
                is_default=True,
                is_active=True,
            ))
        db.session.commit()
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        _log_exception(f"[SUBCATEGORIES] Erro ao criar subcategorias padrão: {e}")


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def _ai_rate_limit_check(user_id: int, tokens_to_consume: int) -> tuple[bool, int, int]:
    limit = int(os.getenv("GROQ_TOKENS_PER_MINUTE", "6000") or "6000")
    now = time.time()
    window_start = now - 60

    entries = _AI_TOKEN_USAGE.get(user_id) or []
    entries = [(ts, t) for (ts, t) in entries if ts >= window_start]
    used = sum(t for (_, t) in entries)

    if used + tokens_to_consume > limit:
        _AI_TOKEN_USAGE[user_id] = entries
        return False, used, limit

    entries.append((now, tokens_to_consume))
    _AI_TOKEN_USAGE[user_id] = entries
    return True, used + tokens_to_consume, limit


def _fallback_icon_for_category(name: str, ctype: str | None) -> str:
    n = str(name or "").lower()
    if "mercad" in n or "super" in n:
        return "🛒"
    if "alug" in n or "morad" in n or "casa" in n:
        return "🏠"
    if "internet" in n or "wifi" in n:
        return "📶"
    if "energia" in n or "luz" in n:
        return "💡"
    if "agua" in n:
        return "🚰"
    if "gas" in n:
        return "🔥"
    if any(word in n for word in ["carro", "uber", "ônibus", "onibus", "transporte"]):
        return "🚗"
    if any(word in n for word in ["saúde", "saude", "médic", "medic", "farm"]):
        return "💊"
    if any(word in n for word in ["salár", "salari", "renda"]):
        return "💼"
    if any(word in n for word in ["pix", "transfer"]):
        return "🏦"
    return "💰" if (ctype or "").lower() == "income" else "💸"


PLACEHOLDER_CATEGORY_ICONS = {"💰", "💸"}


def _fallback_icon_for_subcategory(
    name: str,
    category_name: str | None,
    ctype: str | None,
) -> str:
    icon = _fallback_icon_for_category(name, ctype)
    if not icon and category_name:
        icon = _fallback_icon_for_category(category_name, ctype)
    return icon or ("💰" if (ctype or "").lower() == "income" else "💸")


def _fetch_ai_icon_mapping(user_id: int, items: list[dict], context_label: str) -> tuple[dict, list[str]]:
    """
    items: [{"id": "123", "name": "...", "type": "...", ...}]
    Returns (mapping, notes)
    """
    notes: list[str] = []
    if not items:
        return {}, notes

    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        notes.append("IA indisponível: GROQ_API_KEY não configurada. Aplicando fallback.")
        return {}, notes

    model = os.getenv("GROQ_ICON_MODEL", os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"))
    max_tokens = int(os.getenv("GROQ_ICON_MAX_TOKENS", "350") or "350")

    system_prompt = (
        "Você escolhe emojis para categorias financeiras. "
        "Responda APENAS com JSON válido (sem markdown) no formato: {\"<id>\": \"<emoji>\", ...}. "
        "Use apenas UM emoji por item. Não use texto extra. Contexto: "
        f"{context_label}"
    )
    user_prompt = "Itens: " + json.dumps(items, ensure_ascii=False)

    tokens_to_consume = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt) + max_tokens
    ok, used_now, limit = _ai_rate_limit_check(user_id=user_id, tokens_to_consume=tokens_to_consume)
    if not ok:
        raise IconGenerationError(
            f"Limite de uso de IA atingido. Aguarde 1 minuto. ({used_now}/{limit} tokens)"
        )

    try:
        groq_resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
            timeout=35,
        )
    except Exception as e:
        raise IconGenerationError(f"Falha ao chamar IA: {e}") from e

    if groq_resp.status_code >= 400:
        try:
            err_body = groq_resp.json()
        except Exception:
            err_body = groq_resp.text
        raise IconGenerationError(f"Erro na IA ({groq_resp.status_code}): {err_body}")

    try:
        payload = groq_resp.json()
        content = (((payload.get("choices") or [])[0] or {}).get("message") or {}).get("content")
        content = (content or "").strip()
    except Exception:
        content = ""

    mapping: dict[str, str] = {}
    if content:
        try:
            m = re.search(r"\{[\s\S]*\}", content)
            raw = m.group(0) if m else content
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                mapping = parsed
        except Exception as e:
            raise IconGenerationError(f"Resposta inválida da IA: {content}") from e

    return mapping, notes


@gerenciamento_financeiro_bp.route("/download/app")
def download_app():
    """Serve o APK do aplicativo financeiro Android."""
    apk_path = os.path.join(os.path.dirname(__file__), "app-release.apk")

    if not os.path.exists(apk_path):
        flash("Arquivo de instalação do app não encontrado. Tente novamente mais tarde.", "warning")
        return redirect(url_for("gerenciamento_financeiro.login"))

    return send_file(
        apk_path,
        as_attachment=True,
        download_name="nexus-financeiro.apk",
    )


def _log_attempt(email: str, succeeded: bool, message: str | None = None, user_id: int | None = None):
    audit = LoginAudit(
        email=email,
        succeeded=succeeded,
        message=message,
        user_id=user_id,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    db.session.add(audit)
    db.session.commit()

def _ensure_default_categories(user_id: int, workspace_id: int | None = None):
    """Garante que existam categorias padrão para o usuário.

    Se workspace_id for fornecido, as categorias serão criadas/consultadas no escopo do workspace.
    """
    _ensure_categories_workspace_column()
    config = FinanceConfig.query.filter_by(user_id=user_id).first()
    if not config:
        config = FinanceConfig(user_id=user_id, setup_completed=True)
        db.session.add(config)
        db.session.flush()

    if workspace_id is None:
        return

    # Verificar se já existem categorias para este workspace
    existing_count = Category.query.filter_by(config_id=config.id, workspace_id=workspace_id).count()
    if existing_count > 0:
        return

    # Migração leve: se existirem categorias antigas sem workspace_id, mover para este workspace
    legacy = Category.query.filter_by(config_id=config.id, workspace_id=None).all()
    if legacy:
        for c in legacy:
            c.workspace_id = workspace_id
        try:
            db.session.commit()
            return
        except Exception:
            db.session.rollback()

    # Categorias padrão de receita (incluindo Salário)
    income_categories = [
        {"name": "Salário", "icon": "💼", "color": "#10b981"},
        {"name": "Freelance", "icon": "💻", "color": "#3b82f6"},
        {"name": "Investimentos", "icon": "📈", "color": "#8b5cf6"},
        {"name": "Vendas", "icon": "🛒", "color": "#06b6d4"},
        {"name": "Aluguel Recebido", "icon": "🏠", "color": "#14b8a6"},
        {"name": "Outros Ganhos", "icon": "💰", "color": "#f59e0b"},
    ]

    # Categorias padrão de despesa
    expense_categories = [
        {"name": "Alimentação", "icon": "🍔", "color": "#ef4444"},
        {"name": "Transporte", "icon": "🚗", "color": "#f59e0b"},
        {"name": "Moradia", "icon": "🏡", "color": "#ec4899"},
        {"name": "Saúde", "icon": "⚕️", "color": "#f43f5e"},
        {"name": "Educação", "icon": "📚", "color": "#6366f1"},
        {"name": "Lazer", "icon": "🎮", "color": "#8b5cf6"},
        {"name": "Vestuário", "icon": "👕", "color": "#a855f7"},
        {"name": "Contas", "icon": "📄", "color": "#ef4444"},
        {"name": "Outros Gastos", "icon": "💸", "color": "#64748b"},
    ]

    # Criar categorias de receita
    for cat_data in income_categories:
        category = Category(
            config_id=config.id,
            workspace_id=workspace_id,
            name=cat_data["name"],
            type="income",
            icon=cat_data["icon"],
            color=cat_data["color"],
            is_default=True,
            is_active=True
        )
        db.session.add(category)

    # Criar categorias de despesa
    for cat_data in expense_categories:
        category = Category(
            config_id=config.id,
            workspace_id=workspace_id,
            name=cat_data["name"],
            type="expense",
            icon=cat_data["icon"],
            color=cat_data["color"],
            is_default=True,
            is_active=True
        )
        db.session.add(category)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        _log_exception(f"Erro ao criar categorias padrão: {e}")

# ============================================================================
# ROTAS DE AUTENTICAÇÃO
# ============================================================================

def _get_accessible_user_ids(user_id):
    """Retorna lista de user_ids que o usuário tem acesso (próprio + compartilhados)"""
    user_ids = [user_id]  # Sempre inclui o próprio usuário
    
    # Adicionar IDs de sistemas compartilhados com este usuário (aceitos)
    shared_systems = SystemShare.query.filter_by(
        shared_user_id=user_id,
        status='accepted'
    ).all()
    
    for share in shared_systems:
        user_ids.append(share.owner_id)
    
    return user_ids


def _get_user_workspace_role(user_id: int, workspace_id: int) -> str | None:
    """Retorna a role do usuário no workspace: owner/editor/viewer ou None."""
    workspace = Workspace.query.get(workspace_id)
    if not workspace:
        return None

    if workspace.owner_id == user_id:
        return "owner"

    member = WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=user_id).first()
    return member.role if member else None


def _ensure_recurring_transactions_for_month(workspace_id: int, year: int, month: int) -> None:
    if not workspace_id:
        return

    try:
        from calendar import monthrange

        month_first = date(year, month, 1)
        month_last = date(year, month, monthrange(year, month)[1])

        recurring = (
            RecurringTransaction.query
            .join(Category, RecurringTransaction.category_id == Category.id)
            .filter(Category.workspace_id == workspace_id)
            .filter(RecurringTransaction.is_active == True)
            .all()
        )

        for rt in recurring:
            if getattr(rt, "frequency", None) != "monthly":
                continue

            if rt.start_date and rt.start_date > month_last:
                continue
            if rt.end_date and rt.end_date < month_first:
                continue

            day = int(getattr(rt, "day_of_month", 1) or 1)
            day = max(1, min(day, month_last.day))
            tx_date = date(year, month, day)
            if rt.start_date and tx_date < rt.start_date:
                continue

            try:
                _ensure_recurring_exclusions_table()
                excluded = db.session.execute(
                    text(
                        "SELECT 1 FROM recurring_transaction_exclusions "
                        "WHERE workspace_id = :ws AND recurring_transaction_id = :rid AND transaction_date = :dt "
                        "LIMIT 1"
                    ),
                    {"ws": workspace_id, "rid": int(rt.id), "dt": tx_date},
                ).first()
                if excluded:
                    continue
            except Exception:
                pass

            exists = (
                Transaction.query
                .filter(
                    Transaction.workspace_id == workspace_id,
                    Transaction.recurring_transaction_id == rt.id,
                    Transaction.transaction_date == tx_date,
                )
                .first()
            )
            if exists:
                continue

            tx = Transaction(
                user_id=rt.user_id,
                workspace_id=workspace_id,
                description=rt.description,
                notes=getattr(rt, "notes", None),
                amount=float(rt.amount),
                type=rt.type,
                category_id=rt.category_id,
                subcategory_id=None,
                subcategory_text=getattr(rt, "subcategory_text", None),
                transaction_date=tx_date,
                frequency="once",
                is_recurring=True,
                is_paid=True,
                is_fixed=True,
                recurring_transaction_id=rt.id,
            )
            db.session.add(tx)

        db.session.commit()
    except Exception:
        db.session.rollback()

@gerenciamento_financeiro_bp.route("/")
def home():
    if "finance_user_id" not in session:
        return redirect(url_for("gerenciamento_financeiro.apresentacao"))

    _ensure_transactions_close_columns()

    if "active_workspace_id" not in session:
        user_id = session["finance_user_id"]
        default_workspace = Workspace.query.filter_by(owner_id=user_id).first()
        if not default_workspace:
            default_workspace = Workspace(
                owner_id=user_id,
                name="Meu Workspace",
                description="Workspace padrão",
                color="#3b82f6"
            )
            db.session.add(default_workspace)
            db.session.commit()

        session["active_workspace_id"] = default_workspace.id

    user_id = session["finance_user_id"]
    workspace_id = session.get("active_workspace_id")
    
    user = User.query.get(user_id)
    
    # IDs de usuários cujos dados este usuário pode acessar
    accessible_ids = _get_accessible_user_ids(user_id)
    
    # Verificar se há convites pendentes para este usuário
    pending_invites = SystemShare.query.filter_by(
        shared_email=user.email.lower(),
        status='pending'
    ).all()
    
    # Se houver convites pendentes, mostrar alerta
    if pending_invites:
        count = len(pending_invites)
        if count == 1:
            owner = User.query.get(pending_invites[0].owner_id)
            invite_type = "membro da família" if pending_invites[0].share_type == "family" else "contador/consultor"
            flash(f"Você tem 1 convite pendente de {owner.email} como {invite_type}. Clique em 'Compartilhar Sistema' → 'Convites Recebidos' para aceitar ou recusar.", "info")
        else:
            flash(f"Você tem {count} convites pendentes. Clique em 'Compartilhar Sistema' → 'Convites Recebidos' para gerenciá-los.", "info")
    
    # Garantir categorias padrão (no escopo do workspace ativo)
    owner_id = user_id
    try:
        ws = Workspace.query.get(workspace_id) if workspace_id else None
        if ws:
            owner_id = ws.owner_id
    except Exception:
        owner_id = user_id
    _ensure_default_categories(owner_id, workspace_id)

    # Estatísticas principais
    today = datetime.utcnow().date()
    try:
        selected_month = int(request.args.get("month", today.month))
        selected_year = int(request.args.get("year", today.year))
        if selected_month < 1 or selected_month > 12:
            selected_month = today.month
        if selected_year < 2000 or selected_year > 2100:
            selected_year = today.year
    except Exception:
        selected_month = today.month
        selected_year = today.year

    from calendar import monthrange
    month_start = date(selected_year, selected_month, 1)
    month_end = date(selected_year, selected_month, monthrange(selected_year, selected_month)[1])

    try:
        _ensure_recurring_transactions_for_month(workspace_id=workspace_id, year=selected_year, month=selected_month)
    except Exception:
        pass

    # Totais até o fim do mês selecionado (evita somar lançamentos futuros)
    total_income = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "income",
            Transaction.transaction_date <= month_end,
        )
        .scalar()
    )
    total_expense = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "expense",
            Transaction.transaction_date <= month_end,
        )
        .scalar()
    )

    # Totais do mês selecionado (do workspace ativo)
    monthly_income = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "income",
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end,
        )
        .scalar()
    )
    monthly_expense = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end,
        )
        .scalar()
    )

    monthly_paid_expense = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "expense",
            Transaction.is_closed == True,
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end,
        )
        .scalar()
    )

    # Contadores (do workspace ativo)
    income_count = (
        Transaction.query
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "income",
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end,
        )
        .count()
    )
    expense_count = (
        Transaction.query
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end,
        )
        .count()
    )

    balance = (total_income or 0) - (total_expense or 0)
    savings = (monthly_income or 0) - (monthly_expense or 0)
    savings_rate = (savings / monthly_income * 100) if monthly_income else 0

    # Transações recentes (apenas do mês selecionado)
    recent_transactions = (
        Transaction.query
        .options(joinedload(Transaction.category), joinedload(Transaction.subcategory))
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end,
        )
        .order_by(Transaction.transaction_date.desc())
        .limit(500)
        .all()
    )

    # Vencimentos próximos (despesas não pagas) (do workspace ativo)
    today = date.today()
    vencimentos = (
        Transaction.query
        .options(joinedload(Transaction.category), joinedload(Transaction.subcategory))
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "expense",
            Transaction.is_paid == False,
            Transaction.transaction_date >= today - timedelta(days=7),
        )
        .order_by(Transaction.transaction_date.asc())
        .limit(10)
        .all()
    )

    # Marcar flags de status relativos à data
    for v in vencimentos:
        v.is_overdue = v.transaction_date < today
        v.is_today = v.transaction_date == today

    # Obter workspace ativo
    active_workspace = None
    if workspace_id:
        active_workspace = Workspace.query.get(workspace_id)
    
    return render_template(
        "financeiro_dashboard.html",
        user=user,
        balance=balance,
        total_income=total_income or 0,
        total_expense=total_expense or 0,
        monthly_income=monthly_income or 0,
        monthly_expense=monthly_expense or 0,
        monthly_paid_expense=monthly_paid_expense or 0,
        savings=savings,
        savings_rate=savings_rate,
        income_count=income_count,
        expense_count=expense_count,
        recent_transactions=recent_transactions,
        vencimentos=vencimentos,
        now=datetime.now(),
        active_workspace=active_workspace,
        selected_month=selected_month,
        selected_year=selected_year,
    )


@gerenciamento_financeiro_bp.route("/apresentacao")
def apresentacao():
    page_url = request.url
    base_url = (os.getenv("APP_BASE_URL") or request.url_root).rstrip("/")
    canonical_url = base_url + url_for("gerenciamento_financeiro.apresentacao")
    return render_template(
        "finance_public.html",
        page_url=page_url,
        canonical_url=canonical_url,
    )


@gerenciamento_financeiro_bp.route("/api/summary-cards", methods=["GET", "OPTIONS"])
def api_summary_cards():
    origin = request.headers.get("Origin", "*")

    def _json(payload, status=200):
        resp = jsonify(payload)
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return (resp, status) if status != 200 else resp

    if request.method == "OPTIONS":
        return _json({"ok": True}, 200)

    if "finance_user_id" not in session:
        return _json({"error": "Não autorizado"}, 401)

    _ensure_transactions_close_columns()

    user_id = session["finance_user_id"]
    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        # Tentar obter ou criar workspace padrão automaticamente
        default_workspace = Workspace.query.filter_by(owner_id=user_id).first()
        if not default_workspace:
            default_workspace = Workspace(
                owner_id=user_id,
                name="Meu Workspace",
                description="Workspace padrão",
                color="#3b82f6",
            )
            db.session.add(default_workspace)
            db.session.commit()

        session["active_workspace_id"] = default_workspace.id
        workspace_id = default_workspace.id

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return _json({"error": "Sem permissão"}, 403)

    ws = Workspace.query.get(workspace_id) if workspace_id else None
    include_legacy = bool(ws and ws.owner_id == user_id)

    today = datetime.utcnow().date()
    try:
        selected_month = int(request.args.get("month", today.month))
        selected_year = int(request.args.get("year", today.year))
        if selected_month < 1 or selected_month > 12:
            selected_month = today.month
        if selected_year < 2000 or selected_year > 2100:
            selected_year = today.year
    except Exception:
        selected_month = today.month
        selected_year = today.year

    from calendar import monthrange
    month_start = date(selected_year, selected_month, 1)
    month_end = date(selected_year, selected_month, monthrange(selected_year, selected_month)[1])

    totals_row = (
        db.session.query(
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                Transaction.type == "income",
                                Transaction.transaction_date <= month_end,
                            ),
                            Transaction.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("total_income"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                Transaction.type == "expense",
                                Transaction.transaction_date <= month_end,
                            ),
                            Transaction.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("total_expense"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                Transaction.type == "income",
                                Transaction.transaction_date >= month_start,
                                Transaction.transaction_date <= month_end,
                            ),
                            Transaction.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("monthly_income"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                Transaction.type == "expense",
                                Transaction.transaction_date >= month_start,
                                Transaction.transaction_date <= month_end,
                            ),
                            Transaction.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("monthly_expense"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                Transaction.type == "expense",
                                Transaction.is_closed == True,
                                Transaction.transaction_date >= month_start,
                                Transaction.transaction_date <= month_end,
                            ),
                            Transaction.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("monthly_paid_expense"),
        )
        .filter(Transaction.workspace_id == workspace_id)
        .one()
    )

    total_income = float(getattr(totals_row, "total_income", 0) or 0)
    total_expense = float(getattr(totals_row, "total_expense", 0) or 0)
    monthly_income = float(getattr(totals_row, "monthly_income", 0) or 0)
    monthly_expense = float(getattr(totals_row, "monthly_expense", 0) or 0)
    monthly_paid_expense = float(getattr(totals_row, "monthly_paid_expense", 0) or 0)

    balance = (total_income or 0) - (total_expense or 0)

    return _json({
        "balance": float(balance or 0),
        "monthly_income": float(monthly_income or 0),
        "monthly_expense": float(monthly_expense or 0),
        "monthly_paid_expense": float(monthly_paid_expense or 0),
        "year": selected_year,
        "month": selected_month,
    })


@gerenciamento_financeiro_bp.route("/select-workspace", methods=["GET"])
def select_workspace():
    """Tela de seleção obrigatória de workspace após login - SEM navbar."""
    if "finance_user_id" not in session:
        return redirect(url_for("gerenciamento_financeiro.login"))
    
    user_id = session["finance_user_id"]
    user = User.query.get(user_id)
    
    # Buscar workspaces próprios
    owned_workspaces = Workspace.query.filter_by(owner_id=user_id).all()
    owned_ids = {ws.id for ws in owned_workspaces}
    
    # Buscar workspaces compartilhados (excluindo os que o usuário é dono)
    shared_workspace_members = WorkspaceMember.query.filter_by(user_id=user_id).all()
    shared_workspaces = [
        member.workspace for member in shared_workspace_members 
        if member.workspace and member.workspace.id not in owned_ids
    ]
    
    _log_debug(f"[SELECT_WORKSPACE] user_id={user_id} owned_count={len(owned_workspaces)} shared_count={len(shared_workspaces)}")
    _log_debug(f"[SELECT_WORKSPACE] owned_ids={owned_ids}")
    
    return render_template(
        "workspace_selection_standalone.html",
        user=user,
        owned_workspaces=owned_workspaces,
        shared_workspaces=shared_workspaces
    )

@gerenciamento_financeiro_bp.route("/login", methods=["GET", "POST"])
def login():
    """Tela de login do módulo financeiro.

    Se a URL contiver o parâmetro accept_share_id, ao autenticar com sucesso o sistema
    tentará localizar um convite de compartilhamento pendente (SystemShare) para o
    mesmo email utilizado no login e, em caso positivo, marcará o convite como aceito.
    """

    if request.method == "GET" and "finance_user_id" in session:
        if session.get("active_workspace_id"):
            return redirect(url_for("gerenciamento_financeiro.home"))
        return redirect(url_for("gerenciamento_financeiro.select_workspace"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember_me = request.form.get("remember_me") or request.form.get("auto_login")

        if not email or not password:
            flash("Informe e-mail e senha.", "danger")
            return render_template("finance_login.html", user=None)

        user = User.query.filter(func.lower(User.email) == email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("E-mail ou senha inválidos.", "danger")
            _log_attempt(email, False, "Credenciais inválidas")
            return render_template("finance_login.html", user=None)

        # Autenticação bem-sucedida
        session.permanent = bool(remember_me)
        session["finance_user_id"] = user.id
        session["finance_user_email"] = user.email

        flash("Bem-vindo ao painel financeiro!", "success")
        _log_attempt(email, True, user_id=user.id)

        # Verificar se há convite de compartilhamento (SystemShare) a aceitar
        accept_share_id = request.args.get("accept_share_id")
        if accept_share_id and accept_share_id.isdigit():
            try:
                share_id_int = int(accept_share_id)
                share = SystemShare.query.get(share_id_int)

                if share and share.status == "pending" and share.shared_email.lower() == user.email.lower():
                    share.shared_user_id = user.id
                    share.status = "accepted"
                    share.accepted_at = datetime.utcnow()
                    db.session.commit()
                    flash("Convite de compartilhamento encontrado e aceito com sucesso!", "success")

                    try:
                        from flask import current_app
                        send_share_accepted(
                            owner_email=share.owner.email,
                            shared_email=user.email,
                            app=current_app,
                        )
                    except Exception as e:  # pragma: no cover
                        _log_exception(f"Erro ao enviar email de confirmação de compartilhamento: {e}")
            except Exception as e:
                db.session.rollback()
                _log_exception(f"Erro ao aceitar convite de compartilhamento no login: {e}")

        # Verificar se há convite de WORKSPACE (WorkspaceInvite) a aceitar via token
        accept_invite_token = request.args.get("accept_invite_token")
        if accept_invite_token:
            try:
                invite = WorkspaceInvite.query.filter_by(token=accept_invite_token).first()
                if invite and invite.status == "pending" and invite.expires_at > datetime.utcnow():
                    if invite.invited_email.lower() == user.email.lower() or invite.invited_user_id == user.id:
                        existing = WorkspaceMember.query.filter_by(
                            workspace_id=invite.workspace_id,
                            user_id=user.id,
                        ).first()

                        if not existing:
                            member = WorkspaceMember(
                                workspace_id=invite.workspace_id,
                                user_id=user.id,
                                role=invite.role,
                            )
                            db.session.add(member)

                        invite.status = "accepted"
                        invite.responded_at = datetime.utcnow()
                        invite.invited_user_id = user.id
                        db.session.commit()
                        flash("Convite de workspace aceito com sucesso!", "success")
            except Exception as e:
                db.session.rollback()
                _log_exception(f"Erro ao aceitar convite de workspace no login: {e}")

        response = make_response(redirect(url_for("gerenciamento_financeiro.select_workspace")))
        if remember_me:
            response.set_cookie(
                "finance_remember_email",
                user.email,
                max_age=60 * 60 * 24 * 30,
                samesite="Lax",
            )
        else:
            response.delete_cookie("finance_remember_email")
        return response

    remembered_email = request.cookies.get("finance_remember_email", "")
    return render_template("finance_login.html", user=None, remembered_email=remembered_email)


@gerenciamento_financeiro_bp.route("/invites/<string:token>", methods=["GET"])
def open_workspace_invite(token):
    """Link simples de convite. Se estiver logado, aceita; se não, redireciona para login."""
    _log_debug(f"[OPEN_INVITE] Token recebido: {token[:20]}...")
    
    if "finance_user_id" not in session:
        _log_debug("[OPEN_INVITE] Usuário não logado, redirecionando para login")
        return redirect(url_for("gerenciamento_financeiro.login", accept_invite_token=token))

    user_id = session["finance_user_id"]
    user = User.query.get(user_id)
    _log_debug(f"[OPEN_INVITE] Usuário logado: id={user_id} email={user.email}")

    try:
        invite = WorkspaceInvite.query.filter_by(token=token).first()
        if not invite:
            _log_debug("[OPEN_INVITE] Convite não encontrado para token")
            flash("Convite inválido.", "danger")
            return redirect(url_for("gerenciamento_financeiro.select_workspace"))

        _log_debug(f"[OPEN_INVITE] Convite encontrado: id={invite.id} status={invite.status} workspace_id={invite.workspace_id} invited_email={invite.invited_email}")

        if invite.status != "pending" or invite.expires_at < datetime.utcnow():
            _log_debug(f"[OPEN_INVITE] Convite expirado ou já usado: status={invite.status} expires={invite.expires_at}")
            flash("Convite expirado ou já utilizado.", "warning")
            return redirect(url_for("gerenciamento_financeiro.select_workspace"))

        if invite.invited_email.lower() != user.email.lower() and invite.invited_user_id not in (None, user.id):
            _log_debug(f"[OPEN_INVITE] Convite não é para este usuário: invited_email={invite.invited_email} user_email={user.email}")
            flash("Este convite não é para o seu usuário.", "danger")
            return redirect(url_for("gerenciamento_financeiro.select_workspace"))

        existing = WorkspaceMember.query.filter_by(workspace_id=invite.workspace_id, user_id=user.id).first()
        if not existing:
            member = WorkspaceMember(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role)
            db.session.add(member)
            _log_debug(f"[OPEN_INVITE] Novo membro criado: workspace_id={invite.workspace_id} user_id={user.id} role={invite.role}")
        else:
            _log_debug("[OPEN_INVITE] Usuário já é membro do workspace")

        invite.status = "accepted"
        invite.responded_at = datetime.utcnow()
        invite.invited_user_id = user.id
        db.session.commit()
        _log_debug("[OPEN_INVITE] Convite aceito com sucesso!")

        flash("Convite aceito! Agora você tem acesso ao workspace.", "success")
        return redirect(url_for("gerenciamento_financeiro.select_workspace"))

    except Exception as e:
        db.session.rollback()
        _log_exception(f"Erro ao aceitar convite por token: {e}")
        flash("Erro ao aceitar convite.", "danger")
        return redirect(url_for("gerenciamento_financeiro.select_workspace"))

@gerenciamento_financeiro_bp.route("/api/login", methods=["POST", "OPTIONS"])
@gerenciamento_financeiro_bp.route("/api/login/", methods=["POST", "OPTIONS"])
def api_login():
    """Endpoint de login para clientes API (ex: app Flutter).

    Recebe JSON {"email": "...", "password": "..."} e, em caso de sucesso,
    autentica o usuário na sessão (mesma lógica da tela HTML) e retorna JSON.
    """

    # Tratamento de CORS para Flutter Web / navegadores
    origin = request.headers.get("Origin", "*")

    # Pré-flight (OPTIONS)
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    remember_me = data.get("remember_me") or data.get("auto_login")

    _log_debug("[API LOGIN] Requisição recebida do APP_FIN")
    _log_debug(f"[API LOGIN] IP: {request.remote_addr}")
    _log_debug(f"[API LOGIN] User-Agent: {request.headers.get('User-Agent')}")
    _log_debug(f"[API LOGIN] Payload bruto: {data}")
    _log_debug(f"[API LOGIN] Email normalizado: {email!r}")

    if not email or not password:
        _log_debug("[API LOGIN] Falha: email ou senha vazios")
        resp = jsonify({
            "success": False,
            "message": "Informe e-mail e senha.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 400

    user = User.query.filter(func.lower(User.email) == email).first()

    if not user:
        _log_attempt(email, False, "Credenciais inválidas")
        resp = jsonify({
            "success": False,
            "message": "Credenciais inválidas.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401

    if not check_password_hash(user.password_hash, password):
        _log_attempt(email, False, "Credenciais inválidas")
        resp = jsonify({
            "success": False,
            "message": "Credenciais inválidas.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401

    # Autenticação bem-sucedida (mesma lógica da rota HTML)
    session.permanent = bool(remember_me)
    session["finance_user_id"] = user.id
    session["finance_user_email"] = user.email

    # Garantir que o usuário tenha pelo menos um workspace
    workspace_count = Workspace.query.filter_by(owner_id=user.id).count()
    if workspace_count == 0:
        default_workspace = Workspace(
            owner_id=user.id,
            name="Meu Workspace",
            description="Workspace padrão",
            color="#3b82f6",
        )
        db.session.add(default_workspace)
        db.session.commit()

    _log_attempt(email, True, user_id=user.id)

    _log_debug(f"[API LOGIN] Login bem-sucedido para email={email!r}, user_id={user.id}")

    resp = jsonify({
        "success": True,
        "message": "Login realizado com sucesso",
        "user": {
            "id": user.id,
            "email": user.email,
        },
    })
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp, 200

@gerenciamento_financeiro_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not email or not password:
            flash("Preencha todos os campos.", "danger")
            return render_template("finance_register.html", user=None)

        if "@" not in email:
            flash("E-mail inválido.", "danger")
            return render_template("finance_register.html", user=None)

        if password != confirm:
            flash("As senhas não coincidem.", "danger")
            return render_template("finance_register.html", user=None)

        if len(password) < 6:
            flash("Use uma senha com pelo menos 6 caracteres.", "danger")
            return render_template("finance_register.html", user=None)

        exists = User.query.filter(func.lower(User.email) == email).first()
        if exists:
            flash("Este e-mail já está cadastrado.", "warning")
            return render_template("finance_register.html", user=None)

        try:
            user = User(email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.flush()

            default_workspace = Workspace(
                owner_id=user.id,
                name="Meu Workspace",
                description="Workspace padrão",
                color="#3b82f6"
            )
            db.session.add(default_workspace)
            db.session.flush()

            verification_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            expires_at = datetime.utcnow() + timedelta(minutes=15)

            verification = EmailVerification(
                email=email,
                code=verification_code,
                expires_at=expires_at
            )
            db.session.add(verification)
            db.session.flush()

            from flask import current_app
            email_ok = send_verification_code(email, verification_code, current_app)
            if not email_ok:
                db.session.rollback()
                flash("Não foi possível enviar o código de verificação por e-mail. Tente novamente mais tarde.", "danger")
                return render_template("finance_register.html", user=None)

            db.session.commit()

            _ensure_default_categories(user.id)

            session['pending_verification_email'] = email
            session['pending_verification_user_id'] = user.id

            accept_share_id = request.args.get("accept_share_id")
            if accept_share_id:
                session['pending_share_id'] = accept_share_id

            flash("Conta criada! Verifique seu email e insira o código de 6 dígitos.", "success")
            return redirect(url_for("gerenciamento_financeiro.verify_email"))

        except Exception as e:
            db.session.rollback()
            _log_exception(f"Erro no cadastro/verificação de email: {e}")
            flash("Erro ao criar conta. Tente novamente.", "danger")
            return render_template("finance_register.html", user=None)

    return render_template("finance_register.html", user=None)

@gerenciamento_financeiro_bp.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    """Tela de verificação de email com código de 6 dígitos"""
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        email = session.get('pending_verification_email')
        user_id = session.get('pending_verification_user_id')
        
        if not email or not user_id:
            flash("Sessão expirada. Faça o cadastro novamente.", "danger")
            return redirect(url_for("gerenciamento_financeiro.register"))
        
        # Buscar código válido
        verification = EmailVerification.query.filter_by(
            email=email,
            code=code,
            is_used=False
        ).filter(EmailVerification.expires_at > datetime.utcnow()).first()
        
        if not verification:
            flash("Código inválido ou expirado.", "danger")
            return render_template("finance_verify_email.html", email=email)
        
        # Marcar código como usado
        verification.is_used = True
        
        # Marcar usuário como verificado
        user = User.query.get(user_id)
        user.is_email_verified = True
        db.session.commit()
        
        # Processar convite pendente se houver
        pending_share_id = session.get('pending_share_id')
        if pending_share_id and pending_share_id.isdigit():
            try:
                share = SystemShare.query.get(int(pending_share_id))
                if share and share.status == "pending" and share.shared_email.lower() == user.email.lower():
                    share.shared_user_id = user.id
                    share.status = "accepted"
                    share.accepted_at = datetime.utcnow()
                    db.session.commit()
                    
                    from flask import current_app
                    send_share_accepted(share.owner.email, user.email, current_app)
                    flash("Convite de compartilhamento aceito automaticamente!", "success")
            except Exception as e:
                _log_exception(f"Erro ao aceitar convite: {e}")
        
        # Limpar sessão
        session.pop('pending_verification_email', None)
        session.pop('pending_verification_user_id', None)
        session.pop('pending_share_id', None)
        
        flash("Email verificado com sucesso! Faça login para continuar.", "success")
        return redirect(url_for("gerenciamento_financeiro.login"))
    
    email = session.get('pending_verification_email')
    if not email:
        flash("Sessão expirada. Faça o cadastro novamente.", "danger")
        return redirect(url_for("gerenciamento_financeiro.register"))
    
    return render_template("finance_verify_email.html", email=email)

@gerenciamento_financeiro_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Tela de esqueci minha senha"""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        
        if not email:
            flash("Informe seu email.", "danger")
            return render_template("finance_forgot_password.html")
        
        user = User.query.filter(func.lower(User.email) == email).first()

        if not user:
            flash("Se este email estiver cadastrado, você receberá um link de recuperação.", "info")
            return redirect(url_for("gerenciamento_financeiro.login"))

        try:
            token = secrets.token_urlsafe(32)
            expires_at = datetime.utcnow() + timedelta(hours=1)

            reset = PasswordReset(
                user_id=user.id,
                token=token,
                expires_at=expires_at
            )
            db.session.add(reset)
            db.session.flush()

            from flask import current_app
            base_url = current_app.config.get('APP_BASE_URL', request.host_url.rstrip('/'))
            reset_link = f"{base_url}{url_for('gerenciamento_financeiro.reset_password', token=token)}"
            email_ok = send_password_reset(email, reset_link, current_app)
            if not email_ok:
                db.session.rollback()
                flash("Não foi possível enviar o e-mail de recuperação agora. Tente novamente mais tarde.", "danger")
                return render_template("finance_forgot_password.html")

            db.session.commit()
            flash("Link de recuperação enviado. Verifique seu email.", "success")
            return redirect(url_for("gerenciamento_financeiro.login"))

        except Exception as e:
            db.session.rollback()
            _log_exception(f"Erro ao solicitar recuperação de senha: {e}")
            flash("Não foi possível processar sua solicitação agora. Tente novamente.", "danger")
            return render_template("finance_forgot_password.html")
    
    return render_template("finance_forgot_password.html")

@gerenciamento_financeiro_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Tela de redefinição de senha"""
    # Verificar token
    reset = PasswordReset.query.filter_by(
        token=token,
        is_used=False
    ).filter(PasswordReset.expires_at > datetime.utcnow()).first()
    
    if not reset:
        flash("Link inválido ou expirado. Solicite um novo link de recuperação.", "danger")
        return redirect(url_for("gerenciamento_financeiro.forgot_password"))
    
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        
        if not password or len(password) < 6:
            flash("Use uma senha com pelo menos 6 caracteres.", "danger")
            return render_template("finance_reset_password.html", token=token)
        
        if password != confirm:
            flash("As senhas não coincidem.", "danger")
            return render_template("finance_reset_password.html", token=token)
        
        # Atualizar senha
        user = User.query.get(reset.user_id)
        user.password_hash = generate_password_hash(password)
        
        # Marcar token como usado
        reset.is_used = True
        db.session.commit()
        
        flash("Senha redefinida com sucesso! Faça login com sua nova senha.", "success")
        return redirect(url_for("gerenciamento_financeiro.login"))
    
    return render_template("finance_reset_password.html", token=token)

@gerenciamento_financeiro_bp.route("/shares")
def shares_dashboard():
    """Tela para visualizar compartilhamentos enviados e recebidos"""
    if "finance_user_id" not in session:
        return redirect(url_for("gerenciamento_financeiro.login", next=request.path))

    user_id = session["finance_user_id"]

    # Convites que EU enviei (sou o dono)
    sent_shares = (
        SystemShare.query
        .filter_by(owner_id=user_id)
        .order_by(SystemShare.created_at.desc())
        .all()
    )

    # Compartilhamentos em que EU sou o convidado (já aceitos)
    received_shares = (
        SystemShare.query
        .filter_by(shared_user_id=user_id)
        .order_by(SystemShare.accepted_at.desc())
        .all()
    )

    return render_template(
        "finance_shares.html",
        sent_shares=sent_shares,
        received_shares=received_shares,
    )

@gerenciamento_financeiro_bp.route("/logout")
def logout():
    session.pop("finance_user_id", None)
    session.pop("finance_user_email", None)
    flash("Você saiu do painel financeiro.", "info")
    return redirect(url_for("gerenciamento_financeiro.login"))

# ============================================================================
# API DE TRANSAÇÕES (CORRIGIDA) - COM CORS E SUPORTE A user_id NA QUERY
# ============================================================================

@gerenciamento_financeiro_bp.route("/api/transactions", methods=["GET", "POST", "OPTIONS"])
@gerenciamento_financeiro_bp.route("/api/transactions/", methods=["GET", "POST", "OPTIONS"])
def api_transactions():
    origin = request.headers.get("Origin", "*")

    def _json(payload, status=200):
        resp = jsonify(payload)
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return (resp, status) if status != 200 else resp

    # Pré-flight CORS
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    user_id: int | None = None

    # Tentar usar sessão Flask primeiro
    if "finance_user_id" in session:
        user_id = session["finance_user_id"]
    else:
        # Fallback para apps que não conseguem enviar cookies (Flutter Web)
        user_id = request.args.get("user_id", type=int)

    if not user_id:
        return _json({"error": "Não autorizado"}, 401)

    accessible_ids = _get_accessible_user_ids(user_id)
    
    # Obter workspace_id da sessão (obrigatório para API)
    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        # Tentar obter ou criar workspace padrão automaticamente
        default_workspace = Workspace.query.filter_by(owner_id=user_id).first()
        if not default_workspace:
            default_workspace = Workspace(
                owner_id=user_id,
                name="Meu Workspace",
                description="Workspace padrão",
                color="#3b82f6"
            )
            db.session.add(default_workspace)
            db.session.commit()
        
        # Definir workspace ativo na sessão
        session["active_workspace_id"] = default_workspace.id
        workspace_id = default_workspace.id

    # Permissão do usuário no workspace ativo
    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return _json({"error": "Sem permissão"}, 403)

    ws = Workspace.query.get(workspace_id) if workspace_id else None
    if not ws:
        return _json({"error": "Workspace não encontrado"}, 404)
    owner_id = ws.owner_id

    _ensure_default_categories(owner_id, workspace_id)
    owner_config = FinanceConfig.query.filter_by(user_id=owner_id).first()

    _ensure_transactions_subcategory_text_column()
    _ensure_recurring_subcategory_text_column()

    # Garantir que o workspace exista (sessão pode ficar com id inválido)
    if workspace_id and not Workspace.query.get(workspace_id):
        default_workspace = Workspace.query.filter_by(owner_id=user_id).first()
        if not default_workspace:
            default_workspace = Workspace(
                owner_id=user_id,
                name="Meu Workspace",
                description="Workspace padrão",
                color="#3b82f6",
            )
            db.session.add(default_workspace)
            db.session.commit()
        session["active_workspace_id"] = default_workspace.id
        workspace_id = default_workspace.id
    
    if request.method == "POST":
        try:
            if workspace_role == "viewer":
                return _json({"error": "Sem permissão para criar/editar/excluir (somente visualização)"}, 403)

            data = request.get_json()
            
            # Validação melhorada
            if not data:
                return _json({"error": "Dados não fornecidos"}, 400)
                
            description = data.get("description", "").strip()
            notes = data.get("notes")
            amount = data.get("amount")
            transaction_type = data.get("type", "").strip()
            frequency = data.get("frequency", "").strip()
            category_id = data.get("category_id")
            subcategory_text = data.get("subcategory_text")
            is_active = data.get("is_active", True)
            
            if not description:
                return _json({"error": "Descrição é obrigatória"}, 400)
            
            # Validar e converter amount
            try:
                import math
                amount = float(amount) if amount is not None and str(amount).strip() != "" else 0.0
                if (not math.isfinite(amount)) or amount <= 0:
                    return _json({"error": "Valor deve ser maior que zero"}, 400)
            except (ValueError, TypeError):
                return _json({"error": "Valor inválido"}, 400)

            # Validar e converter category_id (normalmente vem como string do <select>)
            try:
                category_id = int(category_id)
            except (ValueError, TypeError):
                return _json({"error": "Categoria inválida"}, 400)

            if subcategory_text is not None:
                subcategory_text = str(subcategory_text).strip()
                if not subcategory_text:
                    subcategory_text = None
            
            if not frequency:
                return _json({"error": "Frequência é obrigatória"}, 400)
            
            if not category_id or category_id <= 0:
                return _json({"error": "Categoria é obrigatória"}, 400)
                
            if transaction_type not in ['income', 'expense']:
                return _json({"error": "Tipo deve ser 'income' ou 'expense'"}, 400)

            # Validar se a categoria pertence ao workspace ativo
            if not owner_config:
                return _json({"error": "Configuração financeira não encontrada"}, 404)
            category = Category.query.filter_by(
                id=category_id,
                config_id=owner_config.id,
                workspace_id=workspace_id,
                is_active=True,
            ).first()
            if not category:
                return _json({"error": "Categoria não encontrada para este workspace"}, 404)

            
            
            # Validar e obter data da transação
            if data.get("transaction_date"):
                try:
                    transaction_date = datetime.strptime(data["transaction_date"], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    return _json({"error": "Data inválida. Use o formato YYYY-MM-DD"}, 400)
            else:
                transaction_date = date.today()
            
            is_recurring = data.get("is_recurring", False)
            
            # Se é recorrente, criar transações conforme duração especificada
            if is_recurring:
                from dateutil.relativedelta import relativedelta
                transactions_created = []
                
                # Determinar quantidade de meses
                fixed_duration_type = data.get("fixed_duration_type", "infinite")
                fixed_months = data.get("fixed_months")

                if fixed_duration_type == "months":
                    try:
                        num_months = int(fixed_months) if fixed_months else 12
                        num_months = max(1, min(num_months, 120))
                    except (ValueError, TypeError):
                        num_months = 12

                    recurring_source = None
                    try:
                        recurring_source = RecurringTransaction(
                            user_id=user_id,
                            category_id=category_id,
                            subcategory_id=None,
                            subcategory_text=subcategory_text,
                            description=description,
                            amount=float(amount),
                            type=transaction_type,
                            frequency="monthly",
                            day_of_month=transaction_date.day,
                            start_date=transaction_date,
                            end_date=(transaction_date + relativedelta(months=(num_months - 1))) if num_months else None,
                            is_active=False,
                            payment_method=None,
                            notes=notes,
                        )
                        db.session.add(recurring_source)
                        db.session.flush()
                    except Exception:
                        recurring_source = None

                    for month_offset in range(num_months):
                        new_date = transaction_date + relativedelta(months=month_offset)
                        installment_desc = f"{description} {month_offset + 1}/{num_months}"

                        transaction = Transaction(
                            user_id=user_id,
                            workspace_id=workspace_id,
                            description=installment_desc,
                            notes=notes,
                            amount=float(amount),
                            type=transaction_type,
                            category_id=category_id,
                            subcategory_id=None,
                            subcategory_text=subcategory_text,
                            transaction_date=new_date,
                            frequency=frequency,
                            is_recurring=True,
                            is_paid=True,
                            is_fixed=data.get("is_fixed", False),
                            recurring_transaction_id=(recurring_source.id if recurring_source else None),
                        )
                        db.session.add(transaction)
                        transactions_created.append(transaction)

                    db.session.commit()

                    resp = jsonify({
                        "message": f"Transações criadas com sucesso! Duração: {num_months} meses",
                        "created": len(transactions_created),
                        "duration_type": fixed_duration_type,
                        "duration_months": num_months
                    })
                    resp.headers["Access-Control-Allow-Origin"] = origin
                    resp.headers["Vary"] = "Origin"
                    resp.headers["Access-Control-Allow-Credentials"] = "true"
                    return resp

                recurring_source = RecurringTransaction(
                    user_id=user_id,
                    category_id=category_id,
                    subcategory_id=None,
                    subcategory_text=subcategory_text,
                    description=description,
                    amount=float(amount),
                    type=transaction_type,
                    frequency="monthly",
                    day_of_month=transaction_date.day,
                    start_date=transaction_date,
                    end_date=None,
                    is_active=True,
                    payment_method=None,
                    notes=notes,
                )
                db.session.add(recurring_source)
                db.session.flush()

                transaction = Transaction(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    description=description,
                    notes=notes,
                    amount=float(amount),
                    type=transaction_type,
                    category_id=category_id,
                    subcategory_id=None,
                    subcategory_text=subcategory_text,
                    transaction_date=transaction_date,
                    frequency=frequency,
                    is_recurring=True,
                    is_paid=True,
                    is_fixed=True,
                    recurring_transaction_id=recurring_source.id,
                )
                db.session.add(transaction)
                transactions_created.append(transaction)
                db.session.commit()

                category = Category.query.get(transaction.category_id) if transaction.category_id else None
                subcat = SubCategory.query.get(transaction.subcategory_id) if getattr(transaction, "subcategory_id", None) else None
                return _json({
                    "message": "Transação recorrente criada (sem fim definido)",
                    "created": len(transactions_created),
                    "duration_type": "infinite",
                    "id": transaction.id,
                    "description": transaction.description,
                    "notes": getattr(transaction, "notes", None),
                    "amount": float(transaction.amount),
                    "type": transaction.type,
                    "transaction_date": transaction.transaction_date.isoformat(),
                    "frequency": getattr(transaction, "frequency", "once"),
                    "is_recurring": getattr(transaction, "is_recurring", False),
                    "is_fixed": getattr(transaction, "is_fixed", False),
                    "recurring_transaction_id": getattr(transaction, "recurring_transaction_id", None),
                    "subcategory_text": getattr(transaction, "subcategory_text", None) or (subcat.name if subcat else None),
                    "category": {
                        "id": category.id,
                        "name": category.name,
                        "icon": category.icon,
                        "color": category.color,
                    } if category else None,
                    "subcategory": {
                        "id": subcat.id,
                        "name": subcat.name,
                        "icon": subcat.icon,
                        "color": subcat.color,
                    } if subcat else None,
                }, 200)
                
            else:
                # Transação única
                transaction = Transaction(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    description=description,
                    notes=notes,
                    amount=float(amount),
                    type=transaction_type,
                    category_id=category_id,
                    subcategory_id=None,
                    subcategory_text=subcategory_text,
                    transaction_date=transaction_date,
                    frequency=frequency,
                    is_recurring=False,
                    is_paid=True,
                    is_fixed=data.get("is_fixed", False)
                )
                
                db.session.add(transaction)
                db.session.commit()

                category = Category.query.get(transaction.category_id) if transaction.category_id else None
                subcat = SubCategory.query.get(transaction.subcategory_id) if getattr(transaction, "subcategory_id", None) else None
                return _json({
                    "message": "Transação criada com sucesso!",
                    "id": transaction.id,
                    "description": transaction.description,
                    "notes": getattr(transaction, "notes", None),
                    "amount": float(transaction.amount),
                    "type": transaction.type,
                    "transaction_date": transaction.transaction_date.isoformat(),
                    "frequency": getattr(transaction, "frequency", "once"),
                    "is_recurring": getattr(transaction, "is_recurring", False),
                    "is_fixed": getattr(transaction, "is_fixed", False),
                    "recurring_transaction_id": getattr(transaction, "recurring_transaction_id", None),
                    "subcategory_text": getattr(transaction, "subcategory_text", None) or (subcat.name if subcat else None),
                    "category": {
                        "id": category.id,
                        "name": category.name,
                        "icon": category.icon,
                        "color": category.color,
                    } if category else None,
                    "subcategory": {
                        "id": subcat.id,
                        "name": subcat.name,
                        "icon": subcat.icon,
                        "color": subcat.color,
                    } if subcat else None,
                }, 200)
            
        except ValueError as ve:
            db.session.rollback()
            return _json({"error": f"Erro de validação: {str(ve)}"}, 400)
        except Exception as e:
            db.session.rollback()
            _log_exception(f"Erro ao criar transação: {e}")
            return _json({"error": f"Erro interno do servidor: {str(e)}"}, 500)
    
    else:  # GET
        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 10))
            limit = request.args.get("limit", type=int)  # Limite opcional (ignora paginação)
            transaction_type = request.args.get("type")
            category_id = request.args.get("category_id")
            start_date = request.args.get("start_date")
            end_date = request.args.get("end_date")
            
            # Filtro por mês/ano específico
            filter_year = request.args.get("year", type=int)
            filter_month = request.args.get("month", type=int)

            try:
                if filter_year and filter_month:
                    _ensure_recurring_transactions_for_month(workspace_id=workspace_id, year=filter_year, month=filter_month)
                else:
                    today = datetime.utcnow().date()
                    _ensure_recurring_transactions_for_month(workspace_id=workspace_id, year=today.year, month=today.month)
            except Exception:
                pass
            
            # Filtrar por workspace ativo
            query = Transaction.query.options(joinedload(Transaction.category), joinedload(Transaction.subcategory)).filter_by(workspace_id=workspace_id)
            
            if transaction_type:
                query = query.filter_by(type=transaction_type)
            if category_id:
                query = query.filter_by(category_id=category_id)
            
            # Filtro por mês/ano (prioridade sobre start_date/end_date)
            if filter_year and filter_month:
                from calendar import monthrange
                first_day = date(filter_year, filter_month, 1)
                last_day = date(filter_year, filter_month, monthrange(filter_year, filter_month)[1])
                query = query.filter(Transaction.transaction_date >= first_day)
                query = query.filter(Transaction.transaction_date <= last_day)
            else:
                if start_date:
                    query = query.filter(Transaction.transaction_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
                if end_date:
                    query = query.filter(Transaction.transaction_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
            
            query = query.order_by(Transaction.transaction_date.desc())
            
            # Se limit foi especificado, usar limit ao invés de paginação
            if limit:
                transactions_list = query.limit(limit).all()
                resp = jsonify({
                    "transactions": [{
                        "id": t.id,
                        "description": t.description,
                        "notes": getattr(t, 'notes', None),
                        "amount": float(t.amount),
                        "type": t.type,
                        "transaction_date": t.transaction_date.isoformat(),
                        "frequency": getattr(t, 'frequency', 'once'),
                        "is_recurring": getattr(t, 'is_recurring', False),
                        "is_fixed": getattr(t, 'is_fixed', False),
                        "is_closed": getattr(t, 'is_closed', False),
                        "proof_document_url": getattr(t, 'proof_document_url', None),
                        "recurring_transaction_id": getattr(t, 'recurring_transaction_id', None),
                        "subcategory_text": getattr(t, 'subcategory_text', None) or (t.subcategory.name if t.subcategory else None),
                        "category": {
                            "id": t.category.id,
                            "name": t.category.name,
                            "icon": t.category.icon,
                            "color": t.category.color
                        } if t.category else None,
                        "subcategory": {
                            "id": t.subcategory.id,
                            "name": t.subcategory.name,
                            "icon": t.subcategory.icon,
                            "color": t.subcategory.color,
                        } if t.subcategory else None
                    } for t in transactions_list],
                    "total": len(transactions_list)
                })
            else:
                transactions = query.paginate(
                    page=page, 
                    per_page=per_page, 
                    error_out=False
                )
                
                resp = jsonify({
                    "transactions": [{
                        "id": t.id,
                        "description": t.description,
                        "notes": getattr(t, 'notes', None),
                        "amount": float(t.amount),
                        "type": t.type,
                        "transaction_date": t.transaction_date.isoformat(),
                        "frequency": getattr(t, 'frequency', 'once'),
                        "is_recurring": getattr(t, 'is_recurring', False),
                        "is_fixed": getattr(t, 'is_fixed', False),
                        "is_closed": getattr(t, 'is_closed', False),
                        "proof_document_url": getattr(t, 'proof_document_url', None),
                        "recurring_transaction_id": getattr(t, 'recurring_transaction_id', None),
                        "subcategory_text": getattr(t, 'subcategory_text', None) or (t.subcategory.name if t.subcategory else None),
                        "category": {
                            "id": t.category.id,
                            "name": t.category.name,
                            "icon": t.category.icon,
                            "color": t.category.color
                        } if t.category else None,
                        "subcategory": {
                            "id": t.subcategory.id,
                            "name": t.subcategory.name,
                            "icon": t.subcategory.icon,
                            "color": t.subcategory.color,
                        } if t.subcategory else None
                    } for t in transactions.items],
                    "pagination": {
                        "page": transactions.page,
                        "pages": transactions.pages,
                        "per_page": transactions.per_page,
                        "total": transactions.total,
                        "has_next": transactions.has_next,
                        "has_prev": transactions.has_prev
                    }
                })
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp
            
        except Exception as e:
            _log_exception(f"Erro ao buscar transações: {e}")
            resp = jsonify({"error": "Erro ao buscar transações"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 500

@gerenciamento_financeiro_bp.route("/api/transactions/<int:transaction_id>", methods=["GET", "PUT", "DELETE"])
def api_transaction_detail(transaction_id):
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
        
    user_id = session["finance_user_id"]

    origin = request.headers.get("Origin", "*")

    def _json(payload, status=200):
        resp = jsonify(payload)
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return (resp, status) if status != 200 else resp

    # Se existir workspace ativo, filtrar por ele também
    workspace_id = session.get("active_workspace_id")

    if not workspace_id:
        return _json({"error": "Workspace não selecionado"}, 400)

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return _json({"error": "Sem permissão"}, 403)

    # Obter owner_config do workspace para validações de categoria/subcategoria
    ws = Workspace.query.get(workspace_id)
    if not ws:
        return _json({"error": "Workspace não encontrado"}, 404)
    owner_id = ws.owner_id
    owner_config = FinanceConfig.query.filter_by(user_id=owner_id).first()

    # A partir daqui, transações são do workspace (não do criador)
    transaction = Transaction.query.filter_by(id=transaction_id, workspace_id=workspace_id).first()
    
    if not transaction:
        return _json({"error": "Transação não encontrada"}, 404)
    
    if request.method == "GET":
        category = Category.query.get(transaction.category_id) if transaction.category_id else None
        subcat = SubCategory.query.get(transaction.subcategory_id) if getattr(transaction, "subcategory_id", None) else None
        return _json({
            "transaction": {
                "id": transaction.id,
                "description": transaction.description,
                "notes": getattr(transaction, "notes", None),
                "amount": float(transaction.amount),
                "type": transaction.type,
                "transaction_date": transaction.transaction_date.isoformat(),
                "frequency": getattr(transaction, 'frequency', 'once'),
                "is_recurring": getattr(transaction, 'is_recurring', False),
                "is_fixed": getattr(transaction, 'is_fixed', False),
                "is_closed": getattr(transaction, 'is_closed', False),
                "proof_document_url": getattr(transaction, 'proof_document_url', None),
                "recurring_transaction_id": getattr(transaction, 'recurring_transaction_id', None),
                "subcategory_text": getattr(transaction, "subcategory_text", None) or (subcat.name if subcat else None),
                "category": {
                    "id": category.id,
                    "name": category.name,
                    "icon": category.icon,
                    "color": category.color,
                } if category else None,
                "subcategory": {
                    "id": subcat.id,
                    "name": subcat.name,
                    "icon": subcat.icon,
                    "color": subcat.color,
                } if subcat else None,
            }
        })

    if request.method == "PUT":
        try:
            if workspace_role == "viewer":
                return _json({"error": "Sem permissão para editar (somente visualização)"}, 403)

            data = request.get_json() or {}

            apply_scope = (data or {}).get("apply_scope") or "single"
            apply_scope = str(apply_scope).lower().strip() if apply_scope else "single"

            amount_value = None
            if "amount" in data:
                try:
                    amount_value = float(data.get("amount"))
                except (TypeError, ValueError):
                    return _json({"error": "Valor inválido"}, 400)

            category_id = None
            if "category_id" in data:
                if data.get("category_id") in (None, "", 0, "0"):
                    category_id = None
                else:
                    try:
                        category_id = int(data.get("category_id"))
                    except (TypeError, ValueError):
                        return _json({"error": "Categoria inválida"}, 400)

                if category_id is not None:
                    if not owner_config:
                        return _json({"error": "Configuração financeira não encontrada"}, 404)
                    category = Category.query.filter_by(
                        id=category_id,
                        config_id=owner_config.id,
                        workspace_id=workspace_id,
                        is_active=True,
                    ).first()
                    if not category:
                        return _json({"error": "Categoria não encontrada para este workspace"}, 404)

            subcategory_text = None
            if "subcategory_text" in data:
                subcategory_text = data.get("subcategory_text")
                if subcategory_text is not None:
                    subcategory_text = str(subcategory_text).strip()
                    if not subcategory_text:
                        subcategory_text = None

            if apply_scope == "series" and getattr(transaction, "recurring_transaction_id", None):
                series_id = transaction.recurring_transaction_id
                series_transactions = (
                    Transaction.query
                    .filter_by(workspace_id=workspace_id, recurring_transaction_id=series_id)
                    .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
                    .all()
                )

                updated = 0
                total = len(series_transactions)
                new_base_desc = None
                if "description" in data and data.get("description") is not None:
                    new_base_desc = str(data.get("description") or "").strip()
                    new_base_desc = re.sub(r"\s*\d+/\d+\s*$", "", new_base_desc).strip()

                for i, tx in enumerate(series_transactions):
                    if "description" in data:
                        if new_base_desc:
                            m = re.search(r"(\d+/\d+)\s*$", str(tx.description or ""))
                            suffix = m.group(1) if m else None
                            if not suffix:
                                suffix = f"{i + 1}/{total}" if total else ""
                            tx.description = f"{new_base_desc} {suffix}".strip()
                    if "notes" in data:
                        tx.notes = data["notes"]
                    if "amount" in data:
                        tx.amount = amount_value
                    if "category_id" in data:
                        tx.category_id = category_id
                    if "subcategory_text" in data:
                        tx.subcategory_id = None
                        tx.subcategory_text = subcategory_text
                    updated += 1

                db.session.commit()

                resp = jsonify({
                    "message": "Parcelas atualizadas com sucesso!",
                    "updated_count": updated,
                })
                resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                return resp
            
            if "description" in data:
                transaction.description = data["description"]
            if "notes" in data:
                transaction.notes = data["notes"]
            if "amount" in data:
                transaction.amount = amount_value
            if "transaction_date" in data:
                transaction.transaction_date = datetime.strptime(data["transaction_date"], "%Y-%m-%d").date()
            if "frequency" in data:
                transaction.frequency = data["frequency"]
            if "is_recurring" in data:
                transaction.is_recurring = bool(data["is_recurring"])
            if "is_fixed" in data:
                transaction.is_fixed = bool(data["is_fixed"])
            if "category_id" in data:
                transaction.category_id = category_id
            if "subcategory_text" in data:
                transaction.subcategory_id = None
                transaction.subcategory_text = subcategory_text
            if "is_paid" in data:
                transaction.is_paid = bool(data["is_paid"])
            if "paid_date" in data and data["paid_date"]:
                transaction.paid_date = datetime.strptime(data["paid_date"], "%Y-%m-%d").date()
            
            db.session.commit()

            category = Category.query.get(transaction.category_id) if transaction.category_id else None
            subcat = SubCategory.query.get(transaction.subcategory_id) if getattr(transaction, "subcategory_id", None) else None
            resp = jsonify({
                "message": "Transação atualizada com sucesso!",
                "id": transaction.id,
                "description": transaction.description,
                "notes": getattr(transaction, 'notes', None),
                "amount": float(transaction.amount),
                "type": transaction.type,
                "transaction_date": transaction.transaction_date.isoformat(),
                "frequency": getattr(transaction, 'frequency', 'once'),
                "is_recurring": getattr(transaction, 'is_recurring', False),
                "is_fixed": getattr(transaction, 'is_fixed', False),
                "recurring_transaction_id": getattr(transaction, 'recurring_transaction_id', None),
                "subcategory_text": getattr(transaction, 'subcategory_text', None) or (subcat.name if subcat else None),
                "category": {
                    "id": category.id,
                    "name": category.name,
                    "icon": category.icon,
                    "color": category.color,
                } if category else None,
                "subcategory": {
                    "id": subcat.id,
                    "name": subcat.name,
                    "icon": subcat.icon,
                    "color": subcat.color,
                } if subcat else None,
            })
            resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp
            
        except Exception as e:
            db.session.rollback()
            return _json({"error": str(e)}, 500)

    if request.method == "DELETE":
        try:
            if workspace_role == "viewer":
                return _json({"error": "Sem permissão para excluir (somente visualização)"}, 403)

            apply_scope = (request.args.get("apply_scope") or "single").strip().lower()
            if apply_scope == "series" and getattr(transaction, "recurring_transaction_id", None):
                series_id = int(transaction.recurring_transaction_id)

                deleted_count = (
                    Transaction.query
                    .filter_by(workspace_id=workspace_id, recurring_transaction_id=series_id)
                    .delete(synchronize_session=False)
                )

                try:
                    rt = RecurringTransaction.query.get(series_id)
                    if rt:
                        rt.is_active = False
                except Exception:
                    pass

                db.session.commit()
                return _json({
                    "message": "Recorrência excluída com sucesso",
                    "apply_scope": "series",
                    "recurring_transaction_id": series_id,
                    "deleted_count": int(deleted_count or 0),
                }, 200)

            if apply_scope == "single" and getattr(transaction, "recurring_transaction_id", None):
                try:
                    _ensure_recurring_exclusions_table()
                    series_id = int(transaction.recurring_transaction_id)
                    tx_date = transaction.transaction_date

                    dialect = getattr(db.engine, "dialect", None)
                    dialect_name = getattr(dialect, "name", "") if dialect else ""
                    if dialect_name == "postgresql":
                        sql = (
                            "INSERT INTO recurring_transaction_exclusions (workspace_id, recurring_transaction_id, transaction_date) "
                            "VALUES (:ws, :rid, :dt) "
                            "ON CONFLICT (workspace_id, recurring_transaction_id, transaction_date) DO NOTHING"
                        )
                    else:
                        sql = (
                            "INSERT OR IGNORE INTO recurring_transaction_exclusions (workspace_id, recurring_transaction_id, transaction_date) "
                            "VALUES (:ws, :rid, :dt)"
                        )
                    db.session.execute(text(sql), {"ws": workspace_id, "rid": series_id, "dt": tx_date})
                except Exception:
                    pass

            db.session.delete(transaction)
            db.session.commit()
            return _json({"message": "Transação excluída com sucesso", "id": transaction_id, "apply_scope": "single"}, 200)
        except Exception as e:
            db.session.rollback()
            return _json({"error": str(e)}, 500)

    return _json({"error": "Método não suportado"}, 405)

@gerenciamento_financeiro_bp.route("/api/expenses/close", methods=["POST", "OPTIONS"])
def api_close_expense():
    """Fecha uma despesa e opcionalmente anexa um comprovante."""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    origin = request.headers.get("Origin", "*")

    def _json(payload, status=200):
        resp = jsonify(payload)
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return (resp, status) if status != 200 else resp

    if request.method == "OPTIONS":
        return _json({}, 200)

    _ensure_transactions_close_columns()

    # Verificar workspace ativo
    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        return _json({"error": "Workspace não selecionado"}, 400)

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return _json({"error": "Sem permissão"}, 403)

    if workspace_role == "viewer":
        return _json({"error": "Sem permissão para fechar despesa (somente visualização)"}, 403)

    try:
        transaction_id = int(request.form.get("transaction_id"))
        close_notes = request.form.get("close_notes", "")
        
        # Obter transação
        transaction = Transaction.query.filter_by(
            id=transaction_id, 
            workspace_id=workspace_id,
            type="expense"
        ).first()
        
        if not transaction:
            return _json({"error": "Despesa não encontrada"}, 404)
        
        if transaction.is_closed:
            return _json({"error": "Despesa já foi fechada"}, 400)
        
        # Processar upload do comprovante (armazenar no banco; máximo 1MB)
        proof_document_url = None
        proof_document_data = None
        proof_document_name = None
        proof_document_storage_name = None
        proof_document_mime = None
        proof_document_size = None
        if "proof_document" in request.files:
            file = request.files["proof_document"]
            if file and file.filename:
                # Validar arquivo
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'}
                if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
                    return _json({"error": "Tipo de arquivo não permitido"}, 400)

                file.stream.seek(0, os.SEEK_END)
                file_size = file.stream.tell()
                file.stream.seek(0)
                if file_size > 1024 * 1024:
                    return _json({"error": "Arquivo excede o limite de 1MB"}, 400)

                # Gerar nome único
                import uuid
                from werkzeug.utils import secure_filename
                filename = secure_filename(file.filename)
                unique_filename = f"expense_proof_{transaction_id}_{uuid.uuid4().hex[:8]}_{filename}"

                proof_document_data = file.read()
                proof_document_name = filename
                proof_document_storage_name = unique_filename
                proof_document_mime = getattr(file, "mimetype", None)
                proof_document_size = int(file_size)

                # Gerar URL relativa (serve do banco)
                proof_document_url = f"/gerenciamento-financeiro/uploads/expense_proofs/{unique_filename}"
        
        # Atualizar transação
        transaction.is_closed = True
        transaction.closed_date = date.today()
        transaction.closed_by_user_id = user_id
        transaction.proof_document_url = proof_document_url
        transaction.proof_document_data = proof_document_data
        transaction.proof_document_name = proof_document_name
        transaction.proof_document_storage_name = proof_document_storage_name
        transaction.proof_document_mime = proof_document_mime
        transaction.proof_document_size = proof_document_size
        
        if close_notes:
            transaction.notes = f"{transaction.notes or ''}\n\n[Fechamento: {close_notes}]".strip()
        
        db.session.commit()
        
        return _json({
            "message": "Despesa fechada com sucesso!",
            "transaction_id": transaction.id,
            "closed_date": transaction.closed_date.isoformat(),
            "proof_document_url": proof_document_url
        })
        
    except ValueError:
        return _json({"error": "ID de transação inválido"}, 400)
    except Exception as e:
        db.session.rollback()
        return _json({"error": str(e)}, 500)


@gerenciamento_financeiro_bp.route("/api/expenses/reopen", methods=["POST", "OPTIONS"])
def api_reopen_expense():
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401

    user_id = session["finance_user_id"]
    origin = request.headers.get("Origin", "*")

    def _json(payload, status=200):
        resp = jsonify(payload)
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return (resp, status) if status != 200 else resp

    if request.method == "OPTIONS":
        return _json({}, 200)

    _ensure_transactions_close_columns()

    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        return _json({"error": "Workspace não selecionado"}, 400)

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return _json({"error": "Sem permissão"}, 403)

    if workspace_role == "viewer":
        return _json({"error": "Sem permissão para reabrir despesa (somente visualização)"}, 403)

    try:
        payload = request.get_json(silent=True) or {}
        transaction_id = int(payload.get("transaction_id"))

        transaction = Transaction.query.filter_by(
            id=transaction_id,
            workspace_id=workspace_id,
            type="expense",
        ).first()

        if not transaction:
            return _json({"error": "Despesa não encontrada"}, 404)

        if not getattr(transaction, "is_closed", False):
            return _json({"error": "Despesa já está aberta"}, 400)

        transaction.is_closed = False
        transaction.closed_date = None
        transaction.closed_by_user_id = None
        transaction.proof_document_url = None
        transaction.proof_document_data = None
        transaction.proof_document_name = None
        transaction.proof_document_storage_name = None
        transaction.proof_document_mime = None
        transaction.proof_document_size = None

        db.session.commit()

        return _json({
            "message": "Despesa reaberta com sucesso!",
            "transaction_id": transaction.id,
            "is_closed": False,
            "proof_document_url": getattr(transaction, "proof_document_url", None),
        })

    except ValueError:
        return _json({"error": "ID de transação inválido"}, 400)
    except Exception as e:
        db.session.rollback()
        return _json({"error": str(e)}, 500)


@gerenciamento_financeiro_bp.route("/api/expenses/proof", methods=["POST", "OPTIONS"])
def api_update_expense_proof():
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401

    user_id = session["finance_user_id"]
    origin = request.headers.get("Origin", "*")

    def _json(payload, status=200):
        resp = jsonify(payload)
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return (resp, status) if status != 200 else resp

    if request.method == "OPTIONS":
        return _json({}, 200)

    _ensure_transactions_close_columns()

    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        return _json({"error": "Workspace não selecionado"}, 400)

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return _json({"error": "Sem permissão"}, 403)

    if workspace_role == "viewer":
        return _json({"error": "Sem permissão para atualizar comprovante (somente visualização)"}, 403)

    try:
        transaction_id = int(request.form.get("transaction_id"))

        transaction = Transaction.query.filter_by(
            id=transaction_id,
            workspace_id=workspace_id,
            type="expense",
        ).first()

        if not transaction:
            return _json({"error": "Despesa não encontrada"}, 404)

        if "proof_document" not in request.files:
            return _json({"error": "Arquivo não enviado"}, 400)

        file = request.files["proof_document"]
        if not file or not file.filename:
            return _json({"error": "Arquivo inválido"}, 400)

        allowed_extensions = {"png", "jpg", "jpeg", "gif", "pdf", "doc", "docx"}
        if not ("." in file.filename and file.filename.rsplit(".", 1)[1].lower() in allowed_extensions):
            return _json({"error": "Tipo de arquivo não permitido"}, 400)

        file.stream.seek(0, os.SEEK_END)
        file_size = file.stream.tell()
        file.stream.seek(0)
        if file_size > 1024 * 1024:
            return _json({"error": "Arquivo excede o limite de 1MB"}, 400)

        import uuid
        from werkzeug.utils import secure_filename

        filename = secure_filename(file.filename)
        unique_filename = f"expense_proof_{transaction_id}_{uuid.uuid4().hex[:8]}_{filename}"

        proof_document_data = file.read()
        proof_document_url = f"/gerenciamento-financeiro/uploads/expense_proofs/{unique_filename}"

        transaction.proof_document_url = proof_document_url
        transaction.proof_document_data = proof_document_data
        transaction.proof_document_name = filename
        transaction.proof_document_storage_name = unique_filename
        transaction.proof_document_mime = getattr(file, "mimetype", None)
        transaction.proof_document_size = int(file_size)
        if getattr(transaction, "is_closed", False):
            transaction.closed_by_user_id = user_id

        db.session.commit()

        return _json({
            "message": "Comprovante atualizado com sucesso!",
            "transaction_id": transaction.id,
            "proof_document_url": proof_document_url,
        })

    except ValueError:
        return _json({"error": "ID de transação inválido"}, 400)
    except Exception as e:
        db.session.rollback()
        return _json({"error": str(e)}, 500)

@gerenciamento_financeiro_bp.route("/uploads/expense_proofs/<filename>")
def serve_expense_proof(filename):
    """Serve arquivos de comprovante de despesa."""
    try:
        if "finance_user_id" not in session:
            return "Não autorizado", 401

        user_id = session["finance_user_id"]
        _ensure_transactions_close_columns()

        transaction = Transaction.query.filter_by(proof_document_storage_name=filename).first()
        if not transaction or not getattr(transaction, "proof_document_data", None):
            return "Arquivo não encontrado", 404

        if transaction.workspace_id:
            workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=transaction.workspace_id)
            if not workspace_role:
                return "Sem permissão", 403

        mime = getattr(transaction, "proof_document_mime", None) or "application/octet-stream"
        download_name = getattr(transaction, "proof_document_name", None) or filename

        return send_file(
            BytesIO(transaction.proof_document_data),
            mimetype=mime,
            as_attachment=False,
            download_name=download_name,
        )
    except Exception as e:
        return f"Erro ao servir arquivo: {str(e)}", 500

@gerenciamento_financeiro_bp.route("/api/recurring", methods=["GET", "POST"])
def api_recurring():
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
        
    user_id = session["finance_user_id"]

    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        return jsonify({"error": "Workspace não selecionado"}), 400

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return jsonify({"error": "Sem permissão"}), 403

    ws = Workspace.query.get(workspace_id)
    if not ws:
        return jsonify({"error": "Workspace não encontrado"}), 404
    owner_id = ws.owner_id

    # Garantir categorias padrão do workspace (sempre no config do dono)
    _ensure_default_categories(owner_id, workspace_id)
    owner_config = FinanceConfig.query.filter_by(user_id=owner_id).first()

    if request.method == "POST":
        try:
            if workspace_role == "viewer":
                return jsonify({"error": "Sem permissão para criar/editar/excluir (somente visualização)"}), 403

            data = request.get_json()
            
            if not data:
                return jsonify({"error": "Dados não fornecidos"}), 400
                
            description = data.get("description", "").strip()
            amount = data.get("amount")
            transaction_type = data.get("type", "").strip()
            frequency = data.get("frequency", "").strip()
            day_of_month = data.get("day_of_month")
            day_of_week = data.get("day_of_week")
            start_date_str = data.get("start_date")
            end_date_str = data.get("end_date")
            category_id = data.get("category_id")
            payment_method = data.get("payment_method")
            notes = data.get("notes")
            is_active = data.get("is_active", True)
            
            if not description:
                return jsonify({"error": "Descrição é obrigatória"}), 400
                
            if not amount or amount <= 0:
                return jsonify({"error": "Valor deve ser maior que zero"}), 400
            
            if not frequency:
                return jsonify({"error": "Frequência é obrigatória"}), 400

            if frequency == "monthly" and not day_of_month:
                return jsonify({"error": "Dia do mês é obrigatório para frequência mensal"}), 400
            
            if frequency == "weekly" and not day_of_week:
                return jsonify({"error": "Dia da semana é obrigatório para frequência semanal"}), 400

            if not start_date_str:
                return jsonify({"error": "Data de início é obrigatória"}), 400

            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
                
            if transaction_type not in ['income', 'expense']:
                return jsonify({"error": "Tipo deve ser 'income' ou 'expense'"}), 400

            if not owner_config:
                return jsonify({"error": "Configuração financeira não encontrada"}), 404

            # Verificar se a categoria existe e pertence ao workspace
            if category_id:
                try:
                    category_id = int(category_id)
                except (ValueError, TypeError):
                    return jsonify({"error": "Categoria inválida"}), 400

                category = Category.query.filter_by(
                    id=category_id,
                    config_id=owner_config.id,
                    workspace_id=workspace_id,
                    is_active=True,
                ).first()
                if not category:
                    return jsonify({"error": "Categoria não encontrada para este workspace"}), 404
            else:
                category = Category.query.filter_by(
                    config_id=owner_config.id,
                    workspace_id=workspace_id,
                    type=transaction_type,
                    is_default=True,
                    is_active=True,
                ).first()
                if not category:
                    return jsonify({"error": "Categoria padrão não encontrada"}), 404
                category_id = category.id

            recurring_transaction = RecurringTransaction(
                user_id=user_id,
                description=description,
                amount=float(amount),
                type=transaction_type,
                category_id=category_id,
                frequency=frequency,
                day_of_month=day_of_month,
                day_of_week=day_of_week,
                start_date=start_date,
                end_date=end_date,
                is_active=is_active,
                payment_method=payment_method,
                notes=notes
            )
            
            db.session.add(recurring_transaction)
            db.session.commit()
            
            return jsonify({
                "message": "Lançamento fixo criado com sucesso!",
                "recurring_transaction": {
                    "id": recurring_transaction.id,
                    "description": recurring_transaction.description,
                    "amount": float(recurring_transaction.amount),
                    "type": recurring_transaction.type,
                    "frequency": recurring_transaction.frequency,
                    "start_date": recurring_transaction.start_date.isoformat()
                }
            }), 201
            

            
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/subcategories", methods=["GET", "POST"])
def api_subcategories():
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401

    user_id = session["finance_user_id"]
    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        return jsonify({"error": "Workspace não selecionado"}), 400

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return jsonify({"error": "Sem permissão"}), 403

    ws = Workspace.query.get(workspace_id)
    if not ws:
        return jsonify({"error": "Workspace não encontrado"}), 404

    owner_id = ws.owner_id
    _ensure_default_categories(owner_id, workspace_id)
    owner_config = FinanceConfig.query.filter_by(user_id=owner_id).first()
    if not owner_config:
        return jsonify({"error": "Configuração financeira não encontrada"}), 404

    if request.method == "POST":
        try:
            if workspace_role == "viewer":
                return jsonify({"error": "Sem permissão para criar/editar/excluir (somente visualização)"}), 403

            data = request.get_json() or {}
            name = str(data.get("name") or "").strip()
            category_id = data.get("category_id")

            if not name or not category_id:
                return jsonify({"error": "Campos obrigatórios: name, category_id"}), 400

            try:
                category_id = int(category_id)
            except (TypeError, ValueError):
                return jsonify({"error": "Categoria inválida"}), 400

            category = Category.query.filter_by(
                id=category_id,
                config_id=owner_config.id,
                workspace_id=workspace_id,
                is_active=True,
            ).first()
            if not category:
                return jsonify({"error": "Categoria não encontrada para este workspace"}), 404

            sub = SubCategory(
                config_id=owner_config.id,
                workspace_id=workspace_id,
                category_id=category_id,
                name=name,
                icon=data.get("icon"),
                color=data.get("color"),
                is_default=False,
                is_active=True,
            )
            db.session.add(sub)
            db.session.commit()

            return jsonify({
                "message": "Subcategoria criada com sucesso!",
                "subcategory": {
                    "id": sub.id,
                    "category_id": sub.category_id,
                    "name": sub.name,
                    "icon": sub.icon,
                    "color": sub.color,
                    "is_default": sub.is_default,
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    try:
        category_id = request.args.get("category_id", type=int)
        if not category_id:
            return jsonify({"error": "category_id é obrigatório"}), 400

        # Criar subcategorias padrão se não existirem
        _ensure_default_subcategories(category_id)

        # Buscar subcategorias
        subs = (
            SubCategory.query
            .filter_by(
                category_id=category_id,
                is_active=True,
            )
            .order_by(SubCategory.name.asc())
            .all()
        )

        return jsonify({
            "subcategories": [{
                "id": s.id,
                "category_id": s.category_id,
                "name": s.name,
                "icon": s.icon,
                "color": s.color,
                "is_default": s.is_default,
            } for s in subs]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/subcategories/<int:subcategory_id>", methods=["PUT", "DELETE"])
def api_subcategory_detail(subcategory_id: int):
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401

    user_id = session["finance_user_id"]
    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        return jsonify({"error": "Workspace não selecionado"}), 400

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return jsonify({"error": "Sem permissão"}), 403

    if workspace_role == "viewer":
        return jsonify({"error": "Sem permissão para criar/editar/excluir (somente visualização)"}), 403

    ws = Workspace.query.get(workspace_id)
    if not ws:
        return jsonify({"error": "Workspace não encontrado"}), 404

    owner_id = ws.owner_id
    owner_config = FinanceConfig.query.filter_by(user_id=owner_id).first()
    if not owner_config:
        return jsonify({"error": "Configuração financeira não encontrada"}), 404

    sub = SubCategory.query.filter_by(
        id=subcategory_id,
        config_id=owner_config.id,
        workspace_id=workspace_id,
        is_active=True,
    ).first()
    if not sub:
        return jsonify({"error": "Subcategoria não encontrada"}), 404

    if request.method == "PUT":
        try:
            data = request.get_json() or {}

            name = str(data.get("name") or "").strip()
            icon = data.get("icon")
            color = data.get("color")
            new_category_id = data.get("category_id")

            if name:
                sub.name = name
            if icon is not None:
                sub.icon = icon
            if color is not None:
                sub.color = color

            if new_category_id is not None:
                try:
                    new_category_id = int(new_category_id)
                except (TypeError, ValueError):
                    return jsonify({"error": "Categoria inválida"}), 400

                category = Category.query.filter_by(
                    id=new_category_id,
                    config_id=owner_config.id,
                    workspace_id=workspace_id,
                    is_active=True,
                ).first()
                if not category:
                    return jsonify({"error": "Categoria não encontrada para este workspace"}), 404

                sub.category_id = new_category_id

            db.session.commit()
            return jsonify({
                "message": "Subcategoria atualizada com sucesso!",
                "subcategory": {
                    "id": sub.id,
                    "category_id": sub.category_id,
                    "name": sub.name,
                    "icon": sub.icon,
                    "color": sub.color,
                    "is_default": sub.is_default,
                }
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    if getattr(sub, "is_default", False):
        return jsonify({"error": "Subcategorias padrão não podem ser excluídas"}), 400

    try:
        sub.is_active = False
        db.session.commit()
        return jsonify({"message": "Subcategoria excluída com sucesso"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    
    else:  # GET
        try:
            rtype = request.args.get("type")
            query = RecurringTransaction.query.filter_by(user_id=user_id, is_active=True)
            if rtype in ["income", "expense"]:
                query = query.filter_by(type=rtype)
            
            recurring_transactions = query.all()
            
            items = []
            for rt in recurring_transactions:
                category = None
                if rt.category_id:
                    category = Category.query.get(rt.category_id)
                
                items.append({
                    "id": rt.id,
                    "description": rt.description,
                    "amount": float(rt.amount),
                    "type": rt.type,
                    "day_of_month": rt.day_of_month,
                    "category": {
                        "id": category.id,
                        "name": category.name,
                        "icon": category.icon,
                        "color": category.color
                    } if category else None
                })
            
            return jsonify({"recurring_transactions": items})
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/categories/auto-icons", methods=["POST", "OPTIONS"])
def api_categories_auto_icons():
    origin = request.headers.get("Origin", "*")

    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401

    user_id = session["finance_user_id"]

    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        return jsonify({"error": "Workspace não selecionado"}), 400

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return jsonify({"error": "Sem permissão"}), 403

    if workspace_role == "viewer":
        return jsonify({"error": "Sem permissão para criar/editar/excluir (somente visualização)"}), 403

    ws = Workspace.query.get(workspace_id)
    if not ws:
        return jsonify({"error": "Workspace não encontrado"}), 404

    owner_id = ws.owner_id
    _ensure_default_categories(owner_id, workspace_id)
    config = FinanceConfig.query.filter_by(user_id=owner_id).first()
    if not config:
        return jsonify({"error": "Configuração financeira não encontrada"}), 404

    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

    data = request.get_json(silent=True) or {}
    category_type = str(data.get("type") or "").strip().lower()
    if category_type not in ["income", "expense"]:
        category_type = None

    force_all = bool(data.get("force"))

    base_query = Category.query.filter_by(
        config_id=config.id,
        workspace_id=workspace_id,
        is_active=True,
    )
    if category_type:
        base_query = base_query.filter_by(type=category_type)

    categories = base_query.order_by(Category.name.asc()).all()

    def _needs_icon(cat: Category) -> bool:
        icon_val = str(cat.icon or "").strip()
        if not icon_val:
            return True
        return icon_val in PLACEHOLDER_CATEGORY_ICONS

    eligible_categories = [c for c in categories if _needs_icon(c)]
    if force_all:
        cats = categories[:60]
    else:
        cats = eligible_categories[:60]

    if not cats:
        return jsonify({
            "message": "Nenhuma categoria com ícone padrão encontrada.",
            "updated": 0,
            "categories": [],
        })

    items = [{"id": str(c.id), "name": c.name, "type": c.type} for c in cats]

    try:
        mapping, notes = _fetch_ai_icon_mapping(
            user_id=user_id,
            items=items,
            context_label="Categorias do gerenciador financeiro",
        )
    except IconGenerationError as exc:
        return jsonify({"error": str(exc)}), 502

    updated = 0
    updated_items = []
    for c in cats:
        key = str(c.id)
        emoji = str((mapping.get(key) or mapping.get(c.id) or "")).strip()
        if not emoji:
            emoji = _fallback_icon_for_category(c.name, c.type)

        c.icon = emoji
        updated += 1
        updated_items.append({"id": c.id, "name": c.name, "type": c.type, "icon": c.icon})

    db.session.commit()
    suffix = " (forçado)" if force_all else ""
    return jsonify({
        "message": f"Ícones gerados/atualizados: {updated}{suffix}",
        "updated": updated,
        "notes": notes,
        "categories": updated_items,
    })

# ============================================================================
# API DE CATEGORIAS
# ============================================================================

@gerenciamento_financeiro_bp.route("/api/categories", methods=["GET", "POST"])
def api_categories():
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
        
    user_id = session["finance_user_id"]

    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        return jsonify({"error": "Workspace não selecionado"}), 400

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return jsonify({"error": "Sem permissão"}), 403

    ws = Workspace.query.get(workspace_id)
    if not ws:
        return jsonify({"error": "Workspace não encontrado"}), 404

    owner_id = ws.owner_id

    # Garantir categorias padrão do workspace (sempre no config do dono)
    _ensure_default_categories(owner_id, workspace_id)
    config = FinanceConfig.query.filter_by(user_id=owner_id).first()
    
    if request.method == "POST":
        try:
            if workspace_role == "viewer":
                return jsonify({"error": "Sem permissão para criar/editar/excluir (somente visualização)"}), 403

            data = request.get_json()
            
            if not data.get("name") or not data.get("type"):
                return jsonify({"error": "Campos obrigatórios: name, type"}), 400
            
            category = Category(
                config_id=config.id,
                workspace_id=workspace_id,
                name=data["name"],
                type=data["type"],
                icon=data.get("icon", "💰"),
                color=data.get("color", "#6366f1"),
                is_default=False,
                is_active=True
            )
            
            db.session.add(category)
            db.session.commit()
            
            return jsonify({
                "message": "Categoria criada com sucesso!",
                "category": {
                    "id": category.id,
                    "name": category.name,
                    "type": category.type,
                    "icon": category.icon,
                    "color": category.color
                }
            }), 201
            
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    else:  # GET
        try:
            category_type = request.args.get("type")
            
            query = Category.query.filter_by(config_id=config.id, workspace_id=workspace_id, is_active=True)
            
            if category_type:
                query = query.filter_by(type=category_type)
            
            categories = query.order_by(Category.name).all()
            
            return jsonify({
                "categories": [{
                    "id": c.id,
                    "name": c.name,
                    "type": c.type,
                    "icon": c.icon,
                    "color": c.color,
                    "is_default": c.is_default
                } for c in categories]
            })
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@gerenciamento_financeiro_bp.route("/api/categories/<int:category_id>", methods=["PUT", "DELETE"])
def api_category_detail(category_id: int):
    """Permite operações sobre uma categoria específica (atualmente apenas DELETE)."""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401

    user_id = session["finance_user_id"]

    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        return jsonify({"error": "Workspace não selecionado"}), 400

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return jsonify({"error": "Sem permissão"}), 403

    ws = Workspace.query.get(workspace_id)
    if not ws:
        return jsonify({"error": "Workspace não encontrado"}), 404

    owner_id = ws.owner_id

    # Garantir que existe config do dono
    _ensure_default_categories(owner_id, workspace_id)
    config = FinanceConfig.query.filter_by(user_id=owner_id).first()
    if not config:
        return jsonify({"error": "Configuração financeira não encontrada"}), 404

    category = Category.query.filter_by(id=category_id, config_id=config.id, workspace_id=workspace_id).first()
    if not category:
        return jsonify({"error": "Categoria não encontrada"}), 404

    if request.method == "PUT":
        if workspace_role == "viewer":
            return jsonify({"error": "Sem permissão para criar/editar/excluir (somente visualização)"}), 403

        try:
            data = request.get_json() or {}

            name = str(data.get("name") or "").strip()
            icon = data.get("icon")
            color = data.get("color")

            if name:
                category.name = name
            if icon is not None:
                category.icon = icon
            if color is not None:
                category.color = color

            db.session.commit()
            return jsonify({
                "message": "Categoria atualizada com sucesso!",
                "category": {
                    "id": category.id,
                    "name": category.name,
                    "type": category.type,
                    "icon": category.icon,
                    "color": category.color,
                    "is_default": category.is_default,
                }
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    if request.method == "DELETE":
        if workspace_role == "viewer":
            return jsonify({"error": "Sem permissão para criar/editar/excluir (somente visualização)"}), 403

        # Não permitir apagar categorias padrão
        if getattr(category, "is_default", False):
            return jsonify({"error": "Categorias padrão não podem ser excluídas"}), 400

        try:
            category.is_active = False
            db.session.commit()
            return jsonify({"message": "Categoria excluída com sucesso"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

# ============================================================================
# ENDPOINTS DE FECHAMENTO MENSAL
# ============================================================================


@gerenciamento_financeiro_bp.route("/api/monthly-closure/history", methods=["GET"])
def api_monthly_history():
    """Retorna histórico de fechamentos mensais"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        closures = MonthlyClosure.query.filter_by(
            user_id=user_id,
            status="closed"
        ).order_by(MonthlyClosure.year.desc(), MonthlyClosure.month.desc()).all()
        
        return jsonify({
            "closures": [{
                "id": c.id,
                "year": c.year,
                "month": c.month,
                "month_name": calendar.month_name[c.month],
                "status": c.status,
                "total_income": float(c.total_income),
                "total_expense": float(c.total_expense),
                "balance": float(c.balance),
                "closed_at": c.closed_at.isoformat() if c.closed_at else None,
                "created_at": c.created_at.isoformat()
            } for c in closures]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/monthly-closure/<int:closure_id>/details", methods=["GET"])
def api_closure_details(closure_id: int):
    """Retorna detalhes de um fechamento mensal específico"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        closure = MonthlyClosure.query.filter_by(
            id=closure_id,
            user_id=user_id
        ).first()
        
        if not closure:
            return jsonify({"error": "Fechamento não encontrado"}), 404
        
        # Buscar transações do mês
        month_start = date(closure.year, closure.month, 1)
        if closure.month == 12:
            month_end = date(closure.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(closure.year, closure.month + 1, 1) - timedelta(days=1)
        
        transactions = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end
        ).all()
        
        return jsonify({
            "closure": {
                "id": closure.id,
                "year": closure.year,
                "month": closure.month,
                "month_name": calendar.month_name[closure.month],
                "status": closure.status,
                "total_income": float(closure.total_income),
                "total_expense": float(closure.total_expense),
                "balance": float(closure.balance),
                "closed_at": closure.closed_at.isoformat() if closure.closed_at else None
            },
            "transactions": [{
                "id": t.id,
                "description": t.description,
                "amount": float(t.amount),
                "type": t.type,
                "transaction_date": t.transaction_date.isoformat(),
                "category": {
                    "id": t.category.id,
                    "name": t.category.name,
                    "icon": t.category.icon,
                    "color": t.category.color
                } if t.category else None,
                "is_fixed": t.is_fixed,
                "is_auto_loaded": t.is_auto_loaded
            } for t in transactions]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/monthly-closure/current", methods=["GET"])
def api_current_month_closure():
    """Retorna informações do mês atual (ou cria se não existir)"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        today = datetime.utcnow().date()
        year = today.year
        month = today.month
        
        # Buscar ou criar closure para mês atual
        closure = MonthlyClosure.query.filter_by(
            user_id=user_id,
            year=year,
            month=month
        ).first()
        
        if not closure:
            closure = MonthlyClosure(
                user_id=user_id,
                year=year,
                month=month,
                status="open"
            )
            db.session.add(closure)
            db.session.commit()
        
        return jsonify({
            "closure": {
                "id": closure.id,
                "year": closure.year,
                "month": closure.month,
                "month_name": calendar.month_name[closure.month],
                "status": closure.status,
                "total_income": float(closure.total_income),
                "total_expense": float(closure.total_expense),
                "balance": float(closure.balance),
                "is_last_day_of_month": today.day == calendar.monthrange(year, month)[1]
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================================
# ENDPOINTS DE COMPARTILHAMENTO DO SISTEMA
# ============================================================================

@gerenciamento_financeiro_bp.route("/api/system/share", methods=["POST", "OPTIONS"])
def api_share_system():
    """Compartilha o sistema com outro usuário via email"""
    origin = request.headers.get("Origin", "*")

    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    _log_debug(f"[SYSTEM SHARE] HIT path={request.path} method={request.method} user_id={session.get('finance_user_id')}")

    if "finance_user_id" not in session:
        _log_debug("[SYSTEM SHARE] 401 - finance_user_id ausente na sessão")
        resp = jsonify({"error": "Não autorizado"})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401
    
    user_id = session["finance_user_id"]
    data = request.get_json()
    
    if not data or not data.get("email"):
        _log_debug("[SYSTEM SHARE] 400 - payload inválido")
        resp = jsonify({"error": "Email é obrigatório"})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 400
    
    shared_email = data.get("email").lower().strip()
    share_type = data.get("share_type", "accountant")  # family ou accountant
    family_role = data.get("family_role")  # spouse, child, parent, other
    access_level = data.get("access_level", "viewer")  # viewer, editor, admin
    
    try:
        # Verificar se o email é válido
        if "@" not in shared_email:
            return jsonify({"error": "Email inválido"}), 400
        
        # Verificar se não está compartilhando com a mesma pessoa
        user = User.query.get(user_id)
        if user.email == shared_email:
            return jsonify({"error": "Você não pode compartilhar com você mesmo"}), 400
        
        # Verificar se já existe um compartilhamento pendente ou ativo
        existing_share = SystemShare.query.filter_by(
            owner_id=user_id,
            shared_email=shared_email
        ).first()
        
        if existing_share:
            if existing_share.status == "pending":
                # Calcular dias desde o envio
                days_since = (datetime.utcnow() - existing_share.created_at).days
                return jsonify({
                    "error": "Convite já enviado para este email",
                    "details": f"Convite enviado há {days_since} dia(s). Aguardando aceitação.",
                    "status": "pending",
                    "sent_at": existing_share.created_at.isoformat()
                }), 400
            elif existing_share.status == "accepted":
                return jsonify({
                    "error": "Sistema já compartilhado com este email",
                    "details": "Este usuário já tem acesso ao seu sistema.",
                    "status": "accepted",
                    "access_level": existing_share.access_level,
                    "accepted_at": existing_share.accepted_at.isoformat() if existing_share.accepted_at else None
                }), 400
        
        # Verificar se o usuário já existe
        shared_user = User.query.filter_by(email=shared_email).first()
        
        if shared_user:
            # Usuário já existe - criar compartilhamento direto
            share = SystemShare(
                owner_id=user_id,
                shared_user_id=shared_user.id,
                shared_email=shared_email,
                status="accepted",
                share_type=share_type,
                family_role=family_role if share_type == "family" else None,
                access_level=access_level,
                accepted_at=datetime.utcnow()
            )
        else:
            # Usuário não existe - criar convite pendente
            share = SystemShare(
                owner_id=user_id,
                shared_email=shared_email,
                status="pending",
                share_type=share_type,
                family_role=family_role if share_type == "family" else None,
                access_level=access_level
            )

        db.session.add(share)
        db.session.flush()

        email_ok = None
        if share.status == "pending":
            from flask import current_app
            email_ok = send_share_invitation(
                recipient_email=shared_email,
                owner_email=user.email,
                access_level=access_level,
                share_id=share.id,
                app=current_app
            )

            if not email_ok:
                db.session.rollback()
                return jsonify({
                    "error": "Não foi possível enviar o convite por e-mail.",
                    "details": "Verifique a configuração SMTP (Brevo) e tente novamente.",
                    "email_sent": False,
                }), 502

        db.session.commit()

        response_payload = {
            "message": "Compartilhamento criado com sucesso!",
            "email_sent": bool(email_ok) if email_ok is not None else None,
            "share": {
                "id": share.id,
                "email": share.shared_email,
                "status": share.status,
                "access_level": share.access_level,
                "created_at": share.created_at.isoformat()
            }
        }

        return jsonify(response_payload), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/ai/recommendations", methods=["POST", "OPTIONS"])
def api_ai_recommendations():
    origin = request.headers.get("Origin", "*")

    def _json(payload, status=200):
        resp = jsonify(payload)
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, status

    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    if "finance_user_id" not in session:
        return _json({"error": "Não autorizado"}, 401)

    user_id = session["finance_user_id"]
    data = request.get_json(silent=True) or {}

    try:
        workspace_id = data.get("workspace_id") or session.get("active_workspace_id")
        workspace_id = int(workspace_id) if workspace_id is not None else None
    except (ValueError, TypeError):
        workspace_id = None

    if not workspace_id:
        return _json({"error": "Workspace não selecionado"}, 400)

    workspace_role = _get_user_workspace_role(user_id=user_id, workspace_id=workspace_id)
    if not workspace_role:
        return _json({"error": "Sem permissão"}, 403)

    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        return _json({"error": "GROQ_API_KEY não configurada"}, 500)

    # Parâmetros opcionais vindos do front
    try:
        period_days = int(data.get("period_days") or 90)
    except (ValueError, TypeError):
        period_days = 90
    if period_days < 7:
        period_days = 7
    if period_days > 365:
        period_days = 365

    focus = (data.get("focus") or "overall").strip().lower()
    if focus not in ["overall", "category"]:
        focus = "overall"

    try:
        focus_category_id = int(data.get("category_id")) if data.get("category_id") is not None else None
    except (ValueError, TypeError):
        focus_category_id = None

    user_context = (data.get("context") or data.get("user_context") or "").strip()
    if len(user_context) > 2000:
        user_context = user_context[:2000]

    cache_ttl = int(os.getenv("AI_RECOMMEND_CACHE_TTL_SEC", "300") or "300")
    cache_key_raw = f"ws={workspace_id}|u={user_id}|days={period_days}|focus={focus}|cat={focus_category_id}|ctx={user_context}".encode("utf-8", errors="ignore")
    cache_key = hashlib.sha256(cache_key_raw).hexdigest()
    cached = _AI_RECOMMENDATION_CACHE.get(cache_key)
    if cached and (time.time() - cached.get("ts", 0)) <= cache_ttl:
        return _json({
            "cached": True,
            "workspace_id": workspace_id,
            "role": workspace_role,
            "recommendation": cached.get("recommendation"),
        }, 200)

    ws = Workspace.query.get(workspace_id)
    if not ws:
        return _json({"error": "Workspace não encontrado"}, 404)

    today = date.today()
    start_period = today - timedelta(days=period_days)

    income_sum = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.workspace_id == workspace_id,
        Transaction.type == "income",
        Transaction.transaction_date >= start_period,
    ).scalar()
    expense_sum = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.workspace_id == workspace_id,
        Transaction.type == "expense",
        Transaction.transaction_date >= start_period,
    ).scalar()

    recent_transactions = Transaction.query.filter_by(workspace_id=workspace_id).order_by(
        Transaction.transaction_date.desc()
    ).limit(15).all()

    top_categories_rows = db.session.query(
        Category.name,
        Category.type,
        func.coalesce(func.sum(Transaction.amount), 0).label("total"),
    ).join(Category, Category.id == Transaction.category_id).filter(
        Transaction.workspace_id == workspace_id,
        Transaction.transaction_date >= start_period,
    ).group_by(Category.name, Category.type).order_by(func.sum(Transaction.amount).desc()).limit(8).all()

    focus_category_summary = None
    if focus == "category" and focus_category_id:
        focus_cat = Category.query.get(focus_category_id)
        if focus_cat:
            focus_total = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.workspace_id == workspace_id,
                Transaction.category_id == focus_category_id,
                Transaction.transaction_date >= start_period,
            ).scalar()
            focus_category_summary = {
                "id": focus_cat.id,
                "name": focus_cat.name,
                "type": focus_cat.type,
                "total": float(focus_total or 0),
            }

    member_count = WorkspaceMember.query.filter_by(workspace_id=workspace_id).count() + 1

    workspace_snapshot = {
        "workspace": {
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "member_count": member_count,
        },
        "period": {
            "from": start_period.isoformat(),
            "to": today.isoformat(),
            "days": period_days,
        },
        "focus": {
            "type": focus,
            "category": focus_category_summary,
        },
        "totals_last_90_days": {
            "income": float(income_sum or 0),
            "expense": float(expense_sum or 0),
            "balance": float((income_sum or 0) - (expense_sum or 0)),
        },
        "top_categories_last_90_days": [
            {"name": r[0], "type": r[1], "total": float(r[2] or 0)} for r in top_categories_rows
        ],
        "recent_transactions": [
            {
                "date": t.transaction_date.isoformat() if t.transaction_date else None,
                "type": t.type,
                "description": t.description,
                "amount": float(t.amount or 0),
                "category": t.category.name if t.category else None,
            }
            for t in recent_transactions
        ],
    }

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    max_tokens = int(os.getenv("GROQ_MAX_TOKENS", "900") or "900")

    system_prompt = (
        "Você é um gestor de despesas pessoal em português brasileiro. "
        "Seja DIRETO e objetivo. Não faça introduções, não se justifique e não escreva textão. "
        "Use APENAS os dados do workspace e o foco/período recebidos. "
        "Responda em markdown curto, com listas e checklists. "
        "Formato obrigatório:\n"
        "1) ## Ações agora (hoje) -> 3 a 7 bullets no máximo\n"
        "2) ## Plano 7 dias -> 3 a 7 bullets no máximo\n"
        "3) ## Regras automáticas -> 3 a 7 bullets no máximo\n"
        "4) ## Alertas -> só se necessário\n"
        "Se faltar dado, faça NO MÁXIMO 3 perguntas objetivas no final."
    )

    user_prompt = (
        "Gere recomendações no formato solicitado, sem justificativas longas.\n\n"
        f"Contexto/objetivo selecionado: {user_context}\n\n"
        f"Snapshot do workspace (JSON): {workspace_snapshot}"
    )

    tokens_to_consume = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt) + max_tokens
    ok, used_now, limit = _ai_rate_limit_check(user_id=user_id, tokens_to_consume=tokens_to_consume)
    if not ok:
        return _json({
            "error": "Limite de uso de IA atingido. Tente novamente em instantes.",
            "tokens_used_last_minute": used_now,
            "tokens_limit_per_minute": limit,
        }, 429)

    try:
        groq_resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
            timeout=40,
        )
    except Exception as e:
        return _json({"error": f"Falha ao chamar IA: {str(e)}"}, 502)

    if groq_resp.status_code >= 400:
        try:
            err_body = groq_resp.json()
        except Exception:
            err_body = groq_resp.text
        return _json({
            "error": "Erro na IA",
            "status_code": groq_resp.status_code,
            "details": err_body,
        }, 502)

    payload = groq_resp.json() or {}
    recommendation = (((payload.get("choices") or [{}])[0]).get("message") or {}).get("content")
    if not recommendation:
        return _json({"error": "Resposta de IA vazia"}, 502)

    _AI_RECOMMENDATION_CACHE[cache_key] = {
        "ts": time.time(),
        "recommendation": recommendation,
    }

    return _json({
        "cached": False,
        "workspace_id": workspace_id,
        "role": workspace_role,
        "recommendation": recommendation,
    }, 200)


@gerenciamento_financeiro_bp.route("/api/pending-invites", methods=["GET"])
def api_pending_invites():
    """Lista convites pendentes recebidos pelo usuário"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    user = User.query.get(user_id)
    
    try:
        # Convites pendentes para o email do usuário logado
        pending = SystemShare.query.filter_by(
            shared_email=user.email.lower(),
            status='pending'
        ).all()
        
        return jsonify({
            "pending_invites": [{
                "id": s.id,
                "owner_email": s.owner.email,
                "share_type": s.share_type,
                "family_role": s.family_role,
                "access_level": s.access_level,
                "created_at": s.created_at.isoformat()
            } for s in pending]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/system/shares", methods=["GET"])
def api_list_shares():
    """Lista todos os compartilhamentos do usuário"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        # Compartilhamentos que o usuário criou
        created_shares = SystemShare.query.filter_by(owner_id=user_id).all()
        
        # Compartilhamentos que o usuário recebeu
        received_shares = SystemShare.query.filter_by(shared_user_id=user_id).all()
        
        return jsonify({
            "sent_shares": [{
                "id": s.id,
                "shared_email": s.shared_email,
                "status": s.status,
                "share_type": s.share_type,
                "family_role": s.family_role,
                "access_level": s.access_level,
                "created_at": s.created_at.isoformat(),
                "accepted_at": s.accepted_at.isoformat() if s.accepted_at else None
            } for s in created_shares],
            "received_shares": [{
                "id": s.id,
                "owner_email": s.owner.email,
                "status": s.status,
                "share_type": s.share_type,
                "family_role": s.family_role,
                "access_level": s.access_level,
                "created_at": s.created_at.isoformat(),
                "accepted_at": s.accepted_at.isoformat() if s.accepted_at else None
            } for s in received_shares]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/system/share/<int:share_id>/accept", methods=["POST"])
def api_accept_share(share_id: int):
    """Aceita um compartilhamento recebido"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        share = SystemShare.query.get(share_id)
        
        if not share:
            return jsonify({"error": "Compartilhamento não encontrado"}), 404
        
        # Verificar se o usuário é o destinatário
        if share.shared_email != User.query.get(user_id).email:
            return jsonify({"error": "Você não tem permissão para aceitar este compartilhamento"}), 403
        
        if share.status != "pending":
            return jsonify({"error": "Este compartilhamento não está pendente"}), 400
        
        # Atualizar compartilhamento
        share.shared_user_id = user_id
        share.status = "accepted"
        share.accepted_at = datetime.utcnow()
        
        db.session.commit()
        
        # Enviar email de confirmação ao proprietário
        from flask import current_app
        send_share_accepted(
            owner_email=share.owner.email,
            shared_email=share.shared_email,
            app=current_app
        )
        
        return jsonify({
            "message": "Compartilhamento aceito com sucesso!",
            "share": {
                "id": share.id,
                "owner_email": share.owner.email,
                "status": share.status,
                "access_level": share.access_level
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/system/share/<int:share_id>", methods=["DELETE"])
def api_delete_share(share_id: int):
    """Remove um compartilhamento"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        share = SystemShare.query.get(share_id)
        
        if not share:
            return jsonify({"error": "Compartilhamento não encontrado"}), 404
        
        # Verificar se o usuário é o proprietário ou destinatário
        if share.owner_id != user_id and share.shared_user_id != user_id:
            return jsonify({"error": "Você não tem permissão para remover este compartilhamento"}), 403
        
        db.session.delete(share)
        db.session.commit()
        
        return jsonify({"message": "Compartilhamento removido com sucesso!"}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# ============================================================================
# ROTAS DE PÁGINAS (mantidas mas redirecionam para modal)
# ============================================================================

@gerenciamento_financeiro_bp.route("/transactions")
def transactions_page():
    # Redireciona para dashboard com modal aberto via JavaScript
    return redirect(url_for("gerenciamento_financeiro.home") + "#transacoes")

@gerenciamento_financeiro_bp.route("/categories")
def categories_page():
    # Redireciona para dashboard com modal aberto via JavaScript  
    return redirect(url_for("gerenciamento_financeiro.home") + "#categorias")

@gerenciamento_financeiro_bp.route("/reports")
def reports_page():
    # Redireciona para dashboard com modal aberto via JavaScript
    return redirect(url_for("gerenciamento_financeiro.home") + "#relatorios")

@gerenciamento_financeiro_bp.route("/recurring")
def recurring_page():
    # Redireciona para dashboard com modal aberto via JavaScript
    return redirect(url_for("gerenciamento_financeiro.home") + "#fixos")

# ============================================================================
# ROTAS DE WORKSPACES
# ============================================================================

@gerenciamento_financeiro_bp.route("/api/workspaces/select/<int:workspace_id>", methods=["POST"])
def api_select_workspace(workspace_id):
    """Seleciona um workspace ativo"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            resp = jsonify({"error": "Workspace não encontrado"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 404
        
        # Verificar permissão (dono ou membro)
        if workspace.owner_id != user_id:
            member = WorkspaceMember.query.filter_by(
                workspace_id=workspace_id,
                user_id=user_id
            ).first()
            if not member:
                return jsonify({"error": "Sem permissão"}), 403
        
        # Salvar na sessão
        session["active_workspace_id"] = workspace_id
        session.modified = True
        
        return jsonify({
            "success": True,
            "message": "Workspace selecionado",
            "workspace_id": workspace_id,
            "workspace_name": workspace.name
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@gerenciamento_financeiro_bp.route("/api/workspaces", methods=["GET", "POST"])
def api_workspaces():
    """Lista ou cria workspaces"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    if request.method == "POST":
        try:
            data = request.get_json()
            name = data.get("name", "").strip()
            description = data.get("description", "").strip()
            color = data.get("color", "#3b82f6")
            
            if not name:
                return jsonify({"error": "Nome do workspace é obrigatório"}), 400
            
            workspace = Workspace(
                owner_id=user_id,
                name=name,
                description=description,
                color=color
            )
            db.session.add(workspace)
            db.session.commit()
            
            return jsonify({
                "id": workspace.id,
                "name": workspace.name,
                "description": workspace.description,
                "color": workspace.color,
                "created_at": workspace.created_at.isoformat()
            }), 201
            
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    else:  # GET
        try:
            # Workspaces que o usuário é dono
            owned = Workspace.query.filter_by(owner_id=user_id).all()
            owned_ids = {w.id for w in owned}
            
            # Workspaces compartilhados com o usuário (excluindo os que é dono)
            shared_members = WorkspaceMember.query.filter_by(user_id=user_id).all()
            shared_workspace_ids = [m.workspace_id for m in shared_members if m.workspace_id not in owned_ids]
            shared = Workspace.query.filter(Workspace.id.in_(shared_workspace_ids)).all() if shared_workspace_ids else []
            
            # Criar dicionário de roles para workspaces compartilhados
            member_roles = {m.workspace_id: m.role for m in shared_members}
            
            return jsonify({
                "owned": [{
                    "id": w.id,
                    "name": w.name,
                    "description": w.description,
                    "color": w.color,
                    "role": "owner",
                    "created_at": w.created_at.isoformat()
                } for w in owned],
                "shared": [{
                    "id": w.id,
                    "name": w.name,
                    "description": w.description,
                    "color": w.color,
                    "owner_email": w.owner.email,
                    "role": member_roles.get(w.id, "viewer"),
                    "created_at": w.created_at.isoformat()
                } for w in shared]
            }), 200
            
        except Exception as e:
            _log_exception(f"Erro ao listar workspaces: {e}")
            return jsonify({"error": str(e)}), 500

@gerenciamento_financeiro_bp.route("/api/workspaces/<int:workspace_id>/members", methods=["GET"])
def api_workspace_members(workspace_id):
    """Lista membros de um workspace"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    origin = request.headers.get("Origin", "*")
    
    try:
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            resp = jsonify({"error": "Workspace não encontrado"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 404
        
        # Verificar permissão (dono ou membro)
        if workspace.owner_id != user_id:
            member = WorkspaceMember.query.filter_by(
                workspace_id=workspace_id,
                user_id=user_id
            ).first()
            if not member:
                return jsonify({"error": "Sem permissão"}), 403
        
        manager_member = WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=user_id).first()
        can_manage = bool(workspace.owner_id == user_id or (manager_member and manager_member.role == "owner"))
        
        members = WorkspaceMember.query.filter_by(workspace_id=workspace_id).all()
        
        return jsonify({
            "can_manage": can_manage,
            "owner_id": workspace.owner_id,
            "owner_email": workspace.owner.email if workspace.owner else None,
            "members": [{
                "id": m.id,
                "user_id": m.user_id,
                "email": m.user.email,
                "role": m.role,
                "joined_at": m.joined_at.isoformat()
            } for m in members]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/workspaces/<int:workspace_id>/members/<int:member_id>", methods=["PUT", "DELETE"])
def api_manage_workspace_member(workspace_id, member_id):
    """Atualiza role ou remove um membro do workspace (dono ou co-owner)."""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401

    user_id = session["finance_user_id"]
    origin = request.headers.get("Origin", "*")

    try:
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            resp = jsonify({"error": "Workspace não encontrado"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 404

        manager_member = WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=user_id).first()
        can_manage = bool(workspace.owner_id == user_id or (manager_member and manager_member.role == "owner"))
        if not can_manage:
            resp = jsonify({"error": "Sem permissão"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 403

        member = WorkspaceMember.query.filter_by(id=member_id, workspace_id=workspace_id).first()
        if not member:
            resp = jsonify({"error": "Membro não encontrado"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 404

        if member.user_id == workspace.owner_id:
            resp = jsonify({"error": "Não é possível alterar ou remover o dono do workspace"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 400

        if request.method == "PUT":
            data = request.get_json() or {}
            new_role = (data.get("role") or "").strip().lower()
            if new_role not in ["editor", "viewer"]:
                resp = jsonify({"error": "Função inválida"})
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                return resp, 400

            member.role = new_role
            db.session.commit()

            resp = jsonify({
                "message": "Permissão atualizada",
                "member_id": member.id,
                "role": member.role,
            })
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 200

        # DELETE
        db.session.delete(member)
        db.session.commit()
        resp = jsonify({"message": "Membro removido"})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 200

    except Exception as e:
        db.session.rollback()
        resp = jsonify({"error": str(e)})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 500

@gerenciamento_financeiro_bp.route("/api/workspaces/<int:workspace_id>", methods=["PUT", "DELETE"])
def api_update_workspace(workspace_id):
    """Atualiza ou deleta um workspace"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    origin = request.headers.get("Origin", "*")
    
    try:
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            resp = jsonify({"error": "Workspace não encontrado"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 404
        
        # Apenas o dono pode atualizar/deletar
        if workspace.owner_id != user_id:
            return jsonify({"error": "Sem permissão"}), 403
        
        if request.method == "PUT":
            # Atualizar workspace
            data = request.get_json()
            
            if "name" in data:
                name = data.get("name", "").strip()
                if not name:
                    return jsonify({"error": "Nome não pode estar vazio"}), 400
                workspace.name = name
            
            if "description" in data:
                workspace.description = data.get("description", "").strip()
            
            if "color" in data:
                workspace.color = data.get("color", "#3b82f6")
            
            db.session.commit()
            
            return jsonify({
                "message": "Workspace atualizado com sucesso",
                "id": workspace.id,
                "name": workspace.name,
                "description": workspace.description,
                "color": workspace.color
            }), 200
        
        elif request.method == "DELETE":
            # Deletar workspace
            # Não permitir deletar se é o único workspace
            count = Workspace.query.filter_by(owner_id=user_id).count()
            if count <= 1:
                return jsonify({"error": "Você deve ter pelo menos um workspace"}), 400
            
            # Limpar workspace_id das transações
            Transaction.query.filter_by(workspace_id=workspace_id).update({"workspace_id": None})
            
            # Deletar workspace
            db.session.delete(workspace)
            db.session.commit()
            
            # Se era o workspace ativo, selecionar outro
            if session.get("active_workspace_id") == workspace_id:
                new_workspace = Workspace.query.filter_by(owner_id=user_id).first()
                if new_workspace:
                    session["active_workspace_id"] = new_workspace.id
                else:
                    session.pop("active_workspace_id", None)
            
            return jsonify({
                "message": "Workspace deletado com sucesso"
            }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# CONVITES DE WORKSPACE
# ============================================================================

@gerenciamento_financeiro_bp.route("/api/workspaces/<int:workspace_id>/invite", methods=["POST", "OPTIONS"])
def api_invite_to_workspace(workspace_id):
    """Envia convite para workspace por email"""
    origin = request.headers.get("Origin", "*")

    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    _log_debug(f"[WORKSPACE INVITE] HIT path={request.path} method={request.method} user_id={session.get('finance_user_id')} workspace_id={workspace_id}")

    if "finance_user_id" not in session:
        resp = jsonify({"error": "Não autorizado"})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401
    
    user_id = session["finance_user_id"]
    
    try:
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            resp = jsonify({"error": "Workspace não encontrado"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 404
        
        # Verificar se é dono do workspace ou co-owner
        if workspace.owner_id != user_id:
            member = WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=user_id).first()
            if not member or member.role != "owner":
                resp = jsonify({"error": "Apenas o dono pode convidar"})
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                return resp, 403

            # Se chegou aqui, é co-owner (role=owner)
            pass
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"

        
        data = request.get_json()
        email = data.get("email", "").strip().lower()
        role = data.get("role", "editor")
        
        if not email:
            resp = jsonify({"error": "Email é obrigatório"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 400
        
        if role not in ["owner", "editor", "viewer"]:
            resp = jsonify({"error": "Função inválida"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 400
        
        # Verificar se já é membro
        target_user = User.query.filter(func.lower(User.email) == email).first()
        if target_user:
            existing_member = WorkspaceMember.query.filter_by(
                workspace_id=workspace_id, user_id=target_user.id
            ).first()
            if existing_member:
                resp = jsonify({"error": "Usuário já é membro deste workspace"})
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                return resp, 400
            
            if target_user.id == workspace.owner_id:
                resp = jsonify({"error": "Não é possível convidar o dono do workspace"})
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                return resp, 400
        
        # Verificar se já existe convite pendente - se existir, atualiza
        existing_invite = WorkspaceInvite.query.filter_by(
            workspace_id=workspace_id,
            invited_email=email,
            status="pending"
        ).first()
        
        if existing_invite:
            # Atualizar convite existente
            existing_invite.role = role
            existing_invite.token = secrets.token_urlsafe(32)
            existing_invite.expires_at = datetime.utcnow() + timedelta(days=7)
            existing_invite.created_at = datetime.utcnow()
            existing_invite.invited_user_id = target_user.id if target_user else None
            invite = existing_invite
        else:
            # Criar novo convite
            token = secrets.token_urlsafe(32)
            invite = WorkspaceInvite(
                workspace_id=workspace_id,
                invited_by_id=user_id,
                invited_email=email,
                invited_user_id=target_user.id if target_user else None,
                role=role,
                token=token,
                expires_at=datetime.utcnow() + timedelta(days=7)
            )
            db.session.add(invite)
        db.session.commit()
        
        # Enviar email de convite
        inviter = User.query.get(user_id)
        email_ok = None
        try:
            from flask import current_app
            email_ok = send_workspace_invitation(
                recipient_email=email,
                inviter_email=inviter.email,
                token=invite.token,
                workspace_name=workspace.name,
                role=role,
                app=current_app._get_current_object()
            )
            _log_debug(f"[INVITE] send_workspace_invitation retornou={email_ok}")
        except Exception as e:
            _log_exception(f"Erro ao enviar email de convite: {e}")
        
        invite_url = url_for("gerenciamento_financeiro.open_workspace_invite", token=invite.token, _external=True)

        resp = jsonify({
            "message": "Convite criado com sucesso!" if email_ok else "Convite criado, mas o email não pôde ser enviado.",
            "invite_id": invite.id,
            "email": email,
            "role": role,
            "email_sent": bool(email_ok),
            "invite_url": invite_url
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 201
        
    except Exception as e:
        db.session.rollback()
        _log_exception(f"[WORKSPACE INVITE] 500 - {e}")
        resp = jsonify({"error": str(e)})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 500


@gerenciamento_financeiro_bp.route("/api/invites/pending", methods=["GET"])
def api_my_pending_invites():
    """Lista convites pendentes do usuário logado"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    user = User.query.get(user_id)
    
    try:
        invites = WorkspaceInvite.query.filter(
            or_(
                WorkspaceInvite.invited_user_id == user_id,
                func.lower(WorkspaceInvite.invited_email) == user.email.lower()
            ),
            WorkspaceInvite.status == "pending",
            WorkspaceInvite.expires_at > datetime.utcnow()
        ).all()
        
        return jsonify({
            "count": len(invites),
            "invites": [{
                "id": i.id,
                "workspace_id": i.workspace_id,
                "workspace_name": i.workspace.name,
                "workspace_color": i.workspace.color,
                "invited_by": i.invited_by.email,
                "role": i.role,
                "created_at": i.created_at.isoformat()
            } for i in invites]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/invites/<int:invite_id>/accept", methods=["POST"])
def api_accept_invite(invite_id):
    """Aceita um convite de workspace"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    user = User.query.get(user_id)
    
    try:
        invite = WorkspaceInvite.query.get(invite_id)
        if not invite:
            return jsonify({"error": "Convite não encontrado"}), 404
        
        # Verificar se o convite é para este usuário
        is_for_user = (
            invite.invited_user_id == user_id or
            invite.invited_email.lower() == user.email.lower()
        )
        
        if not is_for_user:
            return jsonify({"error": "Este convite não é para você"}), 403
        
        if invite.status != "pending":
            return jsonify({"error": f"Convite já foi {invite.status}"}), 400
        
        if invite.expires_at < datetime.utcnow():
            invite.status = "expired"
            db.session.commit()
            return jsonify({"error": "Convite expirado"}), 400
        
        # Verificar se já é membro
        existing_member = WorkspaceMember.query.filter_by(
            workspace_id=invite.workspace_id,
            user_id=user_id
        ).first()
        
        if not existing_member:
            # Adicionar como membro
            member = WorkspaceMember(
                workspace_id=invite.workspace_id,
                user_id=user_id,
                role=invite.role
            )
            db.session.add(member)
            _log_debug(f"[ACCEPT_INVITE] Novo membro adicionado: user_id={user_id} workspace_id={invite.workspace_id}")
        else:
            _log_debug(f"[ACCEPT_INVITE] Usuário já é membro: user_id={user_id} workspace_id={invite.workspace_id}")
        
        invite.status = "accepted"
        invite.responded_at = datetime.utcnow()
        invite.invited_user_id = user_id
        db.session.commit()
        
        # Notificar quem convidou
        try:
            send_share_accepted(
                owner_email=invite.invited_by.email,
                shared_email=user.email,
                app=current_app
            )
        except Exception as e:
            _log_exception(f"Erro ao enviar email de aceitação: {e}")
        
        return jsonify({
            "message": "Convite aceito! Você agora faz parte do workspace.",
            "workspace_id": invite.workspace_id,
            "workspace_name": invite.workspace.name
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/invites/<int:invite_id>/reject", methods=["POST"])
def api_reject_invite(invite_id):
    """Rejeita um convite de workspace"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    user = User.query.get(user_id)
    
    try:
        invite = WorkspaceInvite.query.get(invite_id)
        if not invite:
            return jsonify({"error": "Convite não encontrado"}), 404
        
        is_for_user = (
            invite.invited_user_id == user_id or
            invite.invited_email.lower() == user.email.lower()
        )
        
        if not is_for_user:
            return jsonify({"error": "Este convite não é para você"}), 403
        
        if invite.status != "pending":
            return jsonify({"error": f"Convite já foi {invite.status}"}), 400
        
        invite.status = "rejected"
        invite.responded_at = datetime.utcnow()
        invite.invited_user_id = user_id
        db.session.commit()
        
        return jsonify({"message": "Convite recusado"}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@gerenciamento_financeiro_bp.route("/api/workspace/clear", methods=["POST"])
def api_clear_workspace():
    """Limpa todas as transações do workspace atual"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    if "active_workspace_id" not in session:
        return jsonify({"error": "Nenhum workspace ativo"}), 400
    
    user_id = session["finance_user_id"]
    workspace_id = session["active_workspace_id"]
    
    try:
        # Verificar se o usuário tem permissão (owner ou editor)
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            return jsonify({"error": "Workspace não encontrado"}), 404
        
        # Verificar se é owner
        is_owner = workspace.owner_id == user_id
        
        # Verificar se é membro com permissão de edição
        is_editor = False
        if not is_owner:
            member = WorkspaceMember.query.filter_by(
                workspace_id=workspace_id,
                user_id=user_id
            ).first()
            is_editor = member and member.role in ['editor', 'owner']
        
        if not (is_owner or is_editor):
            return jsonify({"error": "Sem permissão para limpar este workspace"}), 403
        
        # Capturar IDs de fechamentos ligados às transações deste workspace
        closure_rows = (
            db.session.query(Transaction.monthly_closure_id)
            .filter(Transaction.workspace_id == workspace_id)
            .filter(Transaction.monthly_closure_id.isnot(None))
            .distinct()
            .all()
        )
        closure_ids = [r[0] for r in closure_rows if r and r[0] is not None]

        # Deletar todas as transações do workspace
        deleted_count = (
            Transaction.query
            .filter(Transaction.workspace_id == workspace_id)
            .delete(synchronize_session=False)
        )

        # Deletar transações recorrentes (não possuem workspace_id).
        # Fazemos a limpeza com base no workspace_id da categoria.
        recurring_ids_subq = (
            db.session.query(RecurringTransaction.id)
            .join(Category, RecurringTransaction.category_id == Category.id)
            .filter(Category.workspace_id == workspace_id)
            .subquery()
        )
        recurring_deleted = (
            RecurringTransaction.query
            .filter(RecurringTransaction.id.in_(recurring_ids_subq))
            .delete(synchronize_session=False)
        )

        # Deletar snapshots e fechamentos mensais relacionados às transações deletadas
        fixed_deleted = 0
        closure_deleted = 0
        if closure_ids:
            fixed_deleted = (
                MonthlyFixedExpense.query
                .filter(MonthlyFixedExpense.monthly_closure_id.in_(closure_ids))
                .delete(synchronize_session=False)
            )
            closure_deleted = (
                MonthlyClosure.query
                .filter(MonthlyClosure.id.in_(closure_ids))
                .delete(synchronize_session=False)
            )
        
        db.session.commit()
        
        return jsonify({
            "message": "Workspace limpo com sucesso",
            "transactions_deleted": deleted_count,
            "recurring_deleted": recurring_deleted,
            "monthly_fixed_deleted": fixed_deleted,
            "monthly_closures_deleted": closure_deleted,
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

"""
API REST para Aplicativo Mobile (Flutter) - Gerenciamento Financeiro
=====================================================================

Endpoints JSON para autenticação e operações financeiras via app mobile.
"""

from flask import Blueprint, request, jsonify, session
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta, date
import random
import os
import requests
import calendar

from extensions import db
from models import User, Workspace, EmailVerification, LoginAudit, Transaction, Category, FinanceConfig, RecurringTransaction, TransactionAttachment
from werkzeug.utils import secure_filename

# Blueprint da API
api_financeiro_bp = Blueprint(
    "api_financeiro",
    __name__,
)

print("[API_FINANCEIRO] Blueprint api_financeiro_bp criado")


def _cors_preflight(origin: str, methods: str):
    resp = jsonify({"ok": True})
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = methods
    requested_headers = request.headers.get("Access-Control-Request-Headers")
    resp.headers["Access-Control-Allow-Headers"] = requested_headers or "Content-Type, Authorization"
    resp.headers["Access-Control-Max-Age"] = "86400"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp


def _cors_wrap(resp, origin: str):
    try:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    except Exception:
        pass
    return resp


def _get_user_id_from_request():
    session_user_id = session.get("finance_user_id")
    request_user_id = request.args.get("user_id")
    user_id = session_user_id or request_user_id
    try:
        return int(user_id) if user_id is not None else None
    except Exception:
        return None


def _migrate_legacy_recurring_transactions(user_id: int):
    """
    Migra recorrências antigas criadas diretamente na tabela transactions
    (is_recurring=True, recurring_transaction_id=None) para a tabela
    recurring_transactions.

    Isso permite que ao trocar o mês no dashboard o sistema consiga gerar
    automaticamente as recorrentes futuras.
    """
    legacy = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.is_recurring.is_(True),
        Transaction.recurring_transaction_id.is_(None),
    ).all()

    print(f"[MIGRATE_RECURRING] Encontradas {len(legacy)} transações recorrentes antigas para migrar")

    if not legacy:
        return

    cache: dict[tuple, RecurringTransaction] = {}

    for tx in legacy:
        if not tx.transaction_date:
            continue

        day_of_month = int(tx.transaction_date.day)
        key = (
            (tx.type or "").strip().lower(),
            (tx.description or "").strip().lower(),
            float(tx.amount or 0),
            int(tx.category_id),
            day_of_month,
            (tx.payment_method or "").strip().lower(),
            (tx.subcategory_text or "").strip().lower(),
        )

        rec_tx = cache.get(key)
        if not rec_tx:
            rec_tx = RecurringTransaction.query.filter(
                RecurringTransaction.user_id == user_id,
                RecurringTransaction.frequency == "monthly",
                RecurringTransaction.type == tx.type,
                RecurringTransaction.category_id == tx.category_id,
                RecurringTransaction.description == tx.description,
                RecurringTransaction.amount == tx.amount,
                RecurringTransaction.day_of_month == day_of_month,
                RecurringTransaction.payment_method == tx.payment_method,
                RecurringTransaction.subcategory_text == tx.subcategory_text,
            ).first()

        if not rec_tx:
            print(f"[MIGRATE_RECURRING] Criando RecurringTransaction para: {tx.description} (dia {day_of_month})")
            # start_date deve ser o primeiro dia do mês da transação
            start_date_first_day = date(tx.transaction_date.year, tx.transaction_date.month, 1)
            rec_tx = RecurringTransaction(
                user_id=user_id,
                category_id=tx.category_id,
                subcategory_id=getattr(tx, "subcategory_id", None),
                subcategory_text=tx.subcategory_text,
                description=tx.description,
                amount=tx.amount,
                type=tx.type,
                frequency="monthly",
                day_of_month=day_of_month,
                start_date=start_date_first_day,
                end_date=None,
                is_active=True,
                payment_method=tx.payment_method,
                notes=tx.notes,
            )
            db.session.add(rec_tx)
            db.session.flush()
        else:
            print(f"[MIGRATE_RECURRING] RecurringTransaction já existe para: {tx.description}")

        cache[key] = rec_tx

        tx.recurring_transaction_id = rec_tx.id
        tx.frequency = "monthly"

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _fix_recurring_start_dates(user_id: int):
    """
    Corrige start_date de RecurringTransaction que não estão no primeiro dia do mês.
    Usa a primeira transação vinculada como referência para o mês correto.
    Também vincula transações antigas não vinculadas.
    """
    recurring_txs = RecurringTransaction.query.filter_by(
        user_id=user_id,
        is_active=True,
        frequency="monthly"
    ).all()
    
    fixed_count = 0
    for rec_tx in recurring_txs:
        if not rec_tx.start_date:
            continue
        
        # Buscar transações antigas não vinculadas que correspondem a esta recorrente
        unlinked_txs = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.is_recurring.is_(True),
            Transaction.recurring_transaction_id.is_(None),
            Transaction.description == rec_tx.description,
            Transaction.type == rec_tx.type,
            Transaction.amount == rec_tx.amount
        ).all()
        
        if unlinked_txs:
            print(f"[FIX_START_DATE] {rec_tx.description}: encontradas {len(unlinked_txs)} transações não vinculadas")
            for tx in unlinked_txs:
                print(f"[FIX_START_DATE]   - Vinculando {tx.description} de {tx.transaction_date}")
                tx.recurring_transaction_id = rec_tx.id
                tx.frequency = "monthly"
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        
        # Buscar TODAS as transações vinculadas para debug
        all_txs = Transaction.query.filter_by(
            user_id=user_id,
            recurring_transaction_id=rec_tx.id
        ).order_by(Transaction.transaction_date.asc()).all()
        
        print(f"[FIX_START_DATE] {rec_tx.description}: {len(all_txs)} transações vinculadas, start_date atual: {rec_tx.start_date}")
        for tx in all_txs:
            print(f"[FIX_START_DATE]   - {tx.description} em {tx.transaction_date}")
        
        # Buscar a primeira transação vinculada a esta recorrente
        first_tx = all_txs[0] if all_txs else None
        
        if first_tx and first_tx.transaction_date:
            old_start = rec_tx.start_date
            # Usar o mês da primeira transação como referência
            new_start = date(first_tx.transaction_date.year, first_tx.transaction_date.month, 1)
            
            print(f"[FIX_START_DATE] {rec_tx.description}: comparando start_date {old_start} com primeira transação {first_tx.transaction_date} -> novo start_date seria {new_start}")
            
            # Corrigir se o start_date for diferente do mês da primeira transação
            if old_start != new_start:
                rec_tx.start_date = new_start
                print(f"[FIX_START_DATE] ✅ Corrigindo {rec_tx.description}: {old_start} -> {new_start}")
                fixed_count += 1
            else:
                print(f"[FIX_START_DATE] ✓ {rec_tx.description}: start_date já está correto ({old_start})")
        else:
            print(f"[FIX_START_DATE] ⚠️ {rec_tx.description}: sem transações vinculadas, mantendo start_date {rec_tx.start_date}")
    
    if fixed_count > 0:
        try:
            db.session.commit()
            print(f"[FIX_START_DATE] {fixed_count} RecurringTransaction corrigidas")
        except Exception as e:
            print(f"[FIX_START_DATE] Erro ao corrigir: {e}")
            db.session.rollback()


def _generate_recurring_for_month(user_id: int, year: int, month: int):
    """
    Gera automaticamente as transações recorrentes do mês se ainda não existirem.
    """
    print(f"[GENERATE_RECURRING] Iniciando geração para {month}/{year}")
    
    # Corrigir start_date de recorrentes existentes (uma única vez)
    _fix_recurring_start_dates(user_id)
    
    # Migra recorrências antigas para a tabela recorrente (uma única vez/por demanda)
    _migrate_legacy_recurring_transactions(user_id)

    # Buscar todas as RecurringTransaction ativas do usuário
    recurring_txs = RecurringTransaction.query.filter_by(
        user_id=user_id,
        is_active=True,
        frequency="monthly"
    ).all()
    
    print(f"[GENERATE_RECURRING] Encontradas {len(recurring_txs)} RecurringTransaction ativas")

    for rec_tx in recurring_txs:
        # Verificar se está dentro do período de validade
        target_date = date(year, month, 1)
        
        print(f"[GENERATE_RECURRING] Processando: {rec_tx.description} (dia {rec_tx.day_of_month})")
        print(f"[GENERATE_RECURRING] start_date: {rec_tx.start_date}, end_date: {rec_tx.end_date}, target: {target_date}")
        
        # Se tem start_date e o mês é anterior ao início, pular
        if rec_tx.start_date:
            start_month = date(rec_tx.start_date.year, rec_tx.start_date.month, 1)
            if target_date < start_month:
                print(f"[GENERATE_RECURRING] Pulando {rec_tx.description}: mês anterior ao início ({target_date} < {start_month})")
                continue
        
        # Se tem end_date e o mês é posterior ao fim, pular
        if rec_tx.end_date:
            end_month = date(rec_tx.end_date.year, rec_tx.end_date.month, 1)
            if target_date > end_month:
                print(f"[GENERATE_RECURRING] Pulando {rec_tx.description}: mês posterior ao fim ({target_date} > {end_month})")
                continue
        
        # Calcular a data da transação usando o dia do mês
        day_of_month = rec_tx.day_of_month or 1
        last_day = calendar.monthrange(year, month)[1]
        day = min(day_of_month, last_day)
        transaction_date = date(year, month, day)
        
        # Verificar se já existe uma transação deste recurring_transaction neste mês
        existing = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.recurring_transaction_id == rec_tx.id,
            func.extract('year', Transaction.transaction_date) == year,
            func.extract('month', Transaction.transaction_date) == month
        ).first()
        
        if existing:
            print(f"[GENERATE_RECURRING] Já existe transação para {rec_tx.description} em {month}/{year}")
            continue  # Já existe, não criar novamente
        
        # Criar a transação do mês
        print(f"[GENERATE_RECURRING] Criando transação para {rec_tx.description} em {transaction_date}")
        new_tx = Transaction(
            user_id=user_id,
            category_id=rec_tx.category_id,
            subcategory_id=rec_tx.subcategory_id,
            subcategory_text=rec_tx.subcategory_text,
            description=rec_tx.description,
            amount=rec_tx.amount,
            type=rec_tx.type,
            transaction_date=transaction_date,
            is_paid=False,  # Despesas recorrentes iniciam como não pagas
            payment_method=rec_tx.payment_method,
            notes=rec_tx.notes,
            is_recurring=True,
            frequency="monthly",
            recurring_transaction_id=rec_tx.id,
            is_auto_loaded=True,
        )
        db.session.add(new_tx)
    
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _ensure_finance_config_and_categories(user_id: int):
    cfg = FinanceConfig.query.filter_by(user_id=user_id).first()
    if not cfg:
        cfg = FinanceConfig(user_id=user_id)
        db.session.add(cfg)
        db.session.flush()

    has_any = Category.query.filter_by(config_id=cfg.id).count() > 0
    if not has_any:
        defaults = [
            # Income
            ("Salário", "income", "💼", "#10b981"),
            ("Freelance", "income", "🧑‍💻", "#06b6d4"),
            ("Outros", "income", "✨", "#3b82f6"),
            # Expense
            ("Alimentação", "expense", "🍔", "#f59e0b"),
            ("Transporte", "expense", "🚗", "#22c55e"),
            ("Moradia", "expense", "🏠", "#6366f1"),
            ("Saúde", "expense", "🏥", "#ef4444"),
            ("Lazer", "expense", "🎮", "#a855f7"),
            ("Educação", "expense", "📚", "#0ea5e9"),
            ("Outros", "expense", "🧾", "#64748b"),
        ]
        for name, cat_type, icon, color in defaults:
            db.session.add(Category(
                config_id=cfg.id,
                name=name,
                type=cat_type,
                icon=icon,
                color=color,
                is_default=True,
                is_active=True,
            ))

    db.session.commit()
    return cfg


def _log_attempt(email: str, succeeded: bool, message: str | None = None, user_id: int | None = None):
    """Registra tentativa de login no audit log"""
    try:
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
    except Exception:
        db.session.rollback()


@api_financeiro_bp.route("/api/login", methods=["POST", "OPTIONS"])
@api_financeiro_bp.route("/api/login/", methods=["POST", "OPTIONS"])
def api_login():
    """
    Endpoint de login para clientes API (Flutter).
    
    POST /gerenciamento-financeiro/api/login
    Body: {"email": "...", "password": "..."}
    
    Retorna:
    - 200: {"success": true, "message": "...", "user": {"id": ..., "email": "..."}}
    - 400/401: {"success": false, "message": "..."}
    """
    
    # CORS
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")
    
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    remember_me = data.get("remember_me") or data.get("auto_login")
    
    if not email or not password:
        resp = jsonify({
            "success": False,
            "message": "Informe e-mail e senha.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 400
    
    user = User.query.filter(func.lower(User.email) == email).first()
    
    if not user or not check_password_hash(user.password_hash, password):
        _log_attempt(email, False, "Credenciais inválidas")
        resp = jsonify({
            "success": False,
            "message": "E-mail ou senha inválidos.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401
    
    # Autenticação bem-sucedida
    session.permanent = bool(remember_me)
    session["finance_user_id"] = user.id
    session["finance_user_email"] = user.email
    
    # Garantir workspace padrão
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
    
    _log_attempt(email, True, "Login via API", user_id=user.id)

    # Garantir config e categorias padrão
    try:
        _ensure_finance_config_and_categories(user.id)
    except Exception:
        db.session.rollback()
    
    resp = jsonify({
        "success": True,
        "message": "Login realizado com sucesso",
        "user": {
            "id": user.id,
            "email": user.email,
        },
    })
    return _cors_wrap(resp, origin), 200


@api_financeiro_bp.route("/api/transactions/<int:tx_id>/remove", methods=["GET", "OPTIONS"])
def api_transaction_remove(tx_id: int):
    """Endpoint GET para exclusão (workaround CORS para Flutter Web)."""
    origin = request.headers.get("Origin", "*")
    print(f"[TX_REMOVE] GET /api/transactions/{tx_id}/remove - args: {dict(request.args)}")

    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, OPTIONS")

    user_id_int = session.get("finance_user_id")
    if not user_id_int:
        try:
            raw_user_id = request.args.get("user_id")
            if raw_user_id:
                user_id_int = int(raw_user_id)
        except Exception as e:
            print(f"[TX_REMOVE] Erro ao parsear user_id: {e}")
            user_id_int = None

    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    tx = Transaction.query.filter_by(id=tx_id, user_id=int(user_id_int)).first()
    if not tx:
        resp = jsonify({"success": False, "message": "Transação não encontrada"})
        return _cors_wrap(resp, origin), 404

    scope = (request.args.get("scope") or "single").strip().lower()

    def _prev_month_last_day(d: date) -> date:
        first = date(d.year, d.month, 1)
        prev_last = first - timedelta(days=1)
        return prev_last

    def _delete_recurring_scope(target_tx: Transaction, scope_value: str):
        rec_id = getattr(target_tx, "recurring_transaction_id", None)
        if not rec_id:
            db.session.delete(target_tx)
            return

        if scope_value == "single":
            db.session.delete(target_tx)
            return

        if scope_value == "future":
            db.session.query(Transaction).filter(
                Transaction.user_id == int(user_id_int),
                Transaction.recurring_transaction_id == int(rec_id),
                Transaction.transaction_date >= target_tx.transaction_date,
            ).delete(synchronize_session=False)

            rec_tx = RecurringTransaction.query.filter_by(
                id=int(rec_id),
                user_id=int(user_id_int),
            ).first()
            if rec_tx and target_tx.transaction_date:
                rec_tx.end_date = _prev_month_last_day(target_tx.transaction_date)
            return

        if scope_value == "all":
            db.session.query(Transaction).filter(
                Transaction.user_id == int(user_id_int),
                Transaction.recurring_transaction_id == int(rec_id),
            ).delete(synchronize_session=False)

            rec_tx = RecurringTransaction.query.filter_by(
                id=int(rec_id),
                user_id=int(user_id_int),
            ).first()
            if rec_tx:
                rec_tx.is_active = False
            return

        # fallback
        db.session.delete(target_tx)

    try:
        _delete_recurring_scope(tx, scope)
        db.session.commit()
        print(f"[TX_REMOVE] Transação {tx_id} excluída com sucesso")
        resp = jsonify({"success": True})
        return _cors_wrap(resp, origin), 200
    except Exception as e:
        db.session.rollback()
        print(f"[TX_REMOVE] Erro ao excluir: {e}")
        resp = jsonify({"success": False, "message": f"Falha ao excluir transação: {e}"})
        return _cors_wrap(resp, origin), 500


@api_financeiro_bp.route("/api/dashboard", methods=["GET", "OPTIONS"])
def api_dashboard():
    """Retorna dados básicos do dashboard (ex: saldo total atual)."""
    origin = request.headers.get("Origin", "*")

    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, OPTIONS")

    user_id_int = _get_user_id_from_request()

    if not user_id_int:
        resp = jsonify({
            "success": False,
            "message": "Não autenticado",
        })
        return _cors_wrap(resp, origin), 401

    try:
        _ensure_finance_config_and_categories(user_id_int)
    except Exception:
        db.session.rollback()

    today = datetime.utcnow().date()
    try:
        year = int(request.args.get("year") or today.year)
        month = int(request.args.get("month") or today.month)
    except Exception:
        year = today.year
        month = today.month

    if month < 1 or month > 12:
        month = today.month
    
    # Gerar automaticamente as transações recorrentes do mês
    try:
        _generate_recurring_for_month(user_id_int, year, month)
    except Exception as e:
        print(f"[RECURRING] Erro ao gerar recorrentes: {e}")
        db.session.rollback()

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    # Totais do mês (pagos + pendentes) para os cards "Receitas" e "Gastos"
    month_income = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == user_id_int,
            Transaction.type == "income",
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
        .scalar()
    )
    month_expense = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == user_id_int,
            Transaction.type == "expense",
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
        .scalar()
    )

    # Totais pagos do mês para o "Saldo total atual"
    month_income_paid = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == user_id_int,
            Transaction.type == "income",
            Transaction.is_paid == True,
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
        .scalar()
    )
    month_expense_paid = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == user_id_int,
            Transaction.type == "expense",
            Transaction.is_paid == True,
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
        .scalar()
    )

    expense_by_category_rows = (
        db.session.query(
            Category.id,
            Category.name,
            Category.color,
            Category.icon,
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
        )
        .join(Category, Category.id == Transaction.category_id)
        .filter(
            Transaction.user_id == user_id_int,
            Transaction.type == "expense",
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
        .group_by(Category.id, Category.name, Category.color, Category.icon)
        .order_by(func.sum(Transaction.amount).desc())
        .limit(8)
        .all()
    )

    expense_by_category = []
    for cat_id, cat_name, cat_color, cat_icon, total in expense_by_category_rows:
        expense_by_category.append({
            "category_id": int(cat_id),
            "name": cat_name,
            "color": cat_color,
            "icon": cat_icon,
            "amount": float(total or 0),
        })

    month_income_f = float(month_income or 0)
    month_expense_f = float(month_expense or 0)
    month_income_paid_f = float(month_income_paid or 0)
    month_expense_paid_f = float(month_expense_paid or 0)

    # Saldo atual = apenas o que está efetivamente pago
    balance = month_income_paid_f - month_expense_paid_f

    latest_rows = (
        db.session.query(
            Transaction.id,
            Transaction.description,
            Transaction.amount,
            Transaction.type,
            Transaction.transaction_date,
            Transaction.is_paid,
            Transaction.is_recurring,
            Transaction.recurring_transaction_id,
            Category.name,
            Category.color,
            Category.icon,
        )
        .join(Category, Category.id == Transaction.category_id)
        .filter(
            Transaction.user_id == user_id_int,
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
        .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
        .limit(10)
        .all()
    )

    latest_transactions = []
    for tid, desc, amt, ttype, tdate, is_paid, is_rec, rec_id, cname, ccolor, cicon in latest_rows:
        latest_transactions.append({
            "id": int(tid),
            "description": desc,
            "amount": float(amt or 0),
            "type": ttype,
            "date": tdate.isoformat() if tdate else None,
            "is_paid": bool(is_paid),
            "is_recurring": bool(is_rec),
            "recurring_transaction_id": int(rec_id) if rec_id else None,
            "category": {
                "name": cname,
                "color": ccolor,
                "icon": cicon,
            },
        })

    resp = jsonify({
        "success": True,
        "balance": balance,
        "month": month,
        "year": year,
        "month_income": month_income_f,
        "month_expense": month_expense_f,
        "month_income_paid": month_income_paid_f,
        "month_expense_paid": month_expense_paid_f,
        "month_balance": month_income_f - month_expense_f,
        "expense_by_category": expense_by_category,
        "latest_transactions": latest_transactions,
    })
    return _cors_wrap(resp, origin), 200


@api_financeiro_bp.route("/api/categories", methods=["GET", "OPTIONS"])
def api_categories():
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, OPTIONS")

    user_id_int = _get_user_id_from_request()
    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    cfg = _ensure_finance_config_and_categories(user_id_int)
    cat_type = (request.args.get("type") or "").strip().lower() or None

    query = Category.query.filter_by(config_id=cfg.id, is_active=True)
    if cat_type in ("income", "expense"):
        query = query.filter_by(type=cat_type)

    cats = query.order_by(Category.type.asc(), Category.name.asc()).all()
    resp = jsonify({
        "success": True,
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "icon": c.icon,
                "color": c.color,
            }
            for c in cats
        ],
    })
    return _cors_wrap(resp, origin), 200


@api_financeiro_bp.route("/api/transactions", methods=["POST", "OPTIONS"])
def api_create_transaction():
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")

    user_id_int = session.get("finance_user_id")
    if not user_id_int:
        # fallback para app atual
        try:
            user_id_int = int((request.get_json(silent=True) or {}).get("user_id"))
        except Exception:
            user_id_int = None

    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    cfg = _ensure_finance_config_and_categories(int(user_id_int))

    data = request.get_json(silent=True) or {}
    ttype = str(data.get("type", "")).strip().lower()
    description = str(data.get("description", "")).strip()
    amount_raw = data.get("amount")
    category_text = str(data.get("category_text", "")).strip() or None
    date_raw = str(data.get("transaction_date", "")).strip()
    workspace_id_raw = data.get("workspace_id")
    
    # Campos adicionais
    payment_method = str(data.get("payment_method", "")).strip() or None
    notes = str(data.get("notes", "")).strip() or None
    is_paid = bool(data.get("is_paid", True))
    subcategory_text = str(data.get("subcategory_text", "")).strip() or None
    is_recurring = bool(data.get("is_recurring", False))
    recurring_day = data.get("recurring_day")  # Dia do vencimento (1-31)
    recurring_unlimited = data.get("recurring_unlimited")
    recurring_end_date_raw = str(data.get("recurring_end_date", "")).strip() or None

    if ttype not in ("income", "expense"):
        resp = jsonify({"success": False, "message": "Tipo inválido (income/expense)."})
        return _cors_wrap(resp, origin), 400

    if not description:
        resp = jsonify({"success": False, "message": "Descrição é obrigatória."})
        return _cors_wrap(resp, origin), 400

    try:
        amount = float(amount_raw)
    except Exception:
        amount = 0

    if amount <= 0:
        resp = jsonify({"success": False, "message": "Valor inválido."})
        return _cors_wrap(resp, origin), 400

    # Data base da transação
    try:
        if date_raw:
            tdate = date.fromisoformat(date_raw)
        else:
            tdate = datetime.utcnow().date()
    except Exception:
        tdate = datetime.utcnow().date()

    # Se for recorrente, usar apenas o dia do vencimento e ignorar a data enviada
    recurring_day_int = None
    if is_recurring:
        try:
            recurring_day_int = int(recurring_day)
        except Exception:
            recurring_day_int = None

        if not recurring_day_int or recurring_day_int < 1 or recurring_day_int > 31:
            resp = jsonify({"success": False, "message": "Dia de vencimento inválido (1-31)."})
            return _cors_wrap(resp, origin), 400

        last_day = calendar.monthrange(tdate.year, tdate.month)[1]
        day = min(recurring_day_int, last_day)
        tdate = date(tdate.year, tdate.month, day)

    # Buscar ou criar categoria baseada no texto
    category = None
    if category_text:
        # Tentar encontrar categoria existente (case-insensitive)
        category = Category.query.filter(
            func.lower(Category.name) == category_text.lower(),
            Category.config_id == cfg.id,
            Category.type == ttype
        ).first()
        
        # Se não existir, criar nova categoria
        if not category:
            category = Category(
                config_id=cfg.id,
                name=category_text,
                type=ttype,
                color="#64748B",  # Cor padrão cinza
                icon="📝",  # Ícone padrão
                is_default=False
            )
            db.session.add(category)
            db.session.flush()  # Para obter o ID
    
    # Fallback para categoria "Outros" se não tiver categoria
    if not category:
        category = Category.query.filter_by(config_id=cfg.id, type=ttype, name="Outros").first()
        if not category:
            resp = jsonify({"success": False, "message": "Categoria não encontrada."})
            return _cors_wrap(resp, origin), 400

    workspace_id = None
    try:
        if workspace_id_raw is not None:
            workspace_id = int(workspace_id_raw)
    except Exception:
        workspace_id = None

    recurring_tx = None
    if is_recurring:
        # Null = sem fim
        unlimited_bool = True
        if recurring_unlimited is not None:
            try:
                unlimited_bool = bool(recurring_unlimited)
            except Exception:
                unlimited_bool = True

        end_date = None
        if not unlimited_bool and recurring_end_date_raw:
            try:
                end_date = date.fromisoformat(recurring_end_date_raw)
            except Exception:
                end_date = None

        # start_date deve ser o primeiro dia do mês da transação
        start_date_first_day = date(tdate.year, tdate.month, 1)
        
        recurring_tx = RecurringTransaction(
            user_id=int(user_id_int),
            category_id=category.id,
            subcategory_id=None,
            subcategory_text=subcategory_text,
            description=description,
            amount=amount,
            type=ttype,
            frequency="monthly",
            day_of_month=recurring_day_int,
            start_date=start_date_first_day,
            end_date=end_date,
            is_active=True,
            payment_method=payment_method,
            notes=notes,
        )
        db.session.add(recurring_tx)
        db.session.flush()

    tx = Transaction(
        user_id=int(user_id_int),
        category_id=category.id,
        description=description,
        amount=amount,
        type=ttype,
        transaction_date=tdate,
        is_paid=is_paid,
        paid_date=tdate if is_paid else None,
        workspace_id=workspace_id,
        payment_method=payment_method,
        notes=notes,
        subcategory_text=subcategory_text,
        is_recurring=is_recurring,
        frequency="monthly" if is_recurring else "once",
        recurring_transaction_id=recurring_tx.id if recurring_tx else None,
    )

    db.session.add(tx)
    db.session.commit()

    resp = jsonify({
        "success": True,
        "transaction": {
            "id": tx.id,
            "description": tx.description,
            "amount": float(tx.amount or 0),
            "type": tx.type,
            "date": tx.transaction_date.isoformat() if tx.transaction_date else None,
            "category": {
                "id": category.id,
                "name": category.name,
                "color": category.color,
                "icon": category.icon,
            },
        },
    })
    return _cors_wrap(resp, origin), 201


@api_financeiro_bp.route("/api/transactions", methods=["GET", "OPTIONS"])
def api_list_transactions():
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, OPTIONS")

    user_id_int = _get_user_id_from_request()
    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    today = datetime.utcnow().date()
    try:
        year = int(request.args.get("year") or today.year)
        month = int(request.args.get("month") or today.month)
    except Exception:
        year = today.year
        month = today.month

    if month < 1 or month > 12:
        month = today.month

    tx_type = (request.args.get("type") or "").strip().lower()
    q = (request.args.get("q") or "").strip()

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    query = (
        db.session.query(
            Transaction.id,
            Transaction.description,
            Transaction.amount,
            Transaction.type,
            Transaction.transaction_date,
            Transaction.is_paid,
            Transaction.is_recurring,
            Category.id,
            Category.name,
            Category.color,
            Category.icon,
        )
        .join(Category, Category.id == Transaction.category_id)
        .filter(
            Transaction.user_id == int(user_id_int),
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
    )

    if tx_type in ("income", "expense"):
        query = query.filter(Transaction.type == tx_type)

    if q:
        query = query.filter(func.lower(Transaction.description).like(f"%{q.lower()}%"))

    rows = query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).all()

    items = []
    for tid, desc, amt, ttype, tdate, is_paid, is_recurring, cid, cname, ccolor, cicon in rows:
        items.append({
            "id": int(tid),
            "description": desc,
            "amount": float(amt or 0),
            "type": ttype,
            "date": tdate.isoformat() if tdate else None,
            "is_paid": bool(is_paid),
            "is_recurring": bool(is_recurring),
            "category": {
                "id": int(cid),
                "name": cname,
                "color": ccolor,
                "icon": cicon,
            },
        })

    resp = jsonify({
        "success": True,
        "year": year,
        "month": month,
        "transactions": items,
    })
    return _cors_wrap(resp, origin), 200


@api_financeiro_bp.route("/api/transactions/<int:tx_id>", methods=["GET", "PUT", "DELETE", "OPTIONS"])
def api_transaction_detail(tx_id: int):
    origin = request.headers.get("Origin", "*")
    print(f"[TX_DETAIL] {request.method} /api/transactions/{tx_id} - args: {dict(request.args)}")
    
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, PUT, DELETE, OPTIONS")

    user_id_int = session.get("finance_user_id")
    if not user_id_int:
        try:
            if request.method in ("GET", "DELETE"):
                raw_user_id = request.args.get("user_id")
                print(f"[TX_DETAIL] raw_user_id from args: {raw_user_id}")
                if not raw_user_id:
                    raw_user_id = (request.get_json(silent=True) or {}).get("user_id")
                    print(f"[TX_DETAIL] raw_user_id from body: {raw_user_id}")
                if raw_user_id:
                    user_id_int = int(raw_user_id)
            else:
                raw_user_id = (request.get_json(silent=True) or {}).get("user_id")
                print(f"[TX_DETAIL] raw_user_id from body: {raw_user_id}")
                if raw_user_id:
                    user_id_int = int(raw_user_id)
        except Exception as e:
            print(f"[TX_DETAIL] Erro ao parsear user_id: {e}")
            user_id_int = None

    print(f"[TX_DETAIL] user_id_int final: {user_id_int}")

    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    tx = Transaction.query.filter_by(id=tx_id, user_id=int(user_id_int)).first()
    print(f"[TX_DETAIL] Transaction found: {tx}")
    if not tx:
        resp = jsonify({"success": False, "message": "Transação não encontrada"})
        return _cors_wrap(resp, origin), 404

    if request.method == "DELETE":
        try:
            scope = (request.args.get("scope") or "single").strip().lower()

            def _prev_month_last_day(d: date) -> date:
                first = date(d.year, d.month, 1)
                prev_last = first - timedelta(days=1)
                return prev_last

            def _delete_recurring_scope(target_tx: Transaction, scope_value: str):
                rec_id = getattr(target_tx, "recurring_transaction_id", None)
                if not rec_id:
                    db.session.delete(target_tx)
                    return

                if scope_value == "single":
                    db.session.delete(target_tx)
                    return

                if scope_value == "future":
                    db.session.query(Transaction).filter(
                        Transaction.user_id == int(user_id_int),
                        Transaction.recurring_transaction_id == int(rec_id),
                        Transaction.transaction_date >= target_tx.transaction_date,
                    ).delete(synchronize_session=False)

                    rec_tx = RecurringTransaction.query.filter_by(
                        id=int(rec_id),
                        user_id=int(user_id_int),
                    ).first()
                    if rec_tx and target_tx.transaction_date:
                        rec_tx.end_date = _prev_month_last_day(target_tx.transaction_date)
                    return

                if scope_value == "all":
                    db.session.query(Transaction).filter(
                        Transaction.user_id == int(user_id_int),
                        Transaction.recurring_transaction_id == int(rec_id),
                    ).delete(synchronize_session=False)

                    rec_tx = RecurringTransaction.query.filter_by(
                        id=int(rec_id),
                        user_id=int(user_id_int),
                    ).first()
                    if rec_tx:
                        rec_tx.is_active = False
                    return

                db.session.delete(target_tx)

            _delete_recurring_scope(tx, scope)
            db.session.commit()
            resp = jsonify({"success": True})
            return _cors_wrap(resp, origin), 200
        except Exception as e:
            db.session.rollback()
            resp = jsonify({"success": False, "message": f"Falha ao excluir transação: {e}"})
            return _cors_wrap(resp, origin), 500

    if request.method == "GET":
        category = Category.query.filter_by(id=tx.category_id).first()
        rec_tx = None
        if tx.recurring_transaction_id:
            rec_tx = RecurringTransaction.query.filter_by(id=tx.recurring_transaction_id, user_id=int(user_id_int)).first()

        resp = jsonify({
            "success": True,
            "transaction": {
                "id": int(tx.id),
                "type": tx.type,
                "description": tx.description,
                "amount": float(tx.amount or 0),
                "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
                "is_paid": bool(tx.is_paid),
                "payment_method": tx.payment_method if tx.payment_method else None,
                "notes": tx.notes if tx.notes else None,
                "subcategory_text": tx.subcategory_text if tx.subcategory_text else None,
                "category_text": category.name if category else None,
                "category_id": int(tx.category_id) if tx.category_id else None,
                "is_recurring": bool(tx.is_recurring),
                "recurring_transaction_id": int(tx.recurring_transaction_id) if tx.recurring_transaction_id else None,
                "recurring_day": int(rec_tx.day_of_month) if rec_tx and rec_tx.day_of_month else (tx.transaction_date.day if tx.transaction_date else None),
                "recurring_unlimited": True if (rec_tx and rec_tx.end_date is None) else False,
                "recurring_end_date": rec_tx.end_date.isoformat() if (rec_tx and rec_tx.end_date) else None,
            },
        })
        return _cors_wrap(resp, origin), 200

    data = request.get_json(silent=True) or {}

    # Atualização parcial: permitir marcar/desmarcar como pago sem precisar reenviar
    # todos os campos obrigatórios (data/categoria/recorrência/etc.)
    # Suporta também um flag explícito (action=mark_paid / set_paid) para evitar cair em validações.
    if request.method == "PUT" and "is_paid" in data and (
        data.get("action") in ("mark_paid", "set_paid") or all(k in ("user_id", "is_paid") for k in data.keys())
    ):
        try:
            tx.is_paid = bool(data.get("is_paid"))
            tx.paid_date = datetime.utcnow().date() if tx.is_paid else None
            db.session.commit()
            resp = jsonify({
                "success": True,
                "transaction": {
                    "id": int(tx.id),
                    "is_paid": bool(tx.is_paid),
                    "paid_date": tx.paid_date.isoformat() if tx.paid_date else None,
                },
            })
            return _cors_wrap(resp, origin), 200
        except Exception as e:
            db.session.rollback()
            resp = jsonify({"success": False, "message": f"Falha ao atualizar pagamento: {e}"})
            return _cors_wrap(resp, origin), 500

    ttype = str(data.get("type", tx.type)).strip().lower()
    description = str(data.get("description", tx.description)).strip()
    amount_raw = data.get("amount", float(tx.amount or 0))
    category_text = str(data.get("category_text", "")).strip() or None
    date_raw = str(data.get("transaction_date", "")).strip() or None
    payment_method = str(data.get("payment_method", "")).strip() or None
    notes = str(data.get("notes", "")).strip() or None
    is_paid = bool(data.get("is_paid", tx.is_paid))
    subcategory_text = str(data.get("subcategory_text", "")).strip() or None
    is_recurring = bool(data.get("is_recurring", tx.is_recurring))
    recurring_day = data.get("recurring_day")
    recurring_unlimited = data.get("recurring_unlimited")
    recurring_end_date_raw = str(data.get("recurring_end_date", "")).strip() or None

    if ttype not in ("income", "expense"):
        resp = jsonify({"success": False, "message": "Tipo inválido (income/expense)."})
        return _cors_wrap(resp, origin), 400

    if not description:
        resp = jsonify({"success": False, "message": "Descrição é obrigatória."})
        return _cors_wrap(resp, origin), 400

    try:
        amount = float(amount_raw)
    except Exception:
        amount = 0
    if amount <= 0:
        resp = jsonify({"success": False, "message": "Valor inválido."})
        return _cors_wrap(resp, origin), 400

    try:
        if date_raw:
            tdate = date.fromisoformat(date_raw)
        else:
            tdate = tx.transaction_date
    except Exception:
        tdate = tx.transaction_date

    if not tdate:
        tdate = datetime.utcnow().date()

    recurring_day_int = None
    if is_recurring:
        try:
            recurring_day_int = int(recurring_day) if recurring_day is not None else None
        except Exception:
            recurring_day_int = None

        if not recurring_day_int or recurring_day_int < 1 or recurring_day_int > 31:
            resp = jsonify({"success": False, "message": "Dia de vencimento inválido (1-31)."})
            return _cors_wrap(resp, origin), 400

        last_day = calendar.monthrange(tdate.year, tdate.month)[1]
        day = min(recurring_day_int, last_day)
        tdate = date(tdate.year, tdate.month, day)

    cfg = _ensure_finance_config_and_categories(int(user_id_int))
    category = None
    if category_text:
        category = Category.query.filter(
            func.lower(Category.name) == category_text.lower(),
            Category.config_id == cfg.id,
            Category.type == ttype,
        ).first()

        if not category:
            category = Category(
                config_id=cfg.id,
                name=category_text,
                type=ttype,
                color="#64748B",
                icon="📝",
                is_default=False,
            )
            db.session.add(category)
            db.session.flush()

    if not category:
        category = Category.query.filter_by(config_id=cfg.id, type=ttype, name="Outros").first()
        if not category:
            resp = jsonify({"success": False, "message": "Categoria não encontrada."})
            return _cors_wrap(resp, origin), 400

    rec_tx = None
    if is_recurring:
        unlimited_bool = True
        if recurring_unlimited is not None:
            try:
                unlimited_bool = bool(recurring_unlimited)
            except Exception:
                unlimited_bool = True

        end_date = None
        if not unlimited_bool and recurring_end_date_raw:
            try:
                end_date = date.fromisoformat(recurring_end_date_raw)
            except Exception:
                end_date = None

        if tx.recurring_transaction_id:
            rec_tx = RecurringTransaction.query.filter_by(id=tx.recurring_transaction_id, user_id=int(user_id_int)).first()

        if not rec_tx:
            start_date_first_day = date(tdate.year, tdate.month, 1)
            rec_tx = RecurringTransaction(
                user_id=int(user_id_int),
                category_id=category.id,
                subcategory_id=None,
                subcategory_text=subcategory_text,
                description=description,
                amount=amount,
                type=ttype,
                frequency="monthly",
                day_of_month=recurring_day_int,
                start_date=start_date_first_day,
                end_date=end_date,
                is_active=True,
                payment_method=payment_method,
                notes=notes,
            )
            db.session.add(rec_tx)
            db.session.flush()
            tx.recurring_transaction_id = rec_tx.id

        if rec_tx:
            start_date_first_day = date(tdate.year, tdate.month, 1)
            if rec_tx.start_date is None or start_date_first_day < rec_tx.start_date:
                rec_tx.start_date = start_date_first_day
            rec_tx.end_date = end_date
            rec_tx.day_of_month = recurring_day_int
            rec_tx.category_id = category.id
            rec_tx.subcategory_text = subcategory_text
            rec_tx.description = description
            rec_tx.amount = amount
            rec_tx.type = ttype
            rec_tx.payment_method = payment_method
            rec_tx.notes = notes
            rec_tx.is_active = True

    if not is_recurring:
        tx.recurring_transaction_id = None

    tx.type = ttype
    tx.description = description
    tx.amount = amount
    tx.category_id = category.id
    tx.transaction_date = tdate
    tx.is_paid = is_paid
    tx.paid_date = tdate if is_paid else None
    tx.payment_method = payment_method
    tx.notes = notes
    tx.subcategory_text = subcategory_text
    tx.is_recurring = is_recurring
    tx.frequency = "monthly" if is_recurring else "once"

    db.session.commit()

    resp = jsonify({
        "success": True,
        "transaction": {
            "id": int(tx.id),
            "description": tx.description,
            "amount": float(tx.amount or 0),
            "type": tx.type,
            "date": tx.transaction_date.isoformat() if tx.transaction_date else None,
            "category": {
                "id": category.id,
                "name": category.name,
                "color": category.color,
                "icon": category.icon,
            },
        },
    })
    return _cors_wrap(resp, origin), 200


@api_financeiro_bp.route("/api/suggest-category", methods=["POST", "OPTIONS"])
def api_suggest_category():
    """Sugere categoria e subcategoria usando Groq AI baseado na descrição."""
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")

    user_id_int = session.get("finance_user_id")
    if not user_id_int:
        # fallback para app atual
        try:
            user_id_int = int((request.get_json(silent=True) or {}).get("user_id"))
        except Exception:
            user_id_int = None

    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    data = request.get_json(silent=True) or {}
    description = str(data.get("description", "")).strip()
    transaction_type = str(data.get("type", "expense")).strip().lower()

    if transaction_type not in ("income", "expense"):
        transaction_type = "expense"

    if not description:
        resp = jsonify({"success": False, "message": "Descrição é obrigatória"})
        return _cors_wrap(resp, origin), 400

    cfg = _ensure_finance_config_and_categories(int(user_id_int))
    
    # PRIMEIRO: Buscar transações similares no histórico do usuário
    similar_tx = Transaction.query.filter(
        Transaction.user_id == int(user_id_int),
        Transaction.type == transaction_type,
        func.lower(Transaction.description).like(f"%{description.lower()}%")
    ).order_by(Transaction.created_at.desc()).first()
    
    # Se encontrou transação similar, reutilizar categoria e subcategoria
    if similar_tx and similar_tx.category_id:
        category = Category.query.get(similar_tx.category_id)
        if category:
            resp = jsonify({
                "success": True,
                "category": category.name,
                "category_id": category.id,
                "subcategory": similar_tx.subcategory_text,
                "confidence": "high",
                "source": "history"
            })
            return _cors_wrap(resp, origin), 200
    
    # Se não encontrou no histórico, usar IA
    categories = Category.query.filter_by(config_id=cfg.id, type=transaction_type).all()
    category_names = [c.name for c in categories]

    def _fallback_category_name() -> str:
        if not category_names:
            return "Outros"
        other = next((n for n in category_names if n.strip().lower() == "outros"), None)
        return other or category_names[0]

    # Chamar Groq API
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    print(f"[GROQ] API Key presente: {bool(groq_api_key)}")
    print(f"[GROQ] Descrição: {description}")
    print(f"[GROQ] Tipo: {transaction_type}")
    
    if not groq_api_key:
        print("[GROQ] ERRO: API Key não encontrada")
        resp = jsonify({
            "success": False,
            "message": "IA não configurada (GROQ_API_KEY ausente). Preencha manualmente.",
        })
        return _cors_wrap(resp, origin), 503

    try:
        prompt = f"""Analise esta transação e retorne JSON:

Descrição: "{description}"
Tipo: {"despesa" if transaction_type == "expense" else "receita"}

Categorias: {', '.join(category_names)}

Retorne APENAS JSON:
{{
  "category": "categoria_da_lista",
  "subcategory": "subcategoria_especifica"
}}

Escolha a melhor categoria da lista."""

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 100
            },
            timeout=5
        )

        print(f"[GROQ] Status da resposta: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"[GROQ] Resposta da IA: {content}")
            
            # Limpar markdown code blocks se houver
            content_clean = content.strip()
            if content_clean.startswith("```json"):
                content_clean = content_clean[7:]  # Remove ```json
            if content_clean.startswith("```"):
                content_clean = content_clean[3:]  # Remove ```
            if content_clean.endswith("```"):
                content_clean = content_clean[:-3]  # Remove ```
            content_clean = content_clean.strip()
            
            print(f"[GROQ] JSON limpo: {content_clean}")
            
            # Tentar parsear JSON da resposta
            import json
            try:
                suggestion = json.loads(content_clean)
                suggested_category = suggestion.get("category", "Outros")
                suggested_subcategory = suggestion.get("subcategory")
                
                print(f"[GROQ] Categoria sugerida: {suggested_category}")
                print(f"[GROQ] Subcategoria sugerida: {suggested_subcategory}")
                
                # Validar se categoria existe
                matched_cat = next((c for c in categories if c.name.lower() == suggested_category.lower()), None)
                
                if matched_cat:
                    # Regra de negócio: salário não usa subcategoria (usa campo "De quem é o salário?" no app)
                    if matched_cat.name.strip().lower() in ("salário", "salario"):
                        suggested_subcategory = None

                    resp = jsonify({
                        "success": True,
                        "category": matched_cat.name,
                        "category_id": matched_cat.id,
                        "subcategory": suggested_subcategory,
                        "confidence": "high",
                        "source": "ai"
                    })
                    return _cors_wrap(resp, origin), 200
                else:
                    print(f"[GROQ] Categoria '{suggested_category}' não encontrada nas disponíveis")
            except json.JSONDecodeError as e:
                print(f"[GROQ] Erro ao parsear JSON: {e}")
                pass
        else:
            print(f"[GROQ] Erro na API: {response.text}")

    except Exception as e:
        print(f"[GROQ ERROR] Exceção: {e}")
        import traceback
        print(f"[GROQ ERROR] Traceback: {traceback.format_exc()}")

    # Se chegou aqui, houve erro: retornar erro e deixar o app liberar entrada manual
    print("[GROQ] Falha ao gerar categoria")
    resp = jsonify({
        "success": False,
        "message": "Não foi possível gerar categoria. Preencha manualmente.",
    })
    return _cors_wrap(resp, origin), 500


@api_financeiro_bp.route("/api/register", methods=["POST", "OPTIONS"])
@api_financeiro_bp.route("/api/register/", methods=["POST", "OPTIONS"])
def api_register():
    """
    Endpoint de registro para clientes API (Flutter).
    
    POST /gerenciamento-financeiro/api/register
    Body (form-urlencoded ou JSON): 
    {
        "name": "...",  # opcional (não usado no backend atual)
        "email": "...",
        "password": "...",
        "confirm_password": "..."
    }
    
    Retorna:
    - 200: {"success": true, "message": "Conta criada com sucesso"}
    - 400: {"success": false, "message": "..."}
    """
    
    # CORS
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    
    # Aceitar tanto JSON quanto form-urlencoded
    if request.is_json:
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        confirm = str(data.get("confirm_password", ""))
    else:
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
    
    # Validações
    if not email or not password:
        resp = jsonify({
            "success": False,
            "message": "Preencha todos os campos.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 400
    
    if "@" not in email:
        resp = jsonify({
            "success": False,
            "message": "E-mail inválido.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 400
    
    if password != confirm:
        resp = jsonify({
            "success": False,
            "message": "As senhas não coincidem.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 400
    
    if len(password) < 6:
        resp = jsonify({
            "success": False,
            "message": "Use uma senha com pelo menos 6 caracteres.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 400
    
    # Verificar se já existe
    exists = User.query.filter(func.lower(User.email) == email).first()
    if exists:
        resp = jsonify({
            "success": False,
            "message": "Este e-mail já está cadastrado.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 400
    
    try:
        # Criar usuário
        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.flush()
        
        # Criar workspace padrão
        default_workspace = Workspace(
            owner_id=user.id,
            name="Meu Workspace",
            description="Workspace padrão",
            color="#3b82f6"
        )
        db.session.add(default_workspace)
        db.session.commit()
        
        resp = jsonify({
            "success": True,
            "message": "Conta criada com sucesso! Faça login para continuar.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 200
        
    except Exception as e:
        db.session.rollback()
        resp = jsonify({
            "success": False,
            "message": "Erro ao criar conta. Tente novamente.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 500


@api_financeiro_bp.route("/api/logout", methods=["POST", "OPTIONS"])
def api_logout():
    """Logout da sessão"""
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    
    session.clear()
    
    resp = jsonify({
        "success": True,
        "message": "Logout realizado com sucesso",
    })
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp, 200


@api_financeiro_bp.route("/api/me", methods=["GET", "OPTIONS"])
def api_me():
    """Retorna dados do usuário logado"""
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    
    user_id = session.get("finance_user_id")
    
    if not user_id:
        resp = jsonify({
            "success": False,
            "message": "Não autenticado",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401
    
    user = User.query.get(user_id)
    
    if not user:
        resp = jsonify({
            "success": False,
            "message": "Usuário não encontrado",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 404
    
    resp = jsonify({
        "success": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "is_email_verified": user.is_email_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
    })
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp, 200


# Registrar rotas de comprovantes
from .attachments_endpoints import register_attachment_routes
register_attachment_routes(api_financeiro_bp)

"""
API REST para Aplicativo Mobile (Flutter) - Gerenciamento Financeiro
=====================================================================

Endpoints JSON para autenticação e operações financeiras via app mobile.
"""

from flask import Blueprint, request, jsonify, session, current_app
from sqlalchemy import func, case, or_
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta, date
import math
import random
import os
import json
import requests
import calendar
import re
import secrets

from extensions import db
from models import User, Workspace, WorkspaceMember, WorkspaceInvite, EmailVerification, LoginAudit, Transaction, Category, FinanceConfig, RecurringTransaction, TransactionAttachment, Budget, SavingsPot, SavingsPotContribution
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename
from email_service import send_workspace_invitation

# Blueprint da API
api_financeiro_bp = Blueprint(
    "api_financeiro",
    __name__,
)

_DEBUG = False

_PLANNING_TABLES_READY = False


def _dbg(msg: str):
    if _DEBUG:
        print(msg)


def _strip_installment_suffix(desc: str | None) -> str:
    try:
        s = str(desc or "").strip()
        if not s:
            return ""
        return re.sub(r"\s*\(\s*\d+\s*/\s*\d+\s*\)\s*$", "", s).strip()
    except Exception:
        return str(desc or "").strip()


def _shift_month_simple(y: int, m: int, delta: int) -> tuple[int, int]:
    total = (int(y) * 12) + (int(m) - 1) + int(delta)
    ny = total // 12
    nm = (total % 12) + 1
    return int(ny), int(nm)


def _month_index(y: int, m: int) -> int:
    return (int(y) * 12) + (int(m) - 1)


def _months_diff(y1: int, m1: int, y2: int, m2: int) -> int:
    return _month_index(y2, m2) - _month_index(y1, m1)


def _last_day_of_month(y: int, m: int) -> date:
    last = calendar.monthrange(int(y), int(m))[1]
    return date(int(y), int(m), int(last))


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


def _ensure_planning_tables():
    global _PLANNING_TABLES_READY
    if _PLANNING_TABLES_READY:
        return True
    try:
        db.create_all()
        _PLANNING_TABLES_READY = True
        return True
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def _get_workspace_role(user_id: int, workspace_id: int):
    w = Workspace.query.get(workspace_id)
    if not w:
        return None
    if int(w.owner_id) == int(user_id):
        return "owner"
    member = WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=user_id).first()
    if not member:
        return None
    try:
        return (member.role or "viewer").strip().lower()
    except Exception:
        return "viewer"


def _can_edit_workspace(user_id: int, workspace_id: int) -> bool:
    role = _get_workspace_role(user_id, workspace_id)
    return role in ("owner", "editor")


def _require_active_workspace_or_400(user_id_int: int):
    origin = request.headers.get("Origin", "*")

    workspace_id_hint = None
    try:
        workspace_id_hint = request.args.get("workspace_id")
        if workspace_id_hint:
            workspace_id_hint = int(workspace_id_hint)
    except Exception:
        workspace_id_hint = None

    if request.method in ("POST", "PUT") and request.is_json:
        try:
            body = request.get_json(silent=True) or {}
            if not workspace_id_hint and body.get("workspace_id") is not None:
                workspace_id_hint = int(body.get("workspace_id"))
        except Exception:
            pass

    if not workspace_id_hint:
        owned_ids = [w.id for w in Workspace.query.filter_by(owner_id=user_id_int).all()]
        member_ids = [m.workspace_id for m in WorkspaceMember.query.filter_by(user_id=user_id_int).all()]
        if len(set(owned_ids + member_ids)) > 1:
            resp = jsonify({"success": False, "message": "workspace_id obrigatório"})
            return None, (_cors_wrap(resp, origin), 400)

    active_workspace_id = _get_active_workspace_for_user(user_id_int, workspace_id_hint)
    if not active_workspace_id:
        resp = jsonify({"success": False, "message": "workspace_id obrigatório"})
        return None, (_cors_wrap(resp, origin), 400)

    share_prefs = _check_user_share_preferences(user_id_int, active_workspace_id)
    if not share_prefs:
        resp = jsonify({"success": False, "message": "Sem permissão para acessar este workspace"})
        return None, (_cors_wrap(resp, origin), 403)

    session[f"active_workspace_{user_id_int}"] = active_workspace_id
    return active_workspace_id, None


@api_financeiro_bp.route("/api/budgets", methods=["GET", "POST", "OPTIONS"])
def api_budgets():
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, POST, OPTIONS")

    user_id_int = _get_user_id_from_request()
    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    if not _ensure_planning_tables():
        resp = jsonify({"success": False, "message": "Erro ao preparar tabelas de planejamento"})
        return _cors_wrap(resp, origin), 500

    active_workspace_id, err = _require_active_workspace_or_400(user_id_int)
    if err:
        return err

    share_prefs = _check_user_share_preferences(user_id_int, active_workspace_id) or {}

    today = datetime.utcnow().date()
    try:
        year = int(request.args.get("year") or today.year)
        month = int(request.args.get("month") or today.month)
    except Exception:
        year = today.year
        month = today.month

    period = (request.args.get("period") or "monthly").strip().lower()
    if period not in ("monthly", "yearly"):
        period = "monthly"

    if request.method == "GET":
        if period == "yearly":
            start = date(year, 1, 1)
            end = date(year + 1, 1, 1)
            month_key = 0
        else:
            start = date(year, month, 1)
            if month == 12:
                end = date(year + 1, 1, 1)
            else:
                end = date(year, month + 1, 1)
            month_key = month

        budgets = Budget.query.filter_by(
            workspace_id=active_workspace_id,
            period=period,
            year=year,
            month=month_key,
        ).all()

        cat_ids = [b.category_id for b in budgets]
        spent_map = {}
        if cat_ids:
            tx_filters = [
                Transaction.workspace_id == active_workspace_id,
                Transaction.type == "expense",
                Transaction.is_paid == True,
                Transaction.transaction_date >= start,
                Transaction.transaction_date < end,
                Transaction.category_id.in_(cat_ids),
            ]

            if share_prefs.get("share_transactions") is False:
                tx_filters.append(Transaction.user_id == user_id_int)

            spent_rows = db.session.query(
                Transaction.category_id,
                func.coalesce(func.sum(Transaction.amount), 0).label("spent"),
            ).filter(*tx_filters).group_by(Transaction.category_id).all()
            for cid, spent in spent_rows:
                try:
                    spent_map[int(cid)] = float(spent or 0)
                except Exception:
                    spent_map[int(cid)] = 0.0

        items = []
        for b in budgets:
            limit_v = float(b.limit_amount or 0)
            spent_v = float(spent_map.get(int(b.category_id), 0.0))
            pct = 0.0
            if limit_v > 0:
                pct = spent_v / limit_v
            alert = "ok"
            if limit_v > 0 and pct >= 1:
                alert = "over_limit"
            elif limit_v > 0 and pct >= 0.8:
                alert = "near_limit"

            items.append({
                "id": int(b.id),
                "category_id": int(b.category_id),
                "category": {
                    "name": b.category.name if b.category else None,
                    "color": b.category.color if b.category else None,
                    "icon": b.category.icon if b.category else None,
                },
                "period": b.period,
                "year": int(b.year),
                "month": int(b.month),
                "limit_amount": limit_v,
                "spent_amount": spent_v,
                "remaining_amount": (limit_v - spent_v),
                "percent_used": pct,
                "alert": alert,
            })

        resp = jsonify({
            "success": True,
            "workspace_id": int(active_workspace_id),
            "period": period,
            "year": year,
            "month": month if period == "monthly" else None,
            "budgets": items,
        })
        return _cors_wrap(resp, origin), 200

    if not _can_edit_workspace(user_id_int, active_workspace_id):
        resp = jsonify({"success": False, "message": "Sem permissão para editar planejamento"})
        return _cors_wrap(resp, origin), 403

    data = request.get_json(silent=True) or {}
    category_id = None
    try:
        if data.get("category_id") is not None and str(data.get("category_id")).strip() != "":
            category_id = int(data.get("category_id"))
    except Exception:
        category_id = None

    category_text = str(data.get("category_text") or "").strip() or None

    try:
        limit_amount = float(data.get("limit_amount"))
    except Exception:
        resp = jsonify({"success": False, "message": "Parâmetros inválidos"})
        return _cors_wrap(resp, origin), 400

    if not category_id and not category_text:
        resp = jsonify({"success": False, "message": "Categoria é obrigatória"})
        return _cors_wrap(resp, origin), 400

    period_body = (data.get("period") or period or "monthly").strip().lower()
    if period_body not in ("monthly", "yearly"):
        period_body = "monthly"

    try:
        year_body = int(data.get("year") or year)
    except Exception:
        year_body = year

    month_body = 0
    if period_body == "monthly":
        try:
            month_body = int(data.get("month") or month)
        except Exception:
            month_body = month
        if month_body < 1 or month_body > 12:
            month_body = month

    if limit_amount <= 0:
        resp = jsonify({"success": False, "message": "Limite inválido"})
        return _cors_wrap(resp, origin), 400

    category = None
    if category_id:
        category = Category.query.get(category_id)

    if not category and category_text:
        # Tentar reutilizar categoria existente no workspace (evita duplicatas entre membros)
        cfg_ids = []
        try:
            w = Workspace.query.get(active_workspace_id)
            member_ids = []
            if w:
                member_ids.append(int(w.owner_id))
            for m in WorkspaceMember.query.filter_by(workspace_id=active_workspace_id).all():
                try:
                    member_ids.append(int(m.user_id))
                except Exception:
                    pass
            member_ids = list(set(member_ids))

            for uid in member_ids:
                c = FinanceConfig.query.filter_by(user_id=uid).first()
                if c:
                    cfg_ids.append(int(c.id))
        except Exception:
            cfg_ids = []

        if cfg_ids:
            category = Category.query.filter(
                func.lower(Category.name) == category_text.lower(),
                Category.config_id.in_(cfg_ids),
                Category.type == "expense",
                Category.is_active.is_(True),
            ).first()

        # Se não encontrou no workspace, criar no config do usuário atual
        if not category:
            cfg = _ensure_finance_config_and_categories(user_id_int)
            category = Category.query.filter(
                func.lower(Category.name) == category_text.lower(),
                Category.config_id == cfg.id,
                Category.type == "expense",
            ).first()
            if not category:
                category = Category(
                    config_id=cfg.id,
                    name=category_text,
                    type="expense",
                    color="#64748B",
                    icon="📝",
                    is_default=False,
                    is_active=True,
                )
                db.session.add(category)
                db.session.flush()

    if not category:
        resp = jsonify({"success": False, "message": "Categoria não encontrada"})
        return _cors_wrap(resp, origin), 400

    category_id = int(category.id)

    existing = Budget.query.filter_by(
        workspace_id=active_workspace_id,
        category_id=category_id,
        period=period_body,
        year=year_body,
        month=month_body,
    ).first()

    try:
        if existing:
            existing.limit_amount = limit_amount
            db.session.commit()
            resp = jsonify({"success": True, "budget_id": int(existing.id), "updated": True})
            return _cors_wrap(resp, origin), 200

        b = Budget(
            workspace_id=active_workspace_id,
            created_by_user_id=user_id_int,
            category_id=category_id,
            period=period_body,
            year=year_body,
            month=month_body,
            limit_amount=limit_amount,
        )
        db.session.add(b)
        db.session.commit()
        resp = jsonify({"success": True, "budget_id": int(b.id), "created": True})
        return _cors_wrap(resp, origin), 201
    except Exception:
        db.session.rollback()
        resp = jsonify({"success": False, "message": "Erro ao salvar orçamento"})
        return _cors_wrap(resp, origin), 500


@api_financeiro_bp.route("/api/budgets/<int:budget_id>", methods=["DELETE", "OPTIONS"])
def api_delete_budget(budget_id: int):
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "DELETE, OPTIONS")

    user_id_int = _get_user_id_from_request()
    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    if not _ensure_planning_tables():
        resp = jsonify({"success": False, "message": "Erro ao preparar tabelas de planejamento"})
        return _cors_wrap(resp, origin), 500

    active_workspace_id, err = _require_active_workspace_or_400(user_id_int)
    if err:
        return err

    if not _can_edit_workspace(user_id_int, active_workspace_id):
        resp = jsonify({"success": False, "message": "Sem permissão para editar planejamento"})
        return _cors_wrap(resp, origin), 403

    b = Budget.query.filter_by(id=budget_id, workspace_id=active_workspace_id).first()
    if not b:
        resp = jsonify({"success": False, "message": "Orçamento não encontrado"})
        return _cors_wrap(resp, origin), 404

    try:
        db.session.delete(b)
        db.session.commit()
        resp = jsonify({"success": True})
        return _cors_wrap(resp, origin), 200
    except Exception:
        db.session.rollback()
        resp = jsonify({"success": False, "message": "Erro ao excluir orçamento"})
        return _cors_wrap(resp, origin), 500


@api_financeiro_bp.route("/api/savings-pots", methods=["GET", "POST", "OPTIONS"])
def api_savings_pots():
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, POST, OPTIONS")

    user_id_int = _get_user_id_from_request()
    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    if not _ensure_planning_tables():
        resp = jsonify({"success": False, "message": "Erro ao preparar tabelas de planejamento"})
        return _cors_wrap(resp, origin), 500

    active_workspace_id, err = _require_active_workspace_or_400(user_id_int)
    if err:
        return err

    today = datetime.utcnow().date()

    if request.method == "GET":
        kind = (request.args.get("kind") or "").strip().lower() or None
        include_archived = (request.args.get("include_archived") or "0").strip() == "1"

        query = SavingsPot.query.filter_by(workspace_id=active_workspace_id)
        if not include_archived:
            query = query.filter_by(is_archived=False)
        if kind in ("pot", "purchase"):
            query = query.filter_by(kind=kind)

        pots = query.order_by(SavingsPot.created_at.desc()).all()
        pot_ids = [p.id for p in pots]

        totals = {}
        if pot_ids:
            rows = db.session.query(
                SavingsPotContribution.pot_id,
                func.coalesce(func.sum(SavingsPotContribution.amount), 0).label("total"),
            ).filter(SavingsPotContribution.pot_id.in_(pot_ids)).group_by(SavingsPotContribution.pot_id).all()
            for pid, total in rows:
                try:
                    totals[int(pid)] = float(total or 0)
                except Exception:
                    totals[int(pid)] = 0.0

        items = []
        for p in pots:
            saved = float(totals.get(int(p.id), 0.0))
            target = float(p.target_amount or 0)
            progress = 0.0
            if target > 0:
                progress = min(1.0, saved / target)

            xp = int(saved / 50)
            level = int(xp / 10) + 1
            next_level_xp = level * 10
            level_progress = 0.0
            if next_level_xp > 0:
                level_progress = (xp % 10) / 10.0

            days_left = None
            recommended_monthly = None
            if p.due_date and target > 0:
                try:
                    days_left = int((p.due_date - today).days)
                    if days_left > 0:
                        months_left = max(1, int(math.ceil(days_left / 30.0)))
                        recommended_monthly = float((target - saved) / months_left)
                except Exception:
                    days_left = None

            items.append({
                "id": int(p.id),
                "name": p.name,
                "kind": p.kind,
                "target_amount": target,
                "saved_amount": saved,
                "progress": progress,
                "due_date": p.due_date.isoformat() if p.due_date else None,
                "days_left": days_left,
                "recommended_monthly": recommended_monthly,
                "gamification": {
                    "xp": xp,
                    "level": level,
                    "level_progress": level_progress,
                    "next_level_xp": next_level_xp,
                },
                "is_archived": bool(p.is_archived),
            })

        resp = jsonify({"success": True, "workspace_id": int(active_workspace_id), "pots": items})
        return _cors_wrap(resp, origin), 200

    if not _can_edit_workspace(user_id_int, active_workspace_id):
        resp = jsonify({"success": False, "message": "Sem permissão para editar planejamento"})
        return _cors_wrap(resp, origin), 403

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    kind = str(data.get("kind") or "pot").strip().lower()
    if kind not in ("pot", "purchase"):
        kind = "pot"

    if not name:
        resp = jsonify({"success": False, "message": "Nome é obrigatório"})
        return _cors_wrap(resp, origin), 400

    target_amount = None
    try:
        if data.get("target_amount") is not None and str(data.get("target_amount")).strip() != "":
            target_amount = float(data.get("target_amount"))
    except Exception:
        target_amount = None

    due_date = None
    due_date_raw = str(data.get("due_date") or "").strip() or None
    if due_date_raw:
        try:
            due_date = date.fromisoformat(due_date_raw)
        except Exception:
            due_date = None

    try:
        pot = SavingsPot(
            workspace_id=active_workspace_id,
            created_by_user_id=user_id_int,
            name=name,
            kind=kind,
            target_amount=target_amount,
            due_date=due_date,
        )
        db.session.add(pot)
        db.session.commit()
        resp = jsonify({"success": True, "pot_id": int(pot.id)})
        return _cors_wrap(resp, origin), 201
    except Exception:
        db.session.rollback()
        resp = jsonify({"success": False, "message": "Erro ao criar cofrinho/meta"})
        return _cors_wrap(resp, origin), 500


@api_financeiro_bp.route("/api/savings-pots/<int:pot_id>/contributions", methods=["POST", "OPTIONS"])
def api_savings_pot_contribution(pot_id: int):
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")

    user_id_int = _get_user_id_from_request()
    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    if not _ensure_planning_tables():
        resp = jsonify({"success": False, "message": "Erro ao preparar tabelas de planejamento"})
        return _cors_wrap(resp, origin), 500

    active_workspace_id, err = _require_active_workspace_or_400(user_id_int)
    if err:
        return err

    if not _can_edit_workspace(user_id_int, active_workspace_id):
        resp = jsonify({"success": False, "message": "Sem permissão para editar planejamento"})
        return _cors_wrap(resp, origin), 403

    pot = SavingsPot.query.filter_by(id=pot_id, workspace_id=active_workspace_id).first()
    if not pot:
        resp = jsonify({"success": False, "message": "Cofrinho/meta não encontrado"})
        return _cors_wrap(resp, origin), 404

    data = request.get_json(silent=True) or {}
    try:
        amount = float(data.get("amount"))
    except Exception:
        amount = 0
    if amount <= 0:
        resp = jsonify({"success": False, "message": "Valor inválido"})
        return _cors_wrap(resp, origin), 400

    cdate = datetime.utcnow().date()
    date_raw = str(data.get("date") or "").strip() or None
    if date_raw:
        try:
            cdate = date.fromisoformat(date_raw)
        except Exception:
            cdate = datetime.utcnow().date()

    try:
        contrib = SavingsPotContribution(
            pot_id=pot.id,
            user_id=user_id_int,
            amount=amount,
            contribution_date=cdate,
        )
        db.session.add(contrib)
        db.session.commit()
        resp = jsonify({"success": True, "contribution_id": int(contrib.id)})
        return _cors_wrap(resp, origin), 201
    except Exception:
        db.session.rollback()
        resp = jsonify({"success": False, "message": "Erro ao adicionar aporte"})
        return _cors_wrap(resp, origin), 500


@api_financeiro_bp.route("/api/savings-pots/<int:pot_id>", methods=["DELETE", "OPTIONS"])
def api_delete_savings_pot(pot_id: int):
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "DELETE, OPTIONS")

    user_id_int = _get_user_id_from_request()
    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    if not _ensure_planning_tables():
        resp = jsonify({"success": False, "message": "Erro ao preparar tabelas de planejamento"})
        return _cors_wrap(resp, origin), 500

    active_workspace_id, err = _require_active_workspace_or_400(user_id_int)
    if err:
        return err

    if not _can_edit_workspace(user_id_int, active_workspace_id):
        resp = jsonify({"success": False, "message": "Sem permissão para editar planejamento"})
        return _cors_wrap(resp, origin), 403

    pot = SavingsPot.query.filter_by(id=pot_id, workspace_id=active_workspace_id).first()
    if not pot:
        resp = jsonify({"success": False, "message": "Cofrinho/meta não encontrado"})
        return _cors_wrap(resp, origin), 404

    try:
        db.session.delete(pot)
        db.session.commit()
        resp = jsonify({"success": True})
        return _cors_wrap(resp, origin), 200
    except Exception:
        db.session.rollback()
        resp = jsonify({"success": False, "message": "Erro ao excluir"})
        return _cors_wrap(resp, origin), 500


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
    
    # Para requisições POST, também verificar no body JSON
    body_user_id = None
    if request.method == "POST" and request.is_json:
        try:
            data = request.get_json() or {}
            body_user_id = data.get("user_id")
        except Exception:
            pass
    
    user_id = session_user_id or request_user_id or body_user_id
    try:
        return int(user_id) if user_id is not None else None
    except Exception:
        return None


def _get_active_workspace_for_user(user_id: int, workspace_id_hint: int = None):
    """
    Determina o workspace ativo para um usuário de forma consistente.
    Prioriza workspace_id do request, depois workspace salvo em sessão.
    Para evitar vazamento/mistura de dados entre workspaces, não tenta
    "adivinhar" um workspace quando há múltiplas opções.
    """
    # 1. Se workspace_id foi fornecido no request, verificar se usuário tem acesso
    if workspace_id_hint:
        workspace = Workspace.query.get(workspace_id_hint)
        if workspace:
            # Verificar se usuário tem acesso (owner ou membro)
            is_owner = workspace.owner_id == user_id
            is_member = WorkspaceMember.query.filter_by(
                workspace_id=workspace_id_hint, user_id=user_id
            ).first()
            if is_owner or is_member:
                return workspace_id_hint

    # 2. Se há workspace ativo na sessão, respeitar (se usuário tem acesso)
    active_from_session = session.get(f"active_workspace_{user_id}")
    if active_from_session:
        try:
            active_from_session = int(active_from_session)
        except Exception:
            active_from_session = None

    if active_from_session:
        w = Workspace.query.get(active_from_session)
        if w:
            is_owner = w.owner_id == user_id
            is_member = WorkspaceMember.query.filter_by(
                workspace_id=active_from_session, user_id=user_id
            ).first()
            if is_owner or is_member:
                return active_from_session
    
    # 3. Buscar workspaces do usuário (owner + membro)
    owned_workspaces = Workspace.query.filter_by(owner_id=user_id).all()
    member_links = WorkspaceMember.query.filter_by(user_id=user_id).all()
    
    # Se tem apenas um workspace (owner ou membro), usar esse
    all_workspace_ids = [w.id for w in owned_workspaces] + [m.workspace_id for m in member_links]
    unique_workspace_ids = list(set(all_workspace_ids))
    
    if len(unique_workspace_ids) == 1:
        return unique_workspace_ids[0]

    # 4. Se há múltiplos workspaces e nenhum foi especificado (hint/sessão),
    # não escolher arbitrariamente para evitar misturar dados.
    return None


def _check_user_share_preferences(user_id: int, workspace_id: int):
    """
    Verifica as preferências de compartilhamento do usuário.
    Retorna dict com permissões ou None se usuário é owner.
    """
    workspace = Workspace.query.get(workspace_id)
    if not workspace:
        return None
    
    # Se é owner, tem acesso total
    if workspace.owner_id == user_id:
        return {'share_transactions': True, 'share_categories': True}
    
    # Se é membro, verificar preferências
    member = WorkspaceMember.query.filter_by(
        workspace_id=workspace_id, user_id=user_id
    ).first()
    
    if not member:
        return None

    prefs = member.share_preferences or {}
    # Retornar preferências com defaults (sempre dict truthy)
    return {
        'share_transactions': True,
        'share_categories': True,
        **prefs,
    }


def api_sync_workspace_context(workspace_id: int, requesting_user_id: int):
    """
    Sincroniza o contexto de workspace para todos os membros online.
    Define o mesmo workspace ativo para todos os usuários do workspace.
    """
    try:
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            return False
        
        # Verificar se usuário solicitante tem acesso
        is_owner = workspace.owner_id == requesting_user_id
        is_member = WorkspaceMember.query.filter_by(
            workspace_id=workspace_id, user_id=requesting_user_id
        ).first()
        
        if not (is_owner or is_member):
            return False
        
        # Buscar todos os membros do workspace
        all_member_ids = [workspace.owner_id]
        members = WorkspaceMember.query.filter_by(workspace_id=workspace_id).all()
        all_member_ids.extend([m.user_id for m in members])
        
        # Atualizar sessão para todos os membros (simulação - em produção seria via WebSocket/Redis)
        # Por enquanto, apenas loggar a ação
        _dbg(f"[SYNC_WORKSPACE] Sincronizando workspace {workspace_id} para usuários: {all_member_ids}")
        
        return True
    except Exception as e:
        _dbg(f"[SYNC_WORKSPACE] Erro: {e}")
        return False


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

    _dbg(f"[MIGRATE_RECURRING] Encontradas {len(legacy)} transações recorrentes antigas para migrar")

    if not legacy:
        return

    cache: dict[tuple, RecurringTransaction] = {}

    for tx in legacy:
        if not tx.transaction_date:
            continue
        
        # Buscar transações antigas não vinculadas que correspondem a esta recorrente
        unlinked_txs = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.is_recurring.is_(True),
            Transaction.recurring_transaction_id.is_(None),
            Transaction.description == tx.description,
            Transaction.type == tx.type,
            Transaction.amount == tx.amount
        ).all()
        
        if unlinked_txs:
            _dbg(f"[MIGRATE_RECURRING] {tx.description}: encontradas {len(unlinked_txs)} transações não vinculadas")
            for utx in unlinked_txs:
                _dbg(f"[MIGRATE_RECURRING]   - Vinculando {utx.description} de {utx.transaction_date}")
                utx.recurring_transaction_id = tx.id
                utx.frequency = "monthly"
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        
        # Buscar TODAS as transações vinculadas para debug
        all_txs = Transaction.query.filter_by(
            user_id=user_id,
            recurring_transaction_id=tx.id
        ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc()).all()
        
        _dbg(f"[MIGRATE_RECURRING] {tx.description}: {len(all_txs)} transações vinculadas, start_date atual: {tx.start_date}")
        for atx in all_txs:
            _dbg(f"[MIGRATE_RECURRING]   - {atx.description} em {atx.transaction_date}")
        
        # Buscar a primeira transação vinculada a esta recorrente
        first_tx = all_txs[0] if all_txs else None
        
        if first_tx and first_tx.transaction_date:
            old_start = tx.start_date
            # Usar o mês da primeira transação como referência
            new_start = date(first_tx.transaction_date.year, first_tx.transaction_date.month, 1)
            
            _dbg(f"[MIGRATE_RECURRING] {tx.description}: comparando start_date {old_start} com primeira transação {first_tx.transaction_date} -> novo start_date seria {new_start}")
            
            # Corrigir se o start_date for diferente do mês da primeira transação
            if old_start != new_start:
                tx.start_date = new_start
                _dbg(f"[MIGRATE_RECURRING] ✅ Corrigindo {tx.description}: {old_start} -> {new_start}")
            else:
                _dbg(f"[MIGRATE_RECURRING] ✓ {tx.description}: start_date já está correto ({old_start})")
        else:
            _dbg(f"[MIGRATE_RECURRING] ⚠️ {tx.description}: sem transações vinculadas, mantendo start_date {tx.start_date}")
    
    if cache:
        try:
            db.session.commit()
            _dbg(f"[MIGRATE_RECURRING] {len(cache)} RecurringTransaction criadas")
        except Exception as e:
            _dbg(f"[MIGRATE_RECURRING] Erro ao criar: {e}")
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
            _dbg(f"[FIX_START_DATE] {rec_tx.description}: encontradas {len(unlinked_txs)} transações não vinculadas")
            for tx in unlinked_txs:
                _dbg(f"[FIX_START_DATE]   - Vinculando {tx.description} de {tx.transaction_date}")
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
        ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc()).all()
        
        _dbg(f"[FIX_START_DATE] {rec_tx.description}: {len(all_txs)} transações vinculadas, start_date atual: {rec_tx.start_date}")
        for tx in all_txs:
            _dbg(f"[FIX_START_DATE]   - {tx.description} em {tx.transaction_date}")
        
        # Buscar a primeira transação vinculada a esta recorrente
        first_tx = all_txs[0] if all_txs else None
        
        if first_tx and first_tx.transaction_date:
            old_start = rec_tx.start_date
            # Usar o mês da primeira transação como referência
            new_start = date(first_tx.transaction_date.year, first_tx.transaction_date.month, 1)
            
            _dbg(f"[FIX_START_DATE] {rec_tx.description}: comparando start_date {old_start} com primeira transação {first_tx.transaction_date} -> novo start_date seria {new_start}")
            
            # Corrigir se o start_date for diferente do mês da primeira transação
            if old_start != new_start:
                rec_tx.start_date = new_start
                _dbg(f"[FIX_START_DATE] ✅ Corrigindo {rec_tx.description}: {old_start} -> {new_start}")
                fixed_count += 1
            else:
                _dbg(f"[FIX_START_DATE] ✓ {rec_tx.description}: start_date já está correto ({old_start})")
        else:
            _dbg(f"[FIX_START_DATE] ⚠️ {rec_tx.description}: sem transações vinculadas, mantendo start_date {rec_tx.start_date}")
    
    if fixed_count > 0:
        try:
            db.session.commit()
            _dbg(f"[FIX_START_DATE] {fixed_count} RecurringTransaction corrigidas")
        except Exception as e:
            _dbg(f"[FIX_START_DATE] Erro ao corrigir: {e}")
            db.session.rollback()


def _fix_legacy_auto_loaded_income_paid(user_id: int):
    txs = Transaction.query.filter(
        Transaction.user_id == int(user_id),
        Transaction.type == "income",
        Transaction.is_paid == False,
        Transaction.is_auto_loaded == True,
        Transaction.recurring_transaction_id.isnot(None),
    ).all()

    if not txs:
        return

    for tx in txs:
        try:
            tx.is_paid = True
            tx.paid_date = tx.transaction_date

            if getattr(tx, "workspace_id", None) is None and getattr(tx, "recurring_transaction_id", None):
                base_tx = (
                    Transaction.query.filter(
                        Transaction.user_id == int(user_id),
                        Transaction.recurring_transaction_id == int(tx.recurring_transaction_id),
                        Transaction.workspace_id.isnot(None),
                    )
                    .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
                    .first()
                )
                if base_tx:
                    tx.workspace_id = base_tx.workspace_id
        except Exception:
            pass

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _generate_recurring_for_month(user_id: int, year: int, month: int, workspace_id_fallback: int | None = None):
    """
    Gera automaticamente as transações recorrentes do mês se ainda não existirem.
    """
    _dbg(f"[GENERATE_RECURRING] Iniciando geração para {month}/{year}")
    
    # Corrigir start_date de recorrentes existentes (uma única vez)
    _fix_recurring_start_dates(user_id)
    
    # Migra recorrências antigas para a tabela recorrente (uma única vez/por demanda)
    _migrate_legacy_recurring_transactions(user_id)

    _fix_legacy_auto_loaded_income_paid(user_id)

    # Buscar todas as RecurringTransaction ativas do usuário
    recurring_txs = RecurringTransaction.query.filter_by(
        user_id=user_id,
        is_active=True,
        frequency="monthly"
    ).all()
    
    _dbg(f"[GENERATE_RECURRING] Encontradas {len(recurring_txs)} RecurringTransaction ativas")

    for rec_tx in recurring_txs:
        # Verificar se está dentro do período de validade
        target_date = date(year, month, 1)
        
        _dbg(f"[GENERATE_RECURRING] Processando: {rec_tx.description} (dia {rec_tx.day_of_month})")
        _dbg(f"[GENERATE_RECURRING] start_date: {rec_tx.start_date}, end_date: {rec_tx.end_date}, target: {target_date}")
        
        # Se tem start_date e o mês é anterior ao início, pular
        if rec_tx.start_date:
            start_month = date(rec_tx.start_date.year, rec_tx.start_date.month, 1)
            if target_date < start_month:
                _dbg(f"[GENERATE_RECURRING] Pulando {rec_tx.description}: mês anterior ao início ({target_date} < {start_month})")
                continue
        
        # Se tem end_date e o mês é posterior ao fim, pular
        if rec_tx.end_date:
            end_month = date(rec_tx.end_date.year, rec_tx.end_date.month, 1)
            if target_date > end_month:
                _dbg(f"[GENERATE_RECURRING] Pulando {rec_tx.description}: mês posterior ao fim ({target_date} > {end_month})")
                continue
        
        # Calcular a data da transação usando o dia do mês
        day_of_month = rec_tx.day_of_month or 1
        last_day = calendar.monthrange(year, month)[1]
        day = min(day_of_month, last_day)
        transaction_date = date(year, month, day)

        inherited_workspace_id = None
        try:
            base_tx = (
                Transaction.query.filter(
                    Transaction.user_id == int(user_id),
                    Transaction.recurring_transaction_id == rec_tx.id,
                    Transaction.workspace_id.isnot(None),
                )
                .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
                .first()
            )
            if base_tx:
                inherited_workspace_id = base_tx.workspace_id
        except Exception:
            inherited_workspace_id = None

        target_workspace_id = inherited_workspace_id if inherited_workspace_id is not None else workspace_id_fallback
        
        # Verificar se já existe uma transação deste recurring_transaction neste mês
        existing_query = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.recurring_transaction_id == rec_tx.id,
            func.extract('year', Transaction.transaction_date) == year,
            func.extract('month', Transaction.transaction_date) == month,
        )

        if target_workspace_id is None:
            existing_query = existing_query.filter(Transaction.workspace_id.is_(None))
        else:
            existing_query = existing_query.filter(Transaction.workspace_id == target_workspace_id)

        existing = existing_query.first()
        
        if existing:
            _dbg(f"[GENERATE_RECURRING] Já existe transação para {rec_tx.description} em {month}/{year}")
            continue  # Já existe, não criar novamente

        gen_desc = getattr(rec_tx, "description", "") or ""
        if rec_tx.type == "expense" and getattr(rec_tx, "start_date", None) and getattr(rec_tx, "end_date", None):
            try:
                total_inst = _months_diff(rec_tx.start_date.year, rec_tx.start_date.month, rec_tx.end_date.year, rec_tx.end_date.month) + 1
                idx_inst = _months_diff(rec_tx.start_date.year, rec_tx.start_date.month, int(year), int(month)) + 1
                if total_inst and total_inst > 1:
                    gen_desc = f"{_strip_installment_suffix(gen_desc)} ({idx_inst}/{total_inst})"
                else:
                    gen_desc = _strip_installment_suffix(gen_desc)
            except Exception:
                gen_desc = getattr(rec_tx, "description", "") or ""

        # Criar a transação do mês
        _dbg(f"[GENERATE_RECURRING] Criando transação para {rec_tx.description} em {transaction_date}")
        new_tx = Transaction(
            user_id=user_id,
            category_id=rec_tx.category_id,
            subcategory_id=rec_tx.subcategory_id,
            subcategory_text=rec_tx.subcategory_text,
            description=gen_desc,
            amount=rec_tx.amount,
            type=rec_tx.type,
            transaction_date=transaction_date,
            is_paid=True if rec_tx.type == "income" else False,  # Despesas recorrentes iniciam como não pagas
            paid_date=transaction_date if rec_tx.type == "income" else None,
            workspace_id=target_workspace_id,
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
    
    # NÃO criar workspace automaticamente - usuário deve criar manualmente
    
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

    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, OPTIONS")

    user_id_int = session.get("finance_user_id")
    if not user_id_int:
        try:
            raw_user_id = request.args.get("user_id")
            if raw_user_id:
                user_id_int = int(raw_user_id)
        except Exception:
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
            # Se apenas deletarmos, a transação volta no próximo refresh por causa da geração automática
            # (_generate_recurring_for_month). Para remover só este mês e manter os próximos,
            # quebramos a recorrência em duas: até o mês anterior, e a partir do mês seguinte.
            rec_tx = RecurringTransaction.query.filter_by(
                id=int(rec_id),
                user_id=int(user_id_int),
            ).first()

            if not rec_tx or not target_tx.transaction_date:
                db.session.delete(target_tx)
                return

            original_end_date = rec_tx.end_date

            # Encerrar recorrência antiga no mês anterior
            rec_tx.end_date = _prev_month_last_day(target_tx.transaction_date)

            # Criar uma nova recorrência a partir do mês seguinte (se ainda houver futuro)
            ny, nm = _shift_month_simple(target_tx.transaction_date.year, target_tx.transaction_date.month, 1)
            next_month_first_day = date(ny, nm, 1)

            should_create_new = True
            if original_end_date is not None and original_end_date < next_month_first_day:
                should_create_new = False

            new_rec_tx = None
            if should_create_new:
                new_rec_tx = RecurringTransaction(
                    user_id=rec_tx.user_id,
                    category_id=rec_tx.category_id,
                    subcategory_id=rec_tx.subcategory_id,
                    subcategory_text=rec_tx.subcategory_text,
                    description=rec_tx.description,
                    amount=rec_tx.amount,
                    type=rec_tx.type,
                    frequency=rec_tx.frequency,
                    day_of_month=rec_tx.day_of_month,
                    day_of_week=rec_tx.day_of_week,
                    start_date=next_month_first_day,
                    end_date=original_end_date,
                    is_active=rec_tx.is_active,
                    payment_method=rec_tx.payment_method,
                    notes=rec_tx.notes,
                )
                db.session.add(new_rec_tx)
                db.session.flush()

                # Migrar transações futuras já geradas para a nova recorrência
                db.session.query(Transaction).filter(
                    Transaction.user_id == int(user_id_int),
                    Transaction.recurring_transaction_id == int(rec_id),
                    Transaction.transaction_date >= next_month_first_day,
                ).update(
                    {Transaction.recurring_transaction_id: int(new_rec_tx.id)},
                    synchronize_session=False,
                )

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

    try:
        _delete_recurring_scope(tx, scope)
        db.session.commit()
        _dbg(f"[TX_REMOVE] Transação {tx_id} excluída com sucesso")
        resp = jsonify({"success": True})
        return _cors_wrap(resp, origin), 200
    except Exception as e:
        db.session.rollback()
        _dbg(f"[TX_REMOVE] Erro ao excluir: {e}")
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

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    workspace_id_hint = None
    try:
        workspace_id_hint = request.args.get("workspace_id")
        if workspace_id_hint:
            workspace_id_hint = int(workspace_id_hint)
    except Exception:
        workspace_id_hint = None

    if not workspace_id_hint:
        owned_ids = [w.id for w in Workspace.query.filter_by(owner_id=user_id_int).all()]
        member_ids = [m.workspace_id for m in WorkspaceMember.query.filter_by(user_id=user_id_int).all()]
        if len(set(owned_ids + member_ids)) > 1:
            resp = jsonify({"success": False, "message": "workspace_id obrigatório"})
            return _cors_wrap(resp, origin), 400

    active_workspace_id = _get_active_workspace_for_user(user_id_int, workspace_id_hint)
    if active_workspace_id:
        session[f"active_workspace_{user_id_int}"] = active_workspace_id

    share_prefs = None
    if active_workspace_id:
        share_prefs = _check_user_share_preferences(user_id_int, active_workspace_id)

    # Gerar recorrências do mês antes de calcular totais do dashboard.
    # Em workspaces compartilhados, gerar para todos os membros para que as parcelas
    # criadas por outros usuários também apareçam e somem corretamente.
    try:
        if active_workspace_id and share_prefs and share_prefs.get("share_transactions", True):
            member_ids = []
            try:
                w = Workspace.query.get(active_workspace_id)
                if w:
                    member_ids.append(int(getattr(w, "owner_id", 0) or 0))
                for m in WorkspaceMember.query.filter_by(workspace_id=active_workspace_id).all():
                    try:
                        member_ids.append(int(getattr(m, "user_id", 0) or 0))
                    except Exception:
                        pass
                member_ids = [uid for uid in set(member_ids) if uid]
            except Exception:
                member_ids = []

            for uid in member_ids:
                try:
                    _generate_recurring_for_month(int(uid), int(year), int(month), int(active_workspace_id))
                except Exception:
                    pass
        else:
            _generate_recurring_for_month(int(user_id_int), int(year), int(month), int(active_workspace_id) if active_workspace_id else None)
    except Exception:
        pass

    tx_filters = [
        Transaction.transaction_date >= start,
        Transaction.transaction_date < end,
    ]

    if active_workspace_id and share_prefs:
        if share_prefs.get("share_transactions", True):
            tx_filters.append(Transaction.workspace_id == active_workspace_id)
        else:
            tx_filters.append(Transaction.workspace_id == active_workspace_id)
            tx_filters.append(Transaction.user_id == user_id_int)
    else:
        tx_filters.append(Transaction.user_id == user_id_int)
        tx_filters.append(Transaction.workspace_id.is_(None))

    # Otimização: consolidar todas as queries de totais em uma única query
    from sqlalchemy import case
    
    totals = db.session.query(
        func.coalesce(func.sum(case(
            (Transaction.type == "income", Transaction.amount),
            else_=0
        )), 0).label("month_income"),
        func.coalesce(func.sum(case(
            ((Transaction.type == "expense") & (Transaction.is_paid == True), Transaction.amount),
            else_=0
        )), 0).label("month_expense"),
        func.coalesce(func.sum(case(
            ((Transaction.type == "expense") & (Transaction.is_paid == False), Transaction.amount),
            else_=0
        )), 0).label("month_expense_pending"),
        func.coalesce(func.sum(case(
            ((Transaction.type == "income") & (Transaction.is_paid == True), Transaction.amount),
            else_=0
        )), 0).label("month_income_paid"),
        func.coalesce(func.sum(case(
            ((Transaction.type == "expense") & (Transaction.is_paid == True), Transaction.amount),
            else_=0
        )), 0).label("month_expense_paid"),
    ).filter(*tx_filters).one()
    
    month_income = totals.month_income
    month_expense = totals.month_expense
    month_expense_pending = totals.month_expense_pending
    month_income_paid = totals.month_income_paid
    month_expense_paid = totals.month_expense_paid

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
            Transaction.type == "expense",
            Transaction.is_paid == True,
            *tx_filters,
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
    month_expense_pending_f = float(month_expense_pending or 0)
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
        .filter(*tx_filters)
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

    def _month_bounds(y: int, m: int):
        s = date(y, m, 1)
        if m == 12:
            e = date(y + 1, 1, 1)
        else:
            e = date(y, m + 1, 1)
        return s, e

    def _shift_month(y: int, m: int, delta: int):
        total = (y * 12) + (m - 1) + int(delta)
        ny = total // 12
        nm = (total % 12) + 1
        return ny, nm

    def _build_tx_filters_for_period(p_start: date, p_end: date):
        f = [
            Transaction.transaction_date >= p_start,
            Transaction.transaction_date < p_end,
        ]

        if active_workspace_id:
            if share_prefs.get("share_transactions") is True:
                f.append(Transaction.workspace_id == active_workspace_id)
            else:
                f.append(Transaction.workspace_id == active_workspace_id)
                f.append(Transaction.user_id == user_id_int)
        else:
            f.append(Transaction.user_id == user_id_int)
            f.append(Transaction.workspace_id.is_(None))

        return f

    def _paid_totals(p_filters):
        rows = db.session.query(
            func.coalesce(func.sum(case(
                ((Transaction.type == "income") & (Transaction.is_paid == True), Transaction.amount),
                else_=0,
            )), 0).label("income_paid"),
            func.coalesce(func.sum(case(
                ((Transaction.type == "expense") & (Transaction.is_paid == True), Transaction.amount),
                else_=0,
            )), 0).label("expense_paid"),
        ).filter(*p_filters).one()
        income_paid_v = float(rows.income_paid or 0)
        expense_paid_v = float(rows.expense_paid or 0)
        return income_paid_v, expense_paid_v

    def _pending_expense_total(p_filters):
        rows = db.session.query(
            func.coalesce(func.sum(case(
                ((Transaction.type == "expense") & (Transaction.is_paid == False), Transaction.amount),
                else_=0,
            )), 0).label("expense_pending"),
        ).filter(*p_filters).one()
        return float(rows.expense_pending or 0)

    # Saldo acumulado (carrega sobra/falta de meses anteriores):
    # baseado apenas em transações pagas, respeitando as mesmas regras de workspace/permissões.
    acc_epoch_start = date(1900, 1, 1)
    opening_paid_income, opening_paid_expense = _paid_totals(
        _build_tx_filters_for_period(acc_epoch_start, start)
    )
    closing_paid_income, closing_paid_expense = _paid_totals(
        _build_tx_filters_for_period(acc_epoch_start, end)
    )
    opening_balance = opening_paid_income - opening_paid_expense
    balance_accumulated = closing_paid_income - closing_paid_expense

    previous_expense_pending_total = _pending_expense_total(
        _build_tx_filters_for_period(acc_epoch_start, start)
    )
    carryover_effective = opening_balance - previous_expense_pending_total

    goals = {
        "income_goal": month_income_f,
        "income_actual": month_income_paid_f,
        "expense_goal": (month_expense_paid_f + month_expense_pending_f),
        "expense_actual": month_expense_paid_f,
    }

    prev_year, prev_month = _shift_month(year, month, -1)
    prev_start, prev_end = _month_bounds(prev_year, prev_month)
    prev_paid_income, prev_paid_expense = _paid_totals(_build_tx_filters_for_period(prev_start, prev_end))

    ytd_start = date(year, 1, 1)
    ytd_end = end
    ytd_paid_income, ytd_paid_expense = _paid_totals(_build_tx_filters_for_period(ytd_start, ytd_end))

    prev_ytd_start = date(year - 1, 1, 1)
    _, prev_ytd_end = _month_bounds(year - 1, month)
    prev_ytd_paid_income, prev_ytd_paid_expense = _paid_totals(_build_tx_filters_for_period(prev_ytd_start, prev_ytd_end))

    comparisons = {
        "month_current": {
            "income_paid": month_income_paid_f,
            "expense_paid": month_expense_paid_f,
            "balance": month_income_paid_f - month_expense_paid_f,
        },
        "month_previous": {
            "year": prev_year,
            "month": prev_month,
            "income_paid": prev_paid_income,
            "expense_paid": prev_paid_expense,
            "balance": prev_paid_income - prev_paid_expense,
        },
        "year_current": {
            "year": year,
            "income_paid": ytd_paid_income,
            "expense_paid": ytd_paid_expense,
            "balance": ytd_paid_income - ytd_paid_expense,
            "range_end": (ytd_end - timedelta(days=1)).isoformat() if ytd_end else None,
        },
        "year_previous": {
            "year": year - 1,
            "income_paid": prev_ytd_paid_income,
            "expense_paid": prev_ytd_paid_expense,
            "balance": prev_ytd_paid_income - prev_ytd_paid_expense,
            "range_end": (prev_ytd_end - timedelta(days=1)).isoformat() if prev_ytd_end else None,
        },
    }

    daily_rows = db.session.query(
        Transaction.transaction_date,
        func.coalesce(func.sum(case(
            ((Transaction.type == "income") & (Transaction.is_paid == True), Transaction.amount),
            else_=0,
        )), 0).label("income_paid"),
        func.coalesce(func.sum(case(
            ((Transaction.type == "expense") & (Transaction.is_paid == True), Transaction.amount),
            else_=0,
        )), 0).label("expense_paid"),
    ).filter(*_build_tx_filters_for_period(start, end)).group_by(Transaction.transaction_date).order_by(Transaction.transaction_date.asc()).all()

    daily_map = {}
    for d, inc, exp in daily_rows:
        try:
            daily_map[d] = (float(inc or 0), float(exp or 0))
        except Exception:
            daily_map[d] = (0.0, 0.0)

    last_day = calendar.monthrange(year, month)[1]
    running = 0.0
    daily_series = []
    for day in range(1, last_day + 1):
        dt = date(year, month, day)
        inc, exp = daily_map.get(dt, (0.0, 0.0))
        running += (inc - exp)
        daily_series.append({
            "date": dt.isoformat(),
            "income_paid": inc,
            "expense_paid": exp,
            "balance": running,
        })

    monthly_series = []
    for i in range(11, -1, -1):
        my, mm = _shift_month(year, month, -i)
        ms, me = _month_bounds(my, mm)
        mi, mep = _paid_totals(_build_tx_filters_for_period(ms, me))
        monthly_series.append({
            "year": my,
            "month": mm,
            "income_paid": mi,
            "expense_paid": mep,
            "balance": mi - mep,
        })

    time_series = {
        "daily": daily_series,
        "monthly": monthly_series,
    }

    resp = jsonify({
        "success": True,
        "balance": balance,
        "balance_accumulated": float(balance_accumulated),
        "opening_balance": float(opening_balance),
        "previous_expense_pending_total": float(previous_expense_pending_total),
        "carryover_effective": float(carryover_effective),
        "month": month,
        "year": year,
        "month_income": month_income_f,
        "month_expense": month_expense_f,
        "month_expense_pending": month_expense_pending_f,
        "month_income_paid": month_income_paid_f,
        "month_expense_paid": month_expense_paid_f,
        "month_balance": month_income_f - month_expense_f,
        "expense_by_category": expense_by_category,
        "latest_transactions": latest_transactions,
        "goals": goals,
        "comparisons": comparisons,
        "time_series": time_series,
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

    workspace_id_hint = None
    try:
        workspace_id_hint = request.args.get("workspace_id")
        if workspace_id_hint:
            workspace_id_hint = int(workspace_id_hint)
    except Exception:
        workspace_id_hint = None

    active_workspace_id = None
    share_prefs = None
    if workspace_id_hint:
        active_workspace_id = _get_active_workspace_for_user(user_id_int, workspace_id_hint)
        if not active_workspace_id:
            resp = jsonify({"success": False, "message": "workspace_id obrigatório"})
            return _cors_wrap(resp, origin), 400
        share_prefs = _check_user_share_preferences(user_id_int, active_workspace_id)
        if not share_prefs:
            resp = jsonify({"success": False, "message": "Sem permissão para acessar este workspace"})
            return _cors_wrap(resp, origin), 403

    cfg = _ensure_finance_config_and_categories(user_id_int)
    cat_type = (request.args.get("type") or "").strip().lower() or None

    if active_workspace_id and share_prefs and share_prefs.get("share_categories", True):
        w = Workspace.query.get(active_workspace_id)
        member_ids = []
        if w:
            member_ids.append(int(w.owner_id))
        for m in WorkspaceMember.query.filter_by(workspace_id=active_workspace_id).all():
            try:
                member_ids.append(int(m.user_id))
            except Exception:
                pass
        member_ids = list(set(member_ids))

        cfg_ids = []
        for uid in member_ids:
            c = FinanceConfig.query.filter_by(user_id=uid).first()
            if c:
                cfg_ids.append(int(c.id))

        query = Category.query.filter(Category.is_active.is_(True), Category.config_id.in_(cfg_ids))
        if cat_type in ("income", "expense"):
            query = query.filter(Category.type == cat_type)
        cats = query.order_by(Category.type.asc(), Category.name.asc()).all()
    else:
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


@api_financeiro_bp.route("/api/test", methods=["GET", "OPTIONS"])
def api_test():
    """Endpoint de teste simples"""
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, OPTIONS")
    
    print(f"[TEST] Test endpoint called successfully!")
    resp = jsonify({"success": True, "message": "API is working"})
    return _cors_wrap(resp, origin), 200


@api_financeiro_bp.route("/api/transactions", methods=["POST", "OPTIONS"])
def api_create_transaction():
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")

    print(f"[CREATE_TX] Starting transaction creation")
    
    try:
        print(f"[CREATE_TX] Getting user_id from session")
        user_id_int = session.get("finance_user_id")
        print(f"[CREATE_TX] user_id from session: {user_id_int}")
        
        if not user_id_int:
            # fallback para app atual
            try:
                user_id_int = int((request.get_json(silent=True) or {}).get("user_id"))
                print(f"[CREATE_TX] user_id from body: {user_id_int}")
            except Exception:
                user_id_int = None

        if not user_id_int:
            resp = jsonify({"success": False, "message": "Não autenticado"})
            return _cors_wrap(resp, origin), 401
        
        print(f"[CREATE_TX] Ensuring finance config and categories")
        cfg = _ensure_finance_config_and_categories(int(user_id_int))
        print(f"[CREATE_TX] Config ensured: {cfg}")

        data = request.get_json(silent=True) or {}
        print(f"[CREATE_TX] Request data: {data}")
        
        # Determinar workspace_id do request (se fornecido)
        workspace_id_hint = data.get("workspace_id")
        if workspace_id_hint:
            try:
                workspace_id_hint = int(workspace_id_hint)
            except Exception:
                workspace_id_hint = None

        if not workspace_id_hint:
            owned_ids = [w.id for w in Workspace.query.filter_by(owner_id=user_id_int).all()]
            member_ids = [m.workspace_id for m in WorkspaceMember.query.filter_by(user_id=user_id_int).all()]
            if len(set(owned_ids + member_ids)) > 1:
                resp = jsonify({"success": False, "message": "workspace_id obrigatório"})
                return _cors_wrap(resp, origin), 400
        
        # Usar nova lógica consistente para determinar workspace ativo
        active_workspace_id = _get_active_workspace_for_user(user_id_int, workspace_id_hint)
        print(f"[CREATE_TX] user_id={user_id_int}, active_workspace_id={active_workspace_id}")
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
        recurring_installments_raw = data.get("recurring_installments")
        recurring_installments_start = str(data.get("recurring_installments_start") or "").strip().lower() or None

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

        # Usar o workspace ativo determinado pela nova lógica
        workspace_id = active_workspace_id
        
        # Verificar se usuário tem permissão para criar transações no workspace
        if workspace_id:
            share_prefs = _check_user_share_preferences(user_id_int, workspace_id)
            if not share_prefs:
                resp = jsonify({"success": False, "message": "Sem permissão para acessar este workspace"})
                return _cors_wrap(resp, origin), 403
            
            # Sincronizar contexto do workspace para todos os membros
            try:
                api_sync_workspace_context(workspace_id, user_id_int)
            except Exception as e:
                print(f"[CREATE_TX] Erro na sincronização: {e}")
            
            print(f"[CREATE_TX] Usando workspace_id={workspace_id} com permissões: {share_prefs}")
        
        print(f"[CREATE_TX] workspace_id final determinado: {workspace_id}")
        
        # Se ainda não tem workspace_id, criar um workspace padrão para o usuário
        if workspace_id is None:
            print(f"[CREATE_TX] Criando workspace padrão para user_id={user_id_int}")
            try:
                default_workspace = Workspace(
                    owner_id=user_id_int,
                    name="Meu Workspace",
                    description="Workspace padrão",
                    color="#3b82f6"
                )
                db.session.add(default_workspace)
                db.session.flush()  # Para obter o ID
                workspace_id = default_workspace.id
                session[f"active_workspace_{user_id_int}"] = workspace_id
                print(f"[CREATE_TX] Workspace padrão criado com ID: {workspace_id}")
            except Exception as e:
                print(f"[CREATE_TX] Erro ao criar workspace padrão: {e}")
                resp = jsonify({"success": False, "message": "Erro ao determinar workspace"})
                return _cors_wrap(resp, origin), 500

        recurring_tx = None
        if is_recurring:
            def _parse_bool(v, default: bool = True) -> bool:
                if v is None:
                    return default
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(v)
                try:
                    s = str(v).strip().lower()
                except Exception:
                    return default
                if s in ("true", "1", "yes", "y", "sim"):
                    return True
                if s in ("false", "0", "no", "n", "nao", "não"):
                    return False
                return default

            # Null = sem fim
            unlimited_bool = True
            if recurring_unlimited is not None:
                try:
                    unlimited_bool = _parse_bool(recurring_unlimited, default=True)
                except Exception:
                    unlimited_bool = True

            end_date = None
            installments_int = None
            if ttype == "expense" and recurring_installments_raw is not None:
                try:
                    installments_int = int(recurring_installments_raw)
                except Exception:
                    installments_int = None
                if installments_int is not None and installments_int < 1:
                    installments_int = None

            if recurring_installments_start not in ("current_month", "due_date"):
                recurring_installments_start = "current_month"

            start_for_installments = date(tdate.year, tdate.month, 1)
            if installments_int is not None and recurring_installments_start == "due_date":
                try:
                    today = datetime.utcnow().date()
                    if tdate < today:
                        ny, nm = _shift_month_simple(tdate.year, tdate.month, 1)
                        start_for_installments = date(ny, nm, 1)
                except Exception:
                    start_for_installments = date(tdate.year, tdate.month, 1)

            if installments_int is not None:
                unlimited_bool = False
                end_y, end_m = _shift_month_simple(start_for_installments.year, start_for_installments.month, installments_int - 1)
                end_date = _last_day_of_month(end_y, end_m)
            elif not unlimited_bool and recurring_end_date_raw:
                try:
                    end_date = date.fromisoformat(recurring_end_date_raw)
                except Exception:
                    end_date = None

            recurring_tx = RecurringTransaction(
                user_id=int(user_id_int),
                category_id=category.id,
                subcategory_id=None,
                subcategory_text=subcategory_text,
                description=_strip_installment_suffix(description),
                amount=amount,
                type=ttype,
                frequency="monthly",
                day_of_month=recurring_day_int,
                start_date=start_for_installments,
                end_date=end_date,
                is_active=True,
                payment_method=payment_method,
                notes=notes,
            )
            db.session.add(recurring_tx)
            db.session.flush()

        tx_desc = description
        tx_date_final = tdate
        if is_recurring and ttype == "expense" and recurring_tx and getattr(recurring_tx, "start_date", None) and getattr(recurring_tx, "end_date", None):
            try:
                total_inst = _months_diff(recurring_tx.start_date.year, recurring_tx.start_date.month, recurring_tx.end_date.year, recurring_tx.end_date.month) + 1
                if total_inst and total_inst > 1:
                    tx_desc = f"{_strip_installment_suffix(description)} (1/{total_inst})"
                else:
                    tx_desc = _strip_installment_suffix(description)

                if recurring_tx.start_date:
                    last_day = calendar.monthrange(recurring_tx.start_date.year, recurring_tx.start_date.month)[1]
                    tx_date_final = date(recurring_tx.start_date.year, recurring_tx.start_date.month, min(recurring_day_int or 1, last_day))
            except Exception:
                tx_desc = description

        tx = Transaction(
            user_id=int(user_id_int),
            category_id=category.id,
            description=tx_desc,
            amount=amount,
            type=ttype,
            transaction_date=tx_date_final,
            is_paid=is_paid,
            paid_date=tx_date_final if is_paid else None,
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
        
    except Exception as e:
        print(f"[CREATE_TX] Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        resp = jsonify({"success": False, "message": f"Erro interno: {str(e)}"})
        return _cors_wrap(resp, origin), 500


@api_financeiro_bp.route("/api/workspace/sync", methods=["POST", "OPTIONS"])
def api_sync_workspace():
    """Endpoint para sincronizar contexto de workspace entre membros"""
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")
    
    user_id_int = _get_user_id_from_request()
    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401
    
    data = request.get_json(silent=True) or {}
    workspace_id = data.get("workspace_id")
    
    if not workspace_id:
        resp = jsonify({"success": False, "message": "workspace_id obrigatório"})
        return _cors_wrap(resp, origin), 400
    
    try:
        workspace_id = int(workspace_id)
    except Exception:
        resp = jsonify({"success": False, "message": "workspace_id inválido"})
        return _cors_wrap(resp, origin), 400
    
    # Sincronizar workspace para todos os membros
    success = api_sync_workspace_context(workspace_id, user_id_int)
    
    if success:
        resp = jsonify({
            "success": True,
            "message": "Workspace sincronizado",
            "workspace_id": workspace_id
        })
        return _cors_wrap(resp, origin), 200
    else:
        resp = jsonify({"success": False, "message": "Erro ao sincronizar workspace"})
        return _cors_wrap(resp, origin), 500


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

    tx_type = (request.args.get("type") or "").strip().lower()
    q = (request.args.get("q") or "").strip()

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    # Buscar workspace_id do request (se fornecido)
    workspace_id_hint = None
    try:
        workspace_id_hint = request.args.get("workspace_id")
        if workspace_id_hint:
            workspace_id_hint = int(workspace_id_hint)
    except Exception:
        workspace_id_hint = None

    if not workspace_id_hint:
        owned_ids = [w.id for w in Workspace.query.filter_by(owner_id=user_id_int).all()]
        member_ids = [m.workspace_id for m in WorkspaceMember.query.filter_by(user_id=user_id_int).all()]
        if len(set(owned_ids + member_ids)) > 1:
            resp = jsonify({"success": False, "message": "workspace_id obrigatório"})
            return _cors_wrap(resp, origin), 400
    
    # Determinar workspace ativo usando nova lógica consistente
    active_workspace_id = _get_active_workspace_for_user(user_id_int, workspace_id_hint)
    print(f"[LIST_TX] user_id={user_id_int}, active_workspace_id={active_workspace_id}")
    
    # Verificar preferências de compartilhamento do usuário
    share_prefs = None
    if active_workspace_id:
        share_prefs = _check_user_share_preferences(user_id_int, active_workspace_id)
        print(f"[LIST_TX] share_preferences={share_prefs}")

    # Gerar recorrências do mês para garantir que parcelas apareçam nos meses futuros.
    # Se o workspace compartilha transações, gerar para todos os membros do workspace.
    try:
        if active_workspace_id and share_prefs and share_prefs.get('share_transactions', True):
            member_ids = []
            try:
                w = Workspace.query.get(active_workspace_id)
                if w:
                    member_ids.append(int(getattr(w, 'owner_id', 0) or 0))
                for m in WorkspaceMember.query.filter_by(workspace_id=active_workspace_id).all():
                    try:
                        member_ids.append(int(getattr(m, 'user_id', 0) or 0))
                    except Exception:
                        pass
                member_ids = [uid for uid in set(member_ids) if uid]
            except Exception:
                member_ids = []

            for uid in member_ids:
                try:
                    _generate_recurring_for_month(int(uid), int(year), int(month), int(active_workspace_id))
                except Exception:
                    pass
        else:
            _generate_recurring_for_month(int(user_id_int), int(year), int(month), int(active_workspace_id) if active_workspace_id else None)
    except Exception:
        pass
    
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
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
    )
    
    # Filtrar por workspace se houver um ativo
    if active_workspace_id and share_prefs:
        print(f"[LIST_TX] Filtrando transações por workspace_id={active_workspace_id}")
        
        # Verificar se usuário pode ver transações compartilhadas
        if share_prefs.get('share_transactions', True):
            # Mostrar todas as transações do workspace
            query = query.filter(Transaction.workspace_id == active_workspace_id)
            print(f"[LIST_TX] Mostrando todas as transações do workspace (share_transactions=True)")
        else:
            # Mostrar apenas transações próprias do usuário no workspace
            query = query.filter(
                Transaction.workspace_id == active_workspace_id,
                Transaction.user_id == int(user_id_int)
            )
            print(f"[LIST_TX] Mostrando apenas transações próprias no workspace (share_transactions=False)")
    else:
        print(f"[LIST_TX] Sem workspace ativo, mostrando transações pessoais do usuário")
        # Sem workspace ativo, mostrar apenas transações pessoais do usuário
        query = query.filter(
            Transaction.user_id == int(user_id_int),
            Transaction.workspace_id.is_(None)
        )

    if tx_type in ("income", "expense"):
        query = query.filter(Transaction.type == tx_type)

    if q:
        query = query.filter(func.lower(Transaction.description).like(f"%{q.lower()}%"))

    rows = query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).all()
    print(f"[LIST_TX] Encontradas {len(rows)} transações para o período {year}-{month:02d}")

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
    _dbg(f"[TX_DETAIL] {request.method} /api/transactions/{tx_id} - args: {dict(request.args)}")
    
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, PUT, DELETE, OPTIONS")

    user_id_int = session.get("finance_user_id")
    if not user_id_int:
        try:
            if request.method in ("GET", "DELETE"):
                raw_user_id = request.args.get("user_id")
                _dbg(f"[TX_DETAIL] raw_user_id from args: {raw_user_id}")
                if not raw_user_id:
                    raw_user_id = (request.get_json(silent=True) or {}).get("user_id")
                    _dbg(f"[TX_DETAIL] raw_user_id from body: {raw_user_id}")
                if raw_user_id:
                    user_id_int = int(raw_user_id)
            else:
                raw_user_id = (request.get_json(silent=True) or {}).get("user_id")
                _dbg(f"[TX_DETAIL] raw_user_id from body: {raw_user_id}")
                if raw_user_id:
                    user_id_int = int(raw_user_id)
        except Exception as e:
            _dbg(f"[TX_DETAIL] Erro ao parsear user_id: {e}")
            user_id_int = None

    _dbg(f"[TX_DETAIL] user_id_int final: {user_id_int}")

    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    tx = Transaction.query.filter_by(id=tx_id).first()
    _dbg(f"[TX_DETAIL] Transaction found: {tx}")
    if not tx:
        resp = jsonify({"success": False, "message": "Transação não encontrada"})
        return _cors_wrap(resp, origin), 404

    tx_workspace_id = getattr(tx, "workspace_id", None)
    if tx_workspace_id:
        w = Workspace.query.get(int(tx_workspace_id))
        is_owner = bool(w and int(getattr(w, "owner_id", 0) or 0) == int(user_id_int))
        is_member = WorkspaceMember.query.filter_by(
            workspace_id=int(tx_workspace_id),
            user_id=int(user_id_int),
        ).first()
        if not (is_owner or is_member):
            resp = jsonify({"success": False, "message": "Transação não encontrada"})
            return _cors_wrap(resp, origin), 404

        share_prefs = _check_user_share_preferences(int(user_id_int), int(tx_workspace_id))
        if share_prefs and share_prefs.get("share_transactions") is False:
            if int(getattr(tx, "user_id", 0) or 0) != int(user_id_int):
                resp = jsonify({"success": False, "message": "Transação não encontrada"})
                return _cors_wrap(resp, origin), 404
    else:
        if int(getattr(tx, "user_id", 0) or 0) != int(user_id_int):
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
                "recurring_installments": (
                    (_months_diff(rec_tx.start_date.year, rec_tx.start_date.month, rec_tx.end_date.year, rec_tx.end_date.month) + 1)
                    if (rec_tx and rec_tx.type == "expense" and rec_tx.start_date and rec_tx.end_date)
                    else None
                ),
                "recurring_installments_start": None,
                "recurring_installment_index": (
                    (_months_diff(rec_tx.start_date.year, rec_tx.start_date.month, tx.transaction_date.year, tx.transaction_date.month) + 1)
                    if (rec_tx and rec_tx.type == "expense" and rec_tx.start_date and rec_tx.end_date and tx.transaction_date)
                    else None
                ),
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
    recurring_installments_raw = data.get("recurring_installments")
    recurring_installments_start = str(data.get("recurring_installments_start") or "").strip().lower() or None

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
        installments_int = None
        if ttype == "expense" and recurring_installments_raw is not None:
            try:
                installments_int = int(recurring_installments_raw)
            except Exception:
                installments_int = None
            if installments_int is not None and installments_int < 1:
                installments_int = None

        if recurring_installments_start not in ("current_month", "due_date"):
            recurring_installments_start = "current_month"

        if tx.recurring_transaction_id:
            rec_tx = RecurringTransaction.query.filter_by(id=tx.recurring_transaction_id, user_id=int(user_id_int)).first()

        base_start_month = date(tdate.year, tdate.month, 1)
        if rec_tx and rec_tx.start_date:
            # Não mudar o start_date de uma recorrência já existente ao editar parcelas do meio.
            base_start_month = date(rec_tx.start_date.year, rec_tx.start_date.month, 1)
        elif installments_int is not None:
            # Definir start_date apenas quando estamos criando/ativando a recorrência.
            base_start_month = date(tdate.year, tdate.month, 1)
            if recurring_installments_start == "due_date":
                try:
                    today = datetime.utcnow().date()
                    if tdate < today:
                        ny, nm = _shift_month_simple(tdate.year, tdate.month, 1)
                        base_start_month = date(ny, nm, 1)
                except Exception:
                    base_start_month = date(tdate.year, tdate.month, 1)

        if installments_int is not None:
            unlimited_bool = False
            end_y, end_m = _shift_month_simple(base_start_month.year, base_start_month.month, installments_int - 1)
            end_date = _last_day_of_month(end_y, end_m)
        elif not unlimited_bool and recurring_end_date_raw:
            try:
                end_date = date.fromisoformat(recurring_end_date_raw)
            except Exception:
                end_date = None

        if not rec_tx:
            start_date_first_day = base_start_month
            base_desc = _strip_installment_suffix(description)
            rec_tx = RecurringTransaction(
                user_id=int(user_id_int),
                category_id=category.id,
                subcategory_id=None,
                subcategory_text=subcategory_text,
                description=base_desc,
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
            # Só definir start_date se estiver vazio.
            if rec_tx.start_date is None:
                rec_tx.start_date = base_start_month
            rec_tx.end_date = end_date
            rec_tx.day_of_month = recurring_day_int
            rec_tx.category_id = category.id
            rec_tx.subcategory_text = subcategory_text
            rec_tx.description = _strip_installment_suffix(description)
            rec_tx.amount = amount
            rec_tx.type = ttype
            rec_tx.payment_method = payment_method
            rec_tx.notes = notes
            rec_tx.is_active = True

    if not is_recurring:
        tx.recurring_transaction_id = None

    tx.type = ttype
    tx_desc = description
    if is_recurring and ttype == "expense" and rec_tx and getattr(rec_tx, "end_date", None) and getattr(rec_tx, "start_date", None) and tdate:
        try:
            total_inst = _months_diff(rec_tx.start_date.year, rec_tx.start_date.month, rec_tx.end_date.year, rec_tx.end_date.month) + 1
            idx_inst = _months_diff(rec_tx.start_date.year, rec_tx.start_date.month, tdate.year, tdate.month) + 1
            if total_inst and total_inst > 1:
                tx_desc = f"{_strip_installment_suffix(description)} ({idx_inst}/{total_inst})"
            else:
                tx_desc = _strip_installment_suffix(description)
        except Exception:
            tx_desc = description

    tx.description = tx_desc
    tx.amount = amount
    tx.category_id = category.id
    tx_date_final = tdate
    if is_recurring and recurring_day_int and tdate:
        try:
            last_day = calendar.monthrange(tdate.year, tdate.month)[1]
            tx_date_final = date(tdate.year, tdate.month, min(recurring_day_int or 1, last_day))
        except Exception:
            tx_date_final = tdate

    tx.transaction_date = tx_date_final
    tx.is_paid = is_paid
    tx.paid_date = tx_date_final if is_paid else None
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
    _dbg(f"[GROQ] API Key presente: {bool(groq_api_key)}")
    _dbg(f"[GROQ] Descrição: {description}")
    _dbg(f"[GROQ] Tipo: {transaction_type}")
    
    if not groq_api_key:
        _dbg("[GROQ] ERRO: API Key não encontrada")
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

        _dbg(f"[GROQ] Status da resposta: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            _dbg(f"[GROQ] Resposta da IA: {content}")
            
            # Limpar markdown code blocks se houver
            content_clean = content.strip()
            if content_clean.startswith("```json"):
                content_clean = content_clean[7:]  # Remove ```json
            if content_clean.startswith("```"):
                content_clean = content_clean[3:]  # Remove ```
            if content_clean.endswith("```"):
                content_clean = content_clean[:-3]  # Remove ```
            content_clean = content_clean.strip()

            _dbg(f"[GROQ] JSON limpo: {content_clean}")
            
            # Tentar parsear JSON da resposta
            import json
            try:
                suggestion = json.loads(content_clean)
                suggested_category = suggestion.get("category", "Outros")
                suggested_subcategory = suggestion.get("subcategory")

                _dbg(f"[GROQ] Categoria sugerida: {suggested_category}")
                _dbg(f"[GROQ] Subcategoria sugerida: {suggested_subcategory}")
                
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
                    _dbg(f"[GROQ] Categoria '{suggested_category}' não encontrada nas disponíveis")
            except json.JSONDecodeError as e:
                _dbg(f"[GROQ] Erro ao parsear JSON: {e}")
                pass
        else:
            _dbg(f"[GROQ] Erro na API: {response.text}")

    except Exception as e:
        _dbg(f"[GROQ ERROR] Exceção: {e}")
        import traceback
        _dbg(f"[GROQ ERROR] Traceback: {traceback.format_exc()}")

    # Se chegou aqui, houve erro: retornar erro e deixar o app liberar entrada manual
    _dbg("[GROQ] Falha ao gerar categoria")
    resp = jsonify({
        "success": False,
        "message": "Não foi possível gerar categoria. Preencha manualmente.",
    })
    return _cors_wrap(resp, origin), 500


@api_financeiro_bp.route("/api/finance-ai", methods=["POST", "OPTIONS"])
def api_finance_ai():
    origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")

    user_id_int = _get_user_id_from_request()
    if not user_id_int:
        resp = jsonify({"success": False, "message": "Não autenticado"})
        return _cors_wrap(resp, origin), 401

    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "")).strip().lower()
    message = str(data.get("message", "")).strip()
    context = data.get("context") or {}

    active_workspace_id, err = _require_active_workspace_or_400(int(user_id_int))
    if err:
        return err

    share_prefs = _check_user_share_preferences(int(user_id_int), int(active_workspace_id)) or {}

    if not message:
        resp = jsonify({"success": False, "message": "Mensagem é obrigatória"})
        return _cors_wrap(resp, origin), 400

    if mode not in ("credit_cards", "loans", "calculators"):
        mode = "general"

    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        resp = jsonify({
            "success": False,
            "message": "IA não configurada (GROQ_API_KEY ausente).",
        })
        return _cors_wrap(resp, origin), 503

    # ------------------------------------------------------------------
    # Contexto do workspace (baseado nos dados reais)
    # ------------------------------------------------------------------
    today = datetime.utcnow().date()
    month_start = date(today.year, today.month, 1)
    if today.month == 12:
        month_end = date(today.year + 1, 1, 1)
    else:
        month_end = date(today.year, today.month + 1, 1)

    tx_filters_month = [
        Transaction.workspace_id == int(active_workspace_id),
        Transaction.transaction_date >= month_start,
        Transaction.transaction_date < month_end,
    ]
    tx_filters_90d = [
        Transaction.workspace_id == int(active_workspace_id),
        Transaction.transaction_date >= (today - timedelta(days=90)),
        Transaction.transaction_date <= today,
    ]

    if share_prefs.get("share_transactions") is False:
        tx_filters_month.append(Transaction.user_id == int(user_id_int))
        tx_filters_90d.append(Transaction.user_id == int(user_id_int))

    income_month = 0.0
    expense_month = 0.0
    balance_month = 0.0
    try:
        sums = db.session.query(
            func.coalesce(func.sum(case((Transaction.type == "income", Transaction.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Transaction.type == "expense", Transaction.amount), else_=0)), 0),
        ).filter(*tx_filters_month).first()
        income_month = float(sums[0] or 0)
        expense_month = float(sums[1] or 0)
        balance_month = income_month - expense_month
    except Exception:
        income_month = 0.0
        expense_month = 0.0
        balance_month = 0.0

    income_90d = 0.0
    expense_90d = 0.0
    try:
        sums_90d = db.session.query(
            func.coalesce(func.sum(case((Transaction.type == "income", Transaction.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Transaction.type == "expense", Transaction.amount), else_=0)), 0),
        ).filter(*tx_filters_90d).first()
        income_90d = float(sums_90d[0] or 0)
        expense_90d = float(sums_90d[1] or 0)
    except Exception:
        income_90d = 0.0
        expense_90d = 0.0

    # Estimativa de gastos em cartão (heurística por payment_method)
    credit_card_expense_month = 0.0
    try:
        credit_like = or_(
            func.lower(func.coalesce(Transaction.payment_method, "")).like("%cart%"),
            func.lower(func.coalesce(Transaction.payment_method, "")).like("%credit%"),
            func.lower(func.coalesce(Transaction.payment_method, "")).like("%crédito%"),
            func.lower(func.coalesce(Transaction.payment_method, "")).like("%credito%"),
        )
        cc_sum = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.workspace_id == int(active_workspace_id),
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date < month_end,
            credit_like,
            *( [Transaction.user_id == int(user_id_int)] if share_prefs.get("share_transactions") is False else [] ),
        ).scalar()
        credit_card_expense_month = float(cc_sum or 0)
    except Exception:
        credit_card_expense_month = 0.0

    # Top categorias de despesa no mês
    top_categories = []
    try:
        rows = db.session.query(
            func.coalesce(Category.name, "Sem categoria").label("cat"),
            func.coalesce(func.sum(Transaction.amount), 0).label("spent"),
        ).outerjoin(Category, Category.id == Transaction.category_id).filter(
            Transaction.workspace_id == int(active_workspace_id),
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date < month_end,
            *( [Transaction.user_id == int(user_id_int)] if share_prefs.get("share_transactions") is False else [] ),
        ).group_by(func.coalesce(Category.name, "Sem categoria")).order_by(func.sum(Transaction.amount).desc()).limit(7).all()

        top_categories = [
            {"category": str(r[0]), "spent": float(r[1] or 0)}
            for r in (rows or [])
        ]
    except Exception:
        top_categories = []

    # Orçamentos do mês (se existirem)
    budgets_summary = []
    try:
        budgets = Budget.query.filter_by(
            workspace_id=int(active_workspace_id),
            period="monthly",
            year=int(today.year),
            month=int(today.month),
        ).all()
        cat_ids = [b.category_id for b in budgets]
        spent_map = {}
        if cat_ids:
            spent_rows = db.session.query(
                Transaction.category_id,
                func.coalesce(func.sum(Transaction.amount), 0).label("spent"),
            ).filter(
                Transaction.workspace_id == int(active_workspace_id),
                Transaction.type == "expense",
                Transaction.transaction_date >= month_start,
                Transaction.transaction_date < month_end,
                Transaction.category_id.in_(cat_ids),
                *( [Transaction.user_id == int(user_id_int)] if share_prefs.get("share_transactions") is False else [] ),
            ).group_by(Transaction.category_id).all()
            for cid, spent in spent_rows:
                spent_map[int(cid)] = float(spent or 0)

        for b in budgets[:7]:
            limit_v = float(b.limit_amount or 0)
            spent_v = float(spent_map.get(int(b.category_id), 0.0))
            pct = (spent_v / limit_v) if limit_v > 0 else None
            budgets_summary.append({
                "category": b.category.name if b.category else None,
                "limit": limit_v,
                "spent": spent_v,
                "percent_used": pct,
            })
    except Exception:
        budgets_summary = []

    # Breakdown de despesas por método de pagamento (mês)
    expense_by_payment_method_month = []
    try:
        rows = db.session.query(
            func.lower(func.coalesce(Transaction.payment_method, "")).label("pm"),
            func.coalesce(func.sum(Transaction.amount), 0).label("spent"),
        ).filter(
            Transaction.workspace_id == int(active_workspace_id),
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date < month_end,
            *( [Transaction.user_id == int(user_id_int)] if share_prefs.get("share_transactions") is False else [] ),
        ).group_by(func.lower(func.coalesce(Transaction.payment_method, ""))).order_by(func.sum(Transaction.amount).desc()).limit(10).all()

        expense_by_payment_method_month = [
            {"payment_method": (r[0] or "").strip() or None, "spent": float(r[1] or 0)}
            for r in (rows or [])
        ]
    except Exception:
        expense_by_payment_method_month = []

    # Últimas transações (30 dias) para fundamentar respostas
    recent_transactions_30d = []
    try:
        recent_q = Transaction.query.filter(
            Transaction.workspace_id == int(active_workspace_id),
            Transaction.transaction_date >= (today - timedelta(days=30)),
            Transaction.transaction_date <= today,
        )
        if share_prefs.get("share_transactions") is False:
            recent_q = recent_q.filter(Transaction.user_id == int(user_id_int))

        recent = recent_q.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(25).all()
        for tx in recent or []:
            recent_transactions_30d.append({
                "date": tx.transaction_date.isoformat() if tx.transaction_date else None,
                "type": tx.type,
                "amount": float(tx.amount or 0),
                "description": tx.description,
                "category": tx.category.name if tx.category else None,
                "payment_method": tx.payment_method,
                "is_paid": bool(tx.is_paid),
            })
    except Exception:
        recent_transactions_30d = []

    # Indícios de empréstimo/financiamento (heurística por texto/categoria)
    loan_hints_90d = {"count": 0, "total": 0.0, "examples": []}
    try:
        kw = ["emprest", "emprést", "financ", "parcela", "consign", "juros"]
        text_or = []
        for k in kw:
            text_or.append(func.lower(func.coalesce(Transaction.description, "")).like(f"%{k}%"))
            text_or.append(func.lower(func.coalesce(Transaction.notes, "")).like(f"%{k}%"))
            text_or.append(func.lower(func.coalesce(Category.name, "")).like(f"%{k}%"))

        q = db.session.query(
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0),
        ).outerjoin(Category, Category.id == Transaction.category_id).filter(
            Transaction.workspace_id == int(active_workspace_id),
            Transaction.type == "expense",
            Transaction.transaction_date >= (today - timedelta(days=90)),
            Transaction.transaction_date <= today,
            or_(*text_or),
            *( [Transaction.user_id == int(user_id_int)] if share_prefs.get("share_transactions") is False else [] ),
        ).first()
        loan_hints_90d["count"] = int(q[0] or 0)
        loan_hints_90d["total"] = float(q[1] or 0)

        ex = Transaction.query.outerjoin(Category, Category.id == Transaction.category_id).filter(
            Transaction.workspace_id == int(active_workspace_id),
            Transaction.type == "expense",
            Transaction.transaction_date >= (today - timedelta(days=90)),
            Transaction.transaction_date <= today,
            or_(*text_or),
        )
        if share_prefs.get("share_transactions") is False:
            ex = ex.filter(Transaction.user_id == int(user_id_int))
        ex = ex.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(8).all()
        loan_hints_90d["examples"] = [
            {
                "date": t.transaction_date.isoformat() if t.transaction_date else None,
                "amount": float(t.amount or 0),
                "description": t.description,
                "category": t.category.name if t.category else None,
            }
            for t in (ex or [])
        ]
    except Exception:
        loan_hints_90d = {"count": 0, "total": 0.0, "examples": []}

    workspace = None
    try:
        workspace = Workspace.query.get(int(active_workspace_id))
    except Exception:
        workspace = None

    workspace_context = {
        "workspace_id": int(active_workspace_id),
        "workspace_name": workspace.name if workspace else None,
        "month": f"{today.year:04d}-{today.month:02d}",
        "income_month": income_month,
        "expense_month": expense_month,
        "balance_month": balance_month,
        "income_90d": income_90d,
        "expense_90d": expense_90d,
        "expense_90d_monthly_avg_estimate": (expense_90d / 3.0) if expense_90d else 0.0,
        "credit_card_expense_month_estimate": credit_card_expense_month,
        "expense_by_payment_method_month": expense_by_payment_method_month,
        "top_expense_categories_month": top_categories,
        "budgets_month": budgets_summary,
        "recent_transactions_30d": recent_transactions_30d,
        "loan_hints_90d": loan_hints_90d,
        "share_transactions": bool(share_prefs.get("share_transactions", True)),
    }

    system_prompt = (
        "Você é um assistente financeiro pessoal. "
        "Responda em português (Brasil), de forma objetiva e acionável. "
        "Quando houver números, use cálculos simples e indique suposições. "
        "Não invente dados: se faltar informação, peça exatamente o que precisa. "
        "Não forneça aconselhamento legal; foque em educação financeira."
    )

    mode_label = {
        "credit_cards": "Acompanhamento de cartões de crédito",
        "loans": "Gestão de empréstimos e financiamentos",
        "calculators": "Calculadoras financeiras (juros, inflação, parcelamento)",
        "general": "Assistente financeiro",
    }.get(mode, "Assistente financeiro")

    try:
        # O contexto do cliente é opcional; o principal é o resumo do workspace.
        context_str = json.dumps(context, ensure_ascii=False)
    except Exception:
        context_str = "{}"

    try:
        workspace_context_str = json.dumps(workspace_context, ensure_ascii=False)
    except Exception:
        workspace_context_str = "{}"

    user_prompt = (
        f"Módulo: {mode_label}\n"
        f"UserId: {user_id_int}\n"
        f"WorkspaceId: {active_workspace_id}\n"
        f"Resumo do workspace (JSON): {workspace_context_str}\n"
        f"Contexto do app (JSON): {context_str}\n\n"
        f"Pergunta do usuário: {message}\n\n"
        "Regras:\n"
        "- Baseie a resposta nos dados do 'Resumo do workspace' sempre que fizer sentido.\n"
        "- Se o usuário pedir algo que exige dados que não existem no resumo (ex.: limite por cartão), peça quais dados faltam e sugira como registrar/organizar.\n"
        "- Retorne uma resposta direta com passos práticos."
    )

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 700,
            },
            timeout=12,
        )

        if response.status_code != 200:
            resp = jsonify({
                "success": False,
                "message": "Falha ao consultar IA.",
            })
            return _cors_wrap(resp, origin), 502

        result = response.json() or {}
        content = (result.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        content = content.strip()

        if not content:
            resp = jsonify({
                "success": False,
                "message": "IA retornou resposta vazia.",
            })
            return _cors_wrap(resp, origin), 502

        resp = jsonify({
            "success": True,
            "mode": mode,
            "answer": content,
        })
        return _cors_wrap(resp, origin), 200

    except Exception:
        resp = jsonify({
            "success": False,
            "message": "Erro ao processar IA.",
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
        db.session.commit()
        
        # NÃO criar workspace automaticamente - usuário deve criar manualmente após login
        
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


# ============================================================================
# WORKSPACE MANAGEMENT ENDPOINTS
# ============================================================================

@api_financeiro_bp.route("/api/workspaces", methods=["GET", "OPTIONS"])
def api_get_workspaces():
    """Lista todos os workspaces do usuário"""
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, OPTIONS")
    
    try:
        user_id = _get_user_id_from_request()
        print(f"[WORKSPACE] GET /api/workspaces - user_id={user_id}")
        
        if not user_id:
            return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400
        
        # Buscar workspaces onde usuário é owner ou membro
        print(f"[WORKSPACE] Buscando workspaces para user_id={user_id}")
        owned_workspaces = Workspace.query.filter_by(owner_id=user_id).all()
        member_links = WorkspaceMember.query.filter_by(user_id=user_id).all()
        workspace_ids = {w.id for w in owned_workspaces} | {m.workspace_id for m in member_links}
        all_workspaces = Workspace.query.filter(Workspace.id.in_(workspace_ids)).all() if workspace_ids else []
        print(f"[WORKSPACE] Encontrados {len(all_workspaces)} workspaces (owner ou membro)")
        
        # Mapear status de onboarding
        member_status = {m.workspace_id: (m.onboarding_completed, m.share_preferences) for m in member_links}
        
        workspaces_data = []
        for w in all_workspaces:
            onboarding_completed, prefs = member_status.get(w.id, (True, None)) if w.owner_id != user_id else (True, None)
            # Buscar informações do owner
            owner = User.query.get(w.owner_id) if w.owner_id else None
            workspaces_data.append({
                "id": w.id,
                "name": w.name,
                "description": w.description or "",
                "color": w.color or "#3b82f6",
                "is_owner": w.owner_id == user_id,
                "created_at": w.created_at.isoformat() if w.created_at else None,
                "onboarding_completed": onboarding_completed,
                "share_preferences": prefs or {},
                "owner_email": owner.email if owner else None,
                "owner_name": owner.email.split('@')[0] if owner else None,  # Nome baseado no email
            })
        
        print(f"[WORKSPACE] Retornando {len(workspaces_data)} workspaces para user_id={user_id}")
        
        return _cors_wrap(jsonify({"success": True, "workspaces": workspaces_data}), origin), 200
        
    except Exception as e:
        print(f"[WORKSPACE] ERRO no GET /api/workspaces: {e}")
        import traceback
        traceback.print_exc()
        return _cors_wrap(jsonify({"success": False, "message": "Erro interno no servidor", "error": str(e)}), origin), 500


@api_financeiro_bp.route("/api/workspaces/active", methods=["GET", "OPTIONS"])
def api_get_active_workspace_legacy():
    """Retorna o workspace ativo do usuário (legado - mantém compatibilidade)"""
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, OPTIONS")
    
    user_id = _get_user_id_from_request()
    if not user_id:
        return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400

    # Se o cliente forneceu workspace_id explicitamente, respeitar (desde que tenha acesso)
    workspace_id_hint = None
    try:
        workspace_id_hint = request.args.get("workspace_id")
        if workspace_id_hint:
            workspace_id_hint = int(workspace_id_hint)
    except Exception:
        workspace_id_hint = None

    if workspace_id_hint:
        hinted = Workspace.query.get(workspace_id_hint)
        if hinted:
            member = WorkspaceMember.query.filter_by(workspace_id=hinted.id, user_id=user_id).first()
            has_access = hinted.owner_id == user_id or member
            if has_access:
                session[f"active_workspace_{user_id}"] = hinted.id
                owner = User.query.get(hinted.owner_id) if hinted.owner_id else None
                return _cors_wrap(jsonify({
                    "success": True,
                    "workspace": {
                        "id": hinted.id,
                        "name": hinted.name,
                        "description": hinted.description,
                        "color": hinted.color,
                        "is_owner": hinted.owner_id == user_id,
                        "owner_email": owner.email if owner else None,
                        "owner_name": owner.email.split('@')[0] if owner else None,
                    }
                }), origin), 200
    
    # Buscar workspace ativo na sessão
    active_workspace_id = session.get(f"active_workspace_{user_id}")
    
    if active_workspace_id:
        workspace = Workspace.query.get(active_workspace_id)
        if workspace:
            member = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=user_id).first()
            has_access = workspace.owner_id == user_id or member
            if has_access:
                # Buscar informações do owner
                owner = User.query.get(workspace.owner_id) if workspace.owner_id else None
                return _cors_wrap(jsonify({
                    "success": True,
                    "workspace": {
                        "id": workspace.id,
                        "name": workspace.name,
                        "description": workspace.description,
                        "color": workspace.color,
                        "is_owner": workspace.owner_id == user_id,
                        "owner_email": owner.email if owner else None,
                        "owner_name": owner.email.split('@')[0] if owner else None,
                    }
                }), origin), 200
    
    # Se não tem workspace ativo, pegar o primeiro workspace do usuário (owner ou membro)
    workspace = Workspace.query.filter_by(owner_id=user_id).first()
    if not workspace:
        # Se não é owner, buscar primeiro workspace onde é membro
        member = WorkspaceMember.query.filter_by(user_id=user_id).first()
        if member:
            workspace = Workspace.query.get(member.workspace_id)
            print(f"[ACTIVE_WS] Membro encontrado - workspace_id={workspace.id if workspace else None}")
    
    if workspace:
        # SEMPRE definir o workspace ativo na sessão
        session[f"active_workspace_{user_id}"] = workspace.id
        print(f"[ACTIVE_WS] Definindo workspace ativo na sessão: user_id={user_id}, workspace_id={workspace.id}")
        
        # Buscar informações do owner
        owner = User.query.get(workspace.owner_id) if workspace.owner_id else None
        return _cors_wrap(jsonify({
            "success": True,
            "workspace": {
                "id": workspace.id,
                "name": workspace.name,
                "description": workspace.description,
                "color": workspace.color,
                "is_owner": workspace.owner_id == user_id,
                "owner_email": owner.email if owner else None,
                "owner_name": owner.email.split('@')[0] if owner else None,
            }
        }), origin), 200
    
    # Se não tem nenhum workspace, retornar erro
    return _cors_wrap(jsonify({
        "success": False,
        "message": "Nenhum workspace encontrado. Crie um workspace primeiro."
    }), origin), 404


@api_financeiro_bp.route("/api/workspaces", methods=["POST", "OPTIONS"])
def api_create_workspace():
    """Cria um novo workspace"""
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")
    
    try:
        user_id = _get_user_id_from_request()
        print(f"[WORKSPACE] POST /api/workspaces - user_id={user_id}")
        
        if not user_id:
            return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400
        
        data = request.get_json()
        name = data.get("name", "").strip()
        print(f"[WORKSPACE] Criando workspace com nome='{name}' para user_id={user_id}")
        
        if not name:
            return _cors_wrap(jsonify({"success": False, "message": "Nome obrigatório"}), origin), 400
        
        workspace = Workspace(
            owner_id=user_id,
            name=name,
            description=data.get("description", ""),
            color=data.get("color", "#3b82f6"),
        )
        
        db.session.add(workspace)
        db.session.commit()
        print(f"[WORKSPACE] Workspace criado com sucesso: id={workspace.id}, name='{workspace.name}'")
        
        # Definir como workspace ativo
        session[f"active_workspace_{user_id}"] = workspace.id
        print(f"[WORKSPACE] Workspace id={workspace.id} definido como ativo para user_id={user_id}")
        
        return _cors_wrap(jsonify({
            "success": True,
            "workspace": {
                "id": workspace.id,
                "name": workspace.name,
                "description": workspace.description,
                "color": workspace.color,
            }
        }), origin), 201
        
    except Exception as e:
        print(f"[WORKSPACE] ERRO no POST /api/workspaces: {e}")
        import traceback
        traceback.print_exc()
        return _cors_wrap(jsonify({"success": False, "message": "Erro interno no servidor", "error": str(e)}), origin), 500


@api_financeiro_bp.route("/api/workspaces/<int:workspace_id>", methods=["PUT", "OPTIONS"])
def api_update_workspace(workspace_id):
    """Atualiza um workspace"""
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "PUT, OPTIONS")
    
    user_id = _get_user_id_from_request()
    if not user_id:
        return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400
    
    workspace = Workspace.query.get(workspace_id)
    if not workspace:
        return _cors_wrap(jsonify({"success": False, "message": "Workspace não encontrado"}), origin), 404
    
    if workspace.owner_id != user_id:
        return _cors_wrap(jsonify({"success": False, "message": "Sem permissão"}), origin), 403
    
    data = request.get_json()
    
    if "name" in data:
        workspace.name = data["name"].strip()
    if "description" in data:
        workspace.description = data["description"]
    if "color" in data:
        workspace.color = data["color"]
    
    db.session.commit()
    
    return _cors_wrap(jsonify({
        "success": True,
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
            "description": workspace.description,
            "color": workspace.color,
        }
    }), origin), 200


@api_financeiro_bp.route("/api/workspace/invite", methods=["POST", "OPTIONS"])
def api_invite_workspace_member():
    """Envia convite para um email participar de um workspace"""
    origin = request.headers.get("Origin", "*")

    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")

    try:
        user_id = _get_user_id_from_request()
        if not user_id:
            return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400

        data = request.get_json() or {}
        workspace_id = data.get("workspace_id")
        recipient_email = (data.get("recipient_email") or "").strip().lower()
        role = (data.get("role") or "viewer").strip().lower()

        if not isinstance(workspace_id, int):
            return _cors_wrap(jsonify({"success": False, "message": "workspace_id inválido"}), origin), 400

        if not recipient_email:
            return _cors_wrap(jsonify({"success": False, "message": "Email obrigatório"}), origin), 400

        email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not re.match(email_regex, recipient_email):
            return _cors_wrap(jsonify({"success": False, "message": "Email inválido"}), origin), 400

        allowed_roles = {"viewer", "editor", "owner"}
        if role not in allowed_roles:
            return _cors_wrap(jsonify({"success": False, "message": "Permissão inválida"}), origin), 400

        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            return _cors_wrap(jsonify({"success": False, "message": "Workspace não encontrado"}), origin), 404

        # Verificar se usuário solicitante tem acesso
        is_owner = workspace.owner_id == user_id
        is_member = WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=user_id).first()
        if not (is_owner or is_member):
            return _cors_wrap(jsonify({"success": False, "message": "Sem permissão"}), origin), 403

        inviter = User.query.get(user_id)
        if not inviter:
            return _cors_wrap(jsonify({"success": False, "message": "Usuário não encontrado"}), origin), 400

        if inviter.email.lower() == recipient_email:
            return _cors_wrap(jsonify({"success": False, "message": "Não é possível convidar a si mesmo"}), origin), 400

        # Verificar se email já é membro
        existing_user = User.query.filter(func.lower(User.email) == recipient_email).first()
        if existing_user:
            member_record = WorkspaceMember.query.filter_by(
                workspace_id=workspace_id,
                user_id=existing_user.id
            ).first()
            if member_record or workspace.owner_id == existing_user.id:
                return _cors_wrap(jsonify({"success": False, "message": "Usuário já faz parte do workspace"}), origin), 400

        # Verificar convite pendente
        pending_invite = WorkspaceInvite.query.filter_by(
            workspace_id=workspace_id,
            invited_email=recipient_email,
            status="pending"
        ).first()
        if pending_invite:
            return _cors_wrap(jsonify({"success": False, "message": "Convite pendente já enviado para este email"}), origin), 400

        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(days=7)

        invite = WorkspaceInvite(
            workspace_id=workspace_id,
            invited_by_id=user_id,
            invited_email=recipient_email,
            invited_user_id=existing_user.id if existing_user else None,
            role=role,
            token=token,
            status="pending",
            expires_at=expires_at,
        )

        db.session.add(invite)
        db.session.commit()

        email_sent = send_workspace_invitation(
            recipient_email=recipient_email,
            inviter_email=inviter.email,
            token=token,
            workspace_name=workspace.name,
            role=role,
            app=current_app,
        )

        if not email_sent:
            return _cors_wrap(jsonify({"success": False, "message": "Convite salvo, mas falha ao enviar email"}), origin), 500

        return _cors_wrap(jsonify({"success": True, "message": "Convite enviado!"}), origin), 201

    except Exception as e:
        db.session.rollback()
        print(f"[WORKSPACE_INVITE] ERRO: {e}")
        return _cors_wrap(jsonify({"success": False, "message": "Erro interno no servidor"}), origin), 500


@api_financeiro_bp.route("/api/user/active-workspace", methods=["GET", "OPTIONS"])
def api_get_user_active_workspace():
    """Retorna o workspace ativo (ou primeiro disponível) para o usuário"""
    origin = request.headers.get("Origin", "*")

    if request.method == "OPTIONS":
        return _cors_preflight(origin, "GET, OPTIONS")

    try:
        user_id = _get_user_id_from_request()
        if not user_id:
            return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400

        # 1) Se tiver workspace ativo em sessão e o usuário tem acesso, retorna
        active_ws_id = session.get(f"active_workspace_{user_id}")
        workspace = None
        if active_ws_id:
            ws = Workspace.query.get(active_ws_id)
            if ws and (ws.owner_id == user_id or WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user_id).first()):
                workspace = ws

        # 2) Se não houver em sessão, procurar primeiro workspace onde é dono
        if not workspace:
            workspace = Workspace.query.filter_by(owner_id=user_id).order_by(Workspace.id.asc()).first()

        # 3) Se ainda não houver, pegar primeiro onde é membro
        if not workspace:
            member = WorkspaceMember.query.filter_by(user_id=user_id).order_by(WorkspaceMember.id.asc()).first()
            if member:
                workspace = Workspace.query.get(member.workspace_id)

        if not workspace:
            return _cors_wrap(jsonify({"success": False, "message": "Nenhum workspace encontrado"}), origin), 404

        # Atualiza sessão com workspace ativo
        session[f"active_workspace_{user_id}"] = workspace.id

        return _cors_wrap(jsonify({
            "success": True,
            "workspace_id": workspace.id,
            "name": workspace.name,
        }), origin), 200

    except Exception as e:
        print(f"[WORKSPACE] ERRO no GET /api/user/active-workspace: {e}")
        return _cors_wrap(jsonify({"success": False, "message": "Erro interno no servidor"}), origin), 500


@api_financeiro_bp.route("/api/workspaces/<int:workspace_id>/activate", methods=["POST", "OPTIONS"])
def api_activate_workspace(workspace_id):
    """Define um workspace como ativo"""
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")
    
    user_id = _get_user_id_from_request()
    if not user_id:
        return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400
    
    workspace = Workspace.query.get(workspace_id)
    if not workspace:
        return _cors_wrap(jsonify({"success": False, "message": "Workspace não encontrado"}), origin), 404
    
    # Verificar se usuário tem acesso
    member = WorkspaceMember.query.filter_by(
        workspace_id=workspace_id, user_id=user_id
    ).first()
    if workspace.owner_id != user_id and not member:
        return _cors_wrap(jsonify({"success": False, "message": "Sem permissão"}), origin), 403
    
    session[f"active_workspace_{user_id}"] = workspace.id
    
    return _cors_wrap(jsonify({
        "success": True,
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
            "description": workspace.description,
            "color": workspace.color,
        }
    }), origin), 200


@api_financeiro_bp.route("/api/workspaces/<int:workspace_id>/complete_onboarding", methods=["POST", "OPTIONS"])
def api_complete_onboarding(workspace_id):
    """Marca onboarding como concluído e salva preferências de compartilhamento."""
    origin = request.headers.get("Origin", "*")
    
    if request.method == "OPTIONS":
        return _cors_preflight(origin, "POST, OPTIONS")
    
    try:
        user_id = _get_user_id_from_request()
        if not user_id:
            return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400
        
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            return _cors_wrap(jsonify({"success": False, "message": "Workspace não encontrado"}), origin), 404
        
        member = WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=user_id).first()
        if not member and workspace.owner_id != user_id:
            return _cors_wrap(jsonify({"success": False, "message": "Sem permissão"}), origin), 403
        
        data = request.get_json() or {}
        share_preferences = data.get("share_preferences") or {}
        
        if member:
            member.onboarding_completed = True
            member.share_preferences = share_preferences
        else:
            # Owner não tem registro em workspace_members; nada a salvar além de seguir.
            pass
        
        db.session.commit()
        session[f"active_workspace_{user_id}"] = workspace_id
        
        return _cors_wrap(jsonify({
            "success": True,
            "workspace_id": workspace_id,
            "onboarding_completed": True
        }), origin), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        return _cors_wrap(jsonify({"success": False, "message": "Erro ao salvar onboarding", "error": str(e)}), origin), 500
    except Exception as e:
        db.session.rollback()
        return _cors_wrap(jsonify({"success": False, "message": "Erro interno", "error": str(e)}), origin), 500


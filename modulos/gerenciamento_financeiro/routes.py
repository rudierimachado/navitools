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
)
from sqlalchemy import func, extract, and_, or_
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
import calendar
import os

from extensions import db
from email_service import send_share_invitation, send_share_accepted, send_verification_code, send_password_reset, send_workspace_invitation
from models import (
    User,
    LoginAudit,
    FinanceConfig,
    FamilyMember,
    Category,
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

def _ensure_default_categories(user_id: int):
    """Garante que existam categorias padrão para o usuário"""
    config = FinanceConfig.query.filter_by(user_id=user_id).first()
    if not config:
        config = FinanceConfig(user_id=user_id, setup_completed=True)
        db.session.add(config)
        db.session.flush()

    # Verificar se já existem categorias
    existing_count = Category.query.filter_by(config_id=config.id).count()
    if existing_count > 0:
        return

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
        print(f"Erro ao criar categorias padrão: {e}")

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

@gerenciamento_financeiro_bp.route("/")
def home():
    if "finance_user_id" not in session:
        return redirect(url_for("gerenciamento_financeiro.login", next=request.path))
    
    # Verificar se tem workspace ativo na sessão
    if "active_workspace_id" not in session:
        user_id = session["finance_user_id"]
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
    
    # Garantir categorias padrão
    _ensure_default_categories(user_id)

    # Estatísticas principais
    today = datetime.utcnow().date()
    month_start = today.replace(day=1)

    # Totais gerais (do workspace ativo)
    total_income = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(Transaction.workspace_id == workspace_id, Transaction.type == "income")
        .scalar()
    )
    total_expense = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(Transaction.workspace_id == workspace_id, Transaction.type == "expense")
        .scalar()
    )

    # Totais do mês atual (do workspace ativo)
    monthly_income = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "income",
            Transaction.transaction_date >= month_start,
        )
        .scalar()
    )
    monthly_expense = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
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
        )
        .count()
    )
    expense_count = (
        Transaction.query
        .filter(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
        )
        .count()
    )

    balance = (total_income or 0) - (total_expense or 0)
    savings = (monthly_income or 0) - (monthly_expense or 0)
    savings_rate = (savings / monthly_income * 100) if monthly_income else 0

    # Transações recentes (do workspace ativo)
    recent_transactions = (
        Transaction.query.filter(Transaction.workspace_id == workspace_id)
        .order_by(Transaction.transaction_date.desc())
        .limit(10)
        .all()
    )

    # Vencimentos próximos (despesas não pagas) (do workspace ativo)
    today = date.today()
    vencimentos = (
        Transaction.query
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
        savings=savings,
        savings_rate=savings_rate,
        income_count=income_count,
        expense_count=expense_count,
        recent_transactions=recent_transactions,
        vencimentos=vencimentos,
        now=datetime.now(),
        active_workspace=active_workspace,
    )

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
    
    # Debug
    print(f"[SELECT_WORKSPACE] user_id={user_id} owned_count={len(owned_workspaces)} shared_count={len(shared_workspaces)}")
    print(f"[SELECT_WORKSPACE] owned_ids={owned_ids}")
    for m in shared_workspace_members:
        print(f"[SELECT_WORKSPACE] member: workspace_id={m.workspace_id} user_id={m.user_id} role={m.role}")
    
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

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Informe e-mail e senha.", "danger")
            return render_template("finance_login.html", user=None)

        user = User.query.filter(func.lower(User.email) == email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("E-mail ou senha inválidos.", "danger")
            _log_attempt(email, False, "Credenciais inválidas")
            return render_template("finance_login.html", user=None)

        # Autenticação bem-sucedida
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
                        print(f"Erro ao enviar email de confirmação de compartilhamento: {e}")
            except Exception as e:
                db.session.rollback()
                print(f"Erro ao aceitar convite de compartilhamento no login: {e}")

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
                print(f"Erro ao aceitar convite de workspace no login: {e}")

        return redirect(url_for("gerenciamento_financeiro.select_workspace"))

    return render_template("finance_login.html", user=None)


@gerenciamento_financeiro_bp.route("/invites/<string:token>", methods=["GET"])
def open_workspace_invite(token):
    """Link simples de convite. Se estiver logado, aceita; se não, redireciona para login."""
    print(f"[OPEN_INVITE] Token recebido: {token[:20]}...")
    
    if "finance_user_id" not in session:
        print(f"[OPEN_INVITE] Usuário não logado, redirecionando para login")
        return redirect(url_for("gerenciamento_financeiro.login", accept_invite_token=token))

    user_id = session["finance_user_id"]
    user = User.query.get(user_id)
    print(f"[OPEN_INVITE] Usuário logado: id={user_id} email={user.email}")

    try:
        invite = WorkspaceInvite.query.filter_by(token=token).first()
        if not invite:
            print(f"[OPEN_INVITE] Convite não encontrado para token")
            flash("Convite inválido.", "danger")
            return redirect(url_for("gerenciamento_financeiro.select_workspace"))

        print(f"[OPEN_INVITE] Convite encontrado: id={invite.id} status={invite.status} workspace_id={invite.workspace_id} invited_email={invite.invited_email}")

        if invite.status != "pending" or invite.expires_at < datetime.utcnow():
            print(f"[OPEN_INVITE] Convite expirado ou já usado: status={invite.status} expires={invite.expires_at}")
            flash("Convite expirado ou já utilizado.", "warning")
            return redirect(url_for("gerenciamento_financeiro.select_workspace"))

        if invite.invited_email.lower() != user.email.lower() and invite.invited_user_id not in (None, user.id):
            print(f"[OPEN_INVITE] Convite não é para este usuário: invited_email={invite.invited_email} user_email={user.email}")
            flash("Este convite não é para o seu usuário.", "danger")
            return redirect(url_for("gerenciamento_financeiro.select_workspace"))

        existing = WorkspaceMember.query.filter_by(workspace_id=invite.workspace_id, user_id=user.id).first()
        if not existing:
            member = WorkspaceMember(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role)
            db.session.add(member)
            print(f"[OPEN_INVITE] Novo membro criado: workspace_id={invite.workspace_id} user_id={user.id} role={invite.role}")
        else:
            print(f"[OPEN_INVITE] Usuário já é membro do workspace")

        invite.status = "accepted"
        invite.responded_at = datetime.utcnow()
        invite.invited_user_id = user.id
        db.session.commit()
        print(f"[OPEN_INVITE] Convite aceito com sucesso!")

        flash("Convite aceito! Agora você tem acesso ao workspace.", "success")
        return redirect(url_for("gerenciamento_financeiro.select_workspace"))

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao aceitar convite por token: {e}")
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

    # Logs de depuração
    print("[API LOGIN] Requisição recebida do APP_FIN")
    print(f"[API LOGIN] IP: {request.remote_addr}")
    print(f"[API LOGIN] User-Agent: {request.headers.get('User-Agent')}")
    print(f"[API LOGIN] Payload bruto: {data}")
    print(f"[API LOGIN] Email normalizado: {email!r}")

    if not email or not password:
        print("[API LOGIN] Falha: email ou senha vazios")
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
        print(f"[API LOGIN] Usuário não encontrado no banco local para email={email!r}")
        _log_attempt(email, False, "Credenciais inválidas")
        resp = jsonify({
            "success": False,
            "message": "E-mail ou senha inválidos.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401

    if not check_password_hash(user.password_hash, password):
        print(f"[API LOGIN] Senha inválida para email={email!r} (usuário id={user.id})")
        _log_attempt(email, False, "Credenciais inválidas")
        resp = jsonify({
            "success": False,
            "message": "E-mail ou senha inválidos.",
        })
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401

    # Autenticação bem-sucedida (mesma lógica da rota HTML)
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

    print(f"[API LOGIN] Login bem-sucedido para email={email!r}, user_id={user.id}")

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
            print(f"Erro no cadastro/verificação de email: {e}")
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
                print(f"Erro ao aceitar convite: {e}")
        
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
            print(f"Erro ao solicitar recuperação de senha: {e}")
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
            amount = data.get("amount")
            transaction_type = data.get("type", "").strip()
            frequency = data.get("frequency", "").strip()
            category_id = data.get("category_id")
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
            
            if not frequency:
                return _json({"error": "Frequência é obrigatória"}, 400)
            
            if not category_id or category_id <= 0:
                return _json({"error": "Categoria é obrigatória"}, 400)
                
            if transaction_type not in ['income', 'expense']:
                return _json({"error": "Tipo deve ser 'income' ou 'expense'"}, 400)
            
            # Garantir categorias padrão antes de criar transação
            _ensure_default_categories(user_id)
            
            # Validar e obter data da transação
            if data.get("transaction_date"):
                try:
                    transaction_date = datetime.strptime(data["transaction_date"], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    return _json({"error": "Data inválida. Use o formato YYYY-MM-DD"}, 400)
            else:
                transaction_date = date.today()
            
            is_recurring = data.get("is_recurring", False)
            
            # Se é recorrente, criar transações para os próximos 12 meses
            if is_recurring:
                from dateutil.relativedelta import relativedelta
                transactions_created = []
                
                for month_offset in range(12):
                    new_date = transaction_date + relativedelta(months=month_offset)
                    
                    transaction = Transaction(
                        user_id=user_id,
                        workspace_id=workspace_id,
                        description=description,
                        amount=float(amount),
                        type=transaction_type,
                        category_id=category_id,
                        transaction_date=new_date,
                        frequency=frequency,
                        is_recurring=True,
                        is_paid=True,
                        is_fixed=data.get("is_fixed", False)
                    )
                    db.session.add(transaction)
                    transactions_created.append(transaction)
                
                db.session.commit()
                
                resp = jsonify({"message": "Transações criadas com sucesso!", "created": len(transactions_created)})
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                return resp
                
            else:
                # Transação única
                transaction = Transaction(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    description=description,
                    amount=float(amount),
                    type=transaction_type,
                    category_id=category_id,
                    transaction_date=transaction_date,
                    frequency=frequency,
                    is_recurring=False,
                    is_paid=True,
                    is_fixed=data.get("is_fixed", False)
                )
                
                db.session.add(transaction)
                db.session.commit()

                category = Category.query.get(transaction.category_id) if transaction.category_id else None
                return _json({
                    "message": "Transação criada com sucesso!",
                    "id": transaction.id,
                    "description": transaction.description,
                    "amount": float(transaction.amount),
                    "type": transaction.type,
                    "transaction_date": transaction.transaction_date.isoformat(),
                    "frequency": getattr(transaction, "frequency", "once"),
                    "is_recurring": getattr(transaction, "is_recurring", False),
                    "is_fixed": getattr(transaction, "is_fixed", False),
                    "category": {
                        "id": category.id,
                        "name": category.name,
                        "icon": category.icon,
                        "color": category.color,
                    } if category else None,
                }, 200)
            
        except ValueError as ve:
            db.session.rollback()
            return _json({"error": f"Erro de validação: {str(ve)}"}, 400)
        except Exception as e:
            db.session.rollback()
            import traceback
            error_details = traceback.format_exc()
            print(f"Erro ao criar transação: {e}")
            print(f"Detalhes do erro:\n{error_details}")
            return _json({"error": f"Erro interno do servidor: {str(e)}"}, 500)
    
    else:  # GET
        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 10))
            transaction_type = request.args.get("type")
            category_id = request.args.get("category_id")
            start_date = request.args.get("start_date")
            end_date = request.args.get("end_date")
            
            # Filtrar por workspace ativo
            query = Transaction.query.filter_by(workspace_id=workspace_id)
            
            if transaction_type:
                query = query.filter_by(type=transaction_type)
            if category_id:
                query = query.filter_by(category_id=category_id)
            if start_date:
                query = query.filter(Transaction.transaction_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
            if end_date:
                query = query.filter(Transaction.transaction_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
            
            query = query.order_by(Transaction.transaction_date.desc())
            
            transactions = query.paginate(
                page=page, 
                per_page=per_page, 
                error_out=False
            )
            
            resp = jsonify({
                "transactions": [{
                    "id": t.id,
                    "description": t.description,
                    "amount": float(t.amount),
                    "type": t.type,
                    "transaction_date": t.transaction_date.isoformat(),
                    "frequency": getattr(t, 'frequency', 'once'),
                    "is_recurring": getattr(t, 'is_recurring', False),
                    "is_fixed": getattr(t, 'is_fixed', False),
                    "category": {
                        "id": t.category.id,
                        "name": t.category.name,
                        "icon": t.category.icon,
                        "color": t.category.color
                    } if t.category else None
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
            print(f"Erro ao buscar transações: {e}")
            resp = jsonify({"error": "Erro ao buscar transações"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 500

@gerenciamento_financeiro_bp.route("/api/transactions/<int:transaction_id>", methods=["PUT", "DELETE"])
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

    # A partir daqui, transações são do workspace (não do criador)
    transaction = Transaction.query.filter_by(id=transaction_id, workspace_id=workspace_id).first()
    
    if not transaction:
        return _json({"error": "Transação não encontrada"}, 404)
    
    if request.method == "PUT":
        try:
            if workspace_role == "viewer":
                return _json({"error": "Sem permissão para editar (somente visualização)"}, 403)

            data = request.get_json()
            
            if "description" in data:
                transaction.description = data["description"]
            if "amount" in data:
                transaction.amount = float(data["amount"])
            if "transaction_date" in data:
                transaction.transaction_date = datetime.strptime(data["transaction_date"], "%Y-%m-%d").date()
            if "frequency" in data:
                transaction.frequency = data["frequency"]
            if "is_recurring" in data:
                transaction.is_recurring = bool(data["is_recurring"])
            if "is_fixed" in data:
                transaction.is_fixed = bool(data["is_fixed"])
            if "category_id" in data:
                transaction.category_id = data["category_id"] or None
            if "is_paid" in data:
                transaction.is_paid = bool(data["is_paid"])
            if "paid_date" in data and data["paid_date"]:
                transaction.paid_date = datetime.strptime(data["paid_date"], "%Y-%m-%d").date()
            
            db.session.commit()

            category = Category.query.get(transaction.category_id) if transaction.category_id else None
            resp = jsonify({
                "message": "Transação atualizada com sucesso!",
                "id": transaction.id,
                "description": transaction.description,
                "amount": float(transaction.amount),
                "type": transaction.type,
                "transaction_date": transaction.transaction_date.isoformat(),
                "frequency": getattr(transaction, 'frequency', 'once'),
                "is_recurring": getattr(transaction, 'is_recurring', False),
                "is_fixed": getattr(transaction, 'is_fixed', False),
                "category": {
                    "id": category.id,
                    "name": category.name,
                    "icon": category.icon,
                    "color": category.color,
                } if category else None,
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

            db.session.delete(transaction)
            db.session.commit()
            return _json({"message": "Transação excluída com sucesso", "id": transaction_id}, 200)
        except Exception as e:
            db.session.rollback()
            return _json({"error": str(e)}, 500)

    return _json({"error": "Método não suportado"}, 405)

@gerenciamento_financeiro_bp.route("/api/dashboard-stats", methods=["GET", "OPTIONS"])
@gerenciamento_financeiro_bp.route("/api/dashboard-stats/", methods=["GET", "OPTIONS"])
def api_dashboard_stats():
    """Retorna estatísticas do dashboard para o app/API.

    Agora com suporte a CORS para Flutter Web.
    """

    origin = request.headers.get("Origin", "*")

    # Pré-flight CORS
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    user_id: int | None = None

    # Tentar usar sessão Flask primeiro
    if "finance_user_id" in session:
        user_id = session["finance_user_id"]
    else:
        # Fallback para apps que não conseguem enviar cookies (ex: Flutter Web)
        user_id = request.args.get("user_id", type=int)

    if not user_id:
        resp = jsonify({"error": "Não autorizado"})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401
    today = datetime.utcnow().date()
    month_start = today.replace(day=1)

    total_income = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter_by(user_id=user_id, type="income")
        .scalar()
    )
    total_expense = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter_by(user_id=user_id, type="expense")
        .scalar()
    )

    monthly_income = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == user_id,
            Transaction.type == "income",
            Transaction.transaction_date >= month_start,
        )
        .scalar()
    )
    monthly_expense = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
        )
        .scalar()
    )

    income_count = (
        Transaction.query
        .filter(
            Transaction.user_id == user_id,
            Transaction.type == "income",
            Transaction.transaction_date >= month_start,
        )
        .count()
    )
    expense_count = (
        Transaction.query
        .filter(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
        )
        .count()
    )

    balance = (total_income or 0) - (total_expense or 0)
    savings = (monthly_income or 0) - (monthly_expense or 0)
    savings_rate = (savings / monthly_income * 100) if monthly_income else 0

    resp = jsonify({
        "balance": float(balance),
        "monthly_income": float(monthly_income),
        "monthly_expense": float(monthly_expense),
        "income_count": income_count,
        "expense_count": expense_count,
        "savings_rate": savings_rate,
        "savings": float(savings),
    })
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

@gerenciamento_financeiro_bp.route("/api/recurring", methods=["GET", "POST"])
def api_recurring():
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
        
    user_id = session["finance_user_id"]
    
    if request.method == "POST":
        try:
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
            
            # Garantir categorias padrão antes de criar transação
            _ensure_default_categories(user_id)
            
            # Verificar se a categoria existe e pertence ao usuário
            if category_id:
                category = Category.query.filter_by(id=category_id, config_id=FinanceConfig.query.filter_by(user_id=user_id).first().id).first()
                if not category:
                    return jsonify({"error": "Categoria não encontrada ou não pertence ao usuário"}), 404
            else:
                # Se category_id não for fornecido, tentar encontrar uma categoria padrão
                config = FinanceConfig.query.filter_by(user_id=user_id).first()
                if not config:
                    return jsonify({"error": "Configuração financeira não encontrada para o usuário"}), 404
                category = Category.query.filter_by(config_id=config.id, type=transaction_type, is_default=True).first()
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

# ============================================================================
# API DE CATEGORIAS
# ============================================================================

@gerenciamento_financeiro_bp.route("/api/categories", methods=["GET", "POST"])
def api_categories():
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
        
    user_id = session["finance_user_id"]
    
    # Garantir que existe config
    _ensure_default_categories(user_id)
    config = FinanceConfig.query.filter_by(user_id=user_id).first()
    
    if request.method == "POST":
        try:
            data = request.get_json()
            
            if not data.get("name") or not data.get("type"):
                return jsonify({"error": "Campos obrigatórios: name, type"}), 400
            
            category = Category(
                config_id=config.id,
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
            
            query = Category.query.filter_by(config_id=config.id, is_active=True)
            
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

@gerenciamento_financeiro_bp.route("/api/categories/<int:category_id>", methods=["DELETE"])
def api_category_detail(category_id: int):
    """Permite operações sobre uma categoria específica (atualmente apenas DELETE)."""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401

    user_id = session["finance_user_id"]

    # Garantir que existe config do usuário
    _ensure_default_categories(user_id)
    config = FinanceConfig.query.filter_by(user_id=user_id).first()
    if not config:
        return jsonify({"error": "Configuração financeira não encontrada"}), 404

    category = Category.query.filter_by(id=category_id, config_id=config.id).first()
    if not category:
        return jsonify({"error": "Categoria não encontrada"}), 404

    if request.method == "DELETE":
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

@gerenciamento_financeiro_bp.route("/api/monthly-closure/close-month", methods=["POST"])
def api_close_month():
    """Fecha o mês atual e cria novo mês com despesas fixas carregadas"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        today = datetime.utcnow().date()
        year = today.year
        month = today.month
        
        # Verificar se já existe closure para este mês
        existing_closure = MonthlyClosure.query.filter_by(
            user_id=user_id,
            year=year,
            month=month
        ).first()
        
        if existing_closure and existing_closure.status == "closed":
            return jsonify({"error": "Este mês já foi fechado"}), 400
        
        # Calcular totais do mês
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(year, month + 1, 1) - timedelta(days=1)
        
        total_income = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.user_id == user_id,
            Transaction.type == "income",
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end
        ).scalar()
        
        total_expense = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end
        ).scalar()
        
        balance = float(total_income) - float(total_expense)
        
        # Criar ou atualizar closure do mês atual
        if not existing_closure:
            closure = MonthlyClosure(
                user_id=user_id,
                year=year,
                month=month,
                status="closed",
                total_income=total_income,
                total_expense=total_expense,
                balance=balance,
                closed_at=datetime.utcnow()
            )
            db.session.add(closure)
            db.session.flush()
        else:
            existing_closure.status = "closed"
            existing_closure.total_income = total_income
            existing_closure.total_expense = total_expense
            existing_closure.balance = balance
            existing_closure.closed_at = datetime.utcnow()
            closure = existing_closure
        
        # Criar closure para próximo mês
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        
        next_closure = MonthlyClosure.query.filter_by(
            user_id=user_id,
            year=next_year,
            month=next_month
        ).first()
        
        if not next_closure:
            next_closure = MonthlyClosure(
                user_id=user_id,
                year=next_year,
                month=next_month,
                status="open",
                total_income=0,
                total_expense=0,
                balance=0
            )
            db.session.add(next_closure)
            db.session.flush()
        
        # Copiar despesas fixas para próximo mês
        fixed_expenses = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.is_fixed == True,
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date <= month_end
        ).all()
        
        for expense in fixed_expenses:
            # Criar snapshot
            snapshot = MonthlyFixedExpense(
                monthly_closure_id=closure.id,
                original_transaction_id=expense.id,
                description=expense.description,
                amount=expense.amount,
                category_id=expense.category_id
            )
            db.session.add(snapshot)
            
            # Criar transação no próximo mês
            next_month_date = date(next_year, next_month, expense.transaction_date.day)
            new_transaction = Transaction(
                user_id=user_id,
                category_id=expense.category_id,
                description=expense.description,
                amount=expense.amount,
                type="expense",
                transaction_date=next_month_date,
                is_fixed=True,
                is_auto_loaded=True,
                monthly_closure_id=next_closure.id
            )
            db.session.add(new_transaction)
        
        db.session.commit()
        
        return jsonify({
            "message": "Mês fechado com sucesso",
            "closure": {
                "year": year,
                "month": month,
                "status": "closed",
                "total_income": float(total_income),
                "total_expense": float(total_expense),
                "balance": balance,
                "fixed_expenses_copied": len(fixed_expenses)
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        resp = jsonify({"error": str(e)})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 500


@gerenciamento_financeiro_bp.route("/api/monthly-closure/check-auto-close", methods=["POST"])
def api_check_auto_close():
    """Verifica se precisa fechar mês automaticamente na virada"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        today = datetime.utcnow().date()
        year = today.year
        month = today.month
        
        # Verificar se já existe closure para o mês atual
        current_closure = MonthlyClosure.query.filter_by(
            user_id=user_id,
            year=year,
            month=month
        ).first()
        
        # Se já existe e está aberto, não precisa fazer nada
        if current_closure and current_closure.status == "open":
            return jsonify({"auto_closed": False}), 200
        
        # Se não existe closure para o mês atual, verificar se o mês anterior está fechado
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        
        prev_closure = MonthlyClosure.query.filter_by(
            user_id=user_id,
            year=prev_year,
            month=prev_month
        ).first()
        
        # Se mês anterior não está fechado, fechar automaticamente
        if prev_closure and prev_closure.status == "open":
            # Calcular totais do mês anterior
            month_start = date(prev_year, prev_month, 1)
            if prev_month == 12:
                month_end = date(prev_year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(prev_year, prev_month + 1, 1) - timedelta(days=1)
            
            total_income = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.user_id == user_id,
                Transaction.type == "income",
                Transaction.transaction_date >= month_start,
                Transaction.transaction_date <= month_end
            ).scalar()
            
            total_expense = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.user_id == user_id,
                Transaction.type == "expense",
                Transaction.transaction_date >= month_start,
                Transaction.transaction_date <= month_end
            ).scalar()
            
            balance = float(total_income) - float(total_expense)
            
            # Fechar mês anterior
            prev_closure.status = "closed"
            prev_closure.total_income = total_income
            prev_closure.total_expense = total_expense
            prev_closure.balance = balance
            prev_closure.closed_at = datetime.utcnow()
            
            # Criar closure para mês atual se não existir
            if not current_closure:
                current_closure = MonthlyClosure(
                    user_id=user_id,
                    year=year,
                    month=month,
                    status="open",
                    total_income=0,
                    total_expense=0,
                    balance=0
                )
                db.session.add(current_closure)
                db.session.flush()
            
            # Copiar despesas fixas para o mês atual
            fixed_expenses = Transaction.query.filter(
                Transaction.user_id == user_id,
                Transaction.type == "expense",
                Transaction.is_fixed == True,
                Transaction.transaction_date >= month_start,
                Transaction.transaction_date <= month_end
            ).all()
            
            fixed_count = 0
            for expense in fixed_expenses:
                # Criar snapshot
                snapshot = MonthlyFixedExpense(
                    monthly_closure_id=prev_closure.id,
                    original_transaction_id=expense.id,
                    description=expense.description,
                    amount=expense.amount,
                    category_id=expense.category_id
                )
                db.session.add(snapshot)
                
                # Criar transação no mês atual
                try:
                    current_month_date = date(year, month, expense.transaction_date.day)
                except ValueError:
                    # Se o dia não existe no mês atual (ex: 31 em fevereiro), usar último dia
                    last_day = calendar.monthrange(year, month)[1]
                    current_month_date = date(year, month, last_day)
                
                new_transaction = Transaction(
                    user_id=user_id,
                    category_id=expense.category_id,
                    description=expense.description,
                    amount=expense.amount,
                    type="expense",
                    transaction_date=current_month_date,
                    is_fixed=True,
                    is_auto_loaded=True,
                    monthly_closure_id=current_closure.id
                )
                db.session.add(new_transaction)
                fixed_count += 1
            
            db.session.commit()
            
            return jsonify({
                "auto_closed": True,
                "previous_month": prev_month,
                "previous_year": prev_year,
                "fixed_expenses_copied": fixed_count
            }), 200
        
        return jsonify({"auto_closed": False}), 200
        
    except Exception as e:
        db.session.rollback()
        resp = jsonify({"error": str(e)})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 500


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

    try:
        payload_preview = request.get_json(silent=True)
    except Exception:
        payload_preview = None
    print(f"[SYSTEM SHARE] HIT path={request.path} method={request.method} user_id={session.get('finance_user_id')} payload={payload_preview}", flush=True)

    if "finance_user_id" not in session:
        print("[SYSTEM SHARE] 401 - finance_user_id ausente na sessão", flush=True)
        resp = jsonify({"error": "Não autorizado"})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401
    
    user_id = session["finance_user_id"]
    data = request.get_json()
    
    if not data or not data.get("email"):
        print(f"[SYSTEM SHARE] 400 - payload inválido: {data}", flush=True)
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
            print(f"Erro ao listar workspaces: {e}")
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

    try:
        payload_preview = request.get_json(silent=True)
    except Exception:
        payload_preview = None
    print(f"[WORKSPACE INVITE] HIT path={request.path} method={request.method} user_id={session.get('finance_user_id')} workspace_id={workspace_id} payload={payload_preview}", flush=True)

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
            print(f"[INVITE] send_workspace_invitation retornou={email_ok}")
        except Exception as e:
            print(f"Erro ao enviar email de convite: {e}")
        
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
        print(f"[WORKSPACE INVITE] 500 - {e}", flush=True)
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
            print(f"[ACCEPT_INVITE] Novo membro adicionado: user_id={user_id} workspace_id={invite.workspace_id}")
        else:
            print(f"[ACCEPT_INVITE] Usuário já é membro: user_id={user_id} workspace_id={invite.workspace_id}")
        
        invite.status = "accepted"
        invite.responded_at = datetime.utcnow()
        invite.invited_user_id = user_id
        db.session.commit()
        
        # Notificar quem convidou
        try:
            send_share_accepted(
                to_email=invite.invited_by.email,
                accepter_email=user.email,
                workspace_name=invite.workspace.name
            )
        except Exception as e:
            print(f"Erro ao enviar email de aceitação: {e}")
        
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

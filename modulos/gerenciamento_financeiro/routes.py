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
from email_service import send_share_invitation, send_share_accepted, send_verification_code, send_password_reset
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

@gerenciamento_financeiro_bp.route("/")
def home():
    if "finance_user_id" not in session:
        return redirect(url_for("gerenciamento_financeiro.login", next=request.path))

    user_id = session["finance_user_id"]
    user = User.query.get(user_id)
    
    # IDs de usuários cujos dados este usuário pode acessar
    accessible_ids = _get_accessible_user_ids(user_id)
    
    # Obter workspace ativo
    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        # Usar primeiro workspace do usuário
        workspace = Workspace.query.filter_by(owner_id=user_id).first()
        if workspace:
            workspace_id = workspace.id
            session["active_workspace_id"] = workspace_id
    
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
        
        # Garantir que o usuário tenha pelo menos um workspace
        workspace_count = Workspace.query.filter_by(owner_id=user.id).count()
        if workspace_count == 0:
            default_workspace = Workspace(
                owner_id=user.id,
                name="Meu Workspace",
                description="Workspace padrão",
                color="#3b82f6"
            )
            db.session.add(default_workspace)
            db.session.commit()
        
        flash("Bem-vindo ao painel financeiro!", "success")
        _log_attempt(email, True, user_id=user.id)

        # Verificar se há convite de compartilhamento a aceitar
        accept_share_id = request.args.get("accept_share_id")
        if accept_share_id and accept_share_id.isdigit():
            try:
                share_id_int = int(accept_share_id)
                share = SystemShare.query.get(share_id_int)

                if share and share.status == "pending" and share.shared_email.lower() == user.email.lower():
                    # Aceitar convite para este usuário
                    share.shared_user_id = user.id
                    share.status = "accepted"
                    share.accepted_at = datetime.utcnow()
                    db.session.commit()

                    # Feedback visual para o usuário
                    flash("Convite de compartilhamento encontrado e aceito com sucesso!", "success")

                    # Enviar email de confirmação para o dono
                    try:
                        from flask import current_app
                        send_share_accepted(
                            owner_email=share.owner.email,
                            shared_email=user.email,
                            app=current_app,
                        )
                    except Exception as e:  # pragma: no cover - apenas loga erro de email
                        print(f"Erro ao enviar email de confirmação de compartilhamento: {e}")

            except Exception as e:
                db.session.rollback()
                print(f"Erro ao aceitar convite de compartilhamento no login: {e}")

        next_url = request.args.get("next") or url_for("gerenciamento_financeiro.home")
        return redirect(next_url)

    return render_template("finance_login.html", user=None)

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

        # Criar usuário (ainda não verificado)
        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()

        # Criar workspace padrão
        default_workspace = Workspace(
            owner_id=user.id,
            name="Meu Workspace",
            description="Workspace padrão",
            color="#3b82f6"
        )
        db.session.add(default_workspace)
        db.session.commit()

        # Garantir categorias padrão
        _ensure_default_categories(user.id)

        # Gerar código de verificação de 6 dígitos
        verification_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        
        verification = EmailVerification(
            email=email,
            code=verification_code,
            expires_at=expires_at
        )
        db.session.add(verification)
        db.session.commit()

        # Enviar código por email
        from flask import current_app
        send_verification_code(email, verification_code, current_app)

        # Guardar email na sessão para verificação
        session['pending_verification_email'] = email
        session['pending_verification_user_id'] = user.id

        # Se o usuário chegou aqui a partir de um link de convite, guardar para depois
        accept_share_id = request.args.get("accept_share_id")
        if accept_share_id:
            session['pending_share_id'] = accept_share_id

        flash("Conta criada! Verifique seu email e insira o código de 6 dígitos.", "success")
        return redirect(url_for("gerenciamento_financeiro.verify_email"))

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
        
        # Sempre mostrar mensagem de sucesso (segurança)
        flash("Se este email estiver cadastrado, você receberá um link de recuperação.", "info")
        
        if user:
            # Gerar token único
            token = secrets.token_urlsafe(32)
            expires_at = datetime.utcnow() + timedelta(hours=1)
            
            reset = PasswordReset(
                user_id=user.id,
                token=token,
                expires_at=expires_at
            )
            db.session.add(reset)
            db.session.commit()
            
            # Enviar email com link
            from flask import current_app
            base_url = current_app.config.get('APP_BASE_URL', request.host_url.rstrip('/'))
            reset_link = f"{base_url}{url_for('gerenciamento_financeiro.reset_password', token=token)}"
            send_password_reset(email, reset_link, current_app)
        
        return redirect(url_for("gerenciamento_financeiro.login"))
    
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
        resp = jsonify({"error": "Não autorizado"})
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401

    accessible_ids = _get_accessible_user_ids(user_id)
    
    # Obter workspace_id da sessão ou usar o padrão
    workspace_id = session.get("active_workspace_id")
    if not workspace_id:
        # Usar primeiro workspace do usuário
        workspace = Workspace.query.filter_by(owner_id=user_id).first()
        if workspace:
            workspace_id = workspace.id
            session["active_workspace_id"] = workspace_id
    
    if request.method == "POST":
        try:
            data = request.get_json()
            
            # Validação melhorada
            if not data:
                return jsonify({"error": "Dados não fornecidos"}), 400
                
            description = data.get("description", "").strip()
            amount = data.get("amount")
            transaction_type = data.get("type", "").strip()
            frequency = data.get("frequency", "").strip()
            category_id = data.get("category_id")
            is_active = data.get("is_active", True)
                
            if not amount or amount <= 0:
                return jsonify({"error": "Valor deve ser maior que zero"}), 400
            
            if not frequency:
                return jsonify({"error": "Frequência é obrigatória"}), 400
            
            if not category_id:
                return jsonify({"error": "Categoria é obrigatória"}), 400
                
            if transaction_type not in ['income', 'expense']:
                return jsonify({"error": "Tipo deve ser 'income' ou 'expense'"}), 400
            
            # Garantir categorias padrão antes de criar transação
            _ensure_default_categories(user_id)
            
            transaction_date = datetime.strptime(data["transaction_date"], "%Y-%m-%d").date() if data.get("transaction_date") else date.today()
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
                
                resp = jsonify({"message": "Transação criada com sucesso!", "id": transaction.id})
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                return resp
            
        except ValueError as ve:
            db.session.rollback()
            return jsonify({"error": f"Erro de validação: {str(ve)}"}), 400
        except Exception as e:
            db.session.rollback()
            print(f"Erro ao criar transação: {e}")  # Log para debug
            resp = jsonify({"error": "Erro interno do servidor"})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 500
    
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
    transaction = Transaction.query.filter_by(id=transaction_id, user_id=user_id).first()
    
    if not transaction:
        return jsonify({"error": "Transação não encontrada"}), 404
    
    if request.method == "PUT":
        try:
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
            
            resp = jsonify({"message": "Transação atualizada com sucesso!"})
            resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp
            
        except Exception as e:
            db.session.rollback()
            resp = jsonify({"error": str(e)})
            resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 500

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
        return jsonify({"error": str(e)}), 500


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

@gerenciamento_financeiro_bp.route("/api/system/share", methods=["POST"])
def api_share_system():
    """Compartilha o sistema com outro usuário via email"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    data = request.get_json()
    
    if not data or not data.get("email"):
        return jsonify({"error": "Email é obrigatório"}), 400
    
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
        db.session.commit()
        
        # Enviar email de convite
        from flask import current_app
        send_share_invitation(
            recipient_email=shared_email,
            owner_email=user.email,
            access_level=access_level,
            share_id=share.id,
            app=current_app
        )
        
        return jsonify({
            "message": "Compartilhamento criado com sucesso!",
            "share": {
                "id": share.id,
                "email": share.shared_email,
                "status": share.status,
                "access_level": share.access_level,
                "created_at": share.created_at.isoformat()
            }
        }), 201
        
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
            return jsonify({"error": "Workspace não encontrado"}), 404
        
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
        
        return jsonify({
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
            from models import Workspace, WorkspaceMember
            
            # Workspaces que o usuário é dono
            owned = Workspace.query.filter_by(owner_id=user_id).all()
            
            # Workspaces compartilhados com o usuário
            shared_members = WorkspaceMember.query.filter_by(user_id=user_id).all()
            shared_workspace_ids = [m.workspace_id for m in shared_members]
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

@gerenciamento_financeiro_bp.route("/api/workspaces/<int:workspace_id>/share", methods=["POST"])
def api_share_workspace(workspace_id):
    """Compartilha um workspace com um usuário"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        from models import Workspace, WorkspaceMember
        
        workspace = Workspace.query.get(workspace_id)
        if not workspace or workspace.owner_id != user_id:
            return jsonify({"error": "Workspace não encontrado ou sem permissão"}), 404
        
        data = request.get_json()
        email = data.get("email", "").strip().lower()
        role = data.get("role", "editor")
        
        if not email:
            return jsonify({"error": "Email é obrigatório"}), 400
        
        # Buscar usuário
        target_user = User.query.filter(func.lower(User.email) == email).first()
        if not target_user:
            return jsonify({"error": "Usuário não encontrado"}), 404
        
        # Verificar se já é membro
        existing = WorkspaceMember.query.filter_by(
            workspace_id=workspace_id,
            user_id=target_user.id
        ).first()
        
        if existing:
            return jsonify({"error": "Usuário já é membro deste workspace"}), 400
        
        # Adicionar membro
        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=target_user.id,
            role=role
        )
        db.session.add(member)
        db.session.commit()
        
        return jsonify({
            "message": "Workspace compartilhado com sucesso",
            "user_email": target_user.email,
            "role": role
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@gerenciamento_financeiro_bp.route("/api/workspaces/<int:workspace_id>/members", methods=["GET"])
def api_workspace_members(workspace_id):
    """Lista membros de um workspace"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        from models import Workspace, WorkspaceMember
        
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            return jsonify({"error": "Workspace não encontrado"}), 404
        
        # Verificar permissão (dono ou membro)
        if workspace.owner_id != user_id:
            member = WorkspaceMember.query.filter_by(
                workspace_id=workspace_id,
                user_id=user_id
            ).first()
            if not member:
                return jsonify({"error": "Sem permissão"}), 403
        
        members = WorkspaceMember.query.filter_by(workspace_id=workspace_id).all()
        
        return jsonify({
            "members": [{
                "id": m.id,
                "email": m.user.email,
                "role": m.role,
                "joined_at": m.joined_at.isoformat()
            } for m in members]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@gerenciamento_financeiro_bp.route("/api/workspaces/<int:workspace_id>", methods=["PUT", "DELETE"])
def api_update_workspace(workspace_id):
    """Atualiza ou deleta um workspace"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    user_id = session["finance_user_id"]
    
    try:
        from models import Workspace
        
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            return jsonify({"error": "Workspace não encontrado"}), 404
        
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

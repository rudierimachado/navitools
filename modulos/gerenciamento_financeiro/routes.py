from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User, LoginAudit


gerenciamento_financeiro_bp = Blueprint(
    "gerenciamento_financeiro",
    __name__,
    template_folder="templates",
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


@gerenciamento_financeiro_bp.route("/")
def home():
    if "finance_user_id" not in session:
        return redirect(url_for("gerenciamento_financeiro.login", next=request.path))

    return render_template(
        "gerenciamento_financeiro.html",
        module_name="Gerenciamento Financeiro",
        module_version="0.1.0",
        module_status="Em desenvolvimento",
    )


@gerenciamento_financeiro_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Informe e-mail e senha.", "danger")
            return render_template("finance_login.html")

        user = User.query.filter(func.lower(User.email) == email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("E-mail ou senha inválidos.", "danger")
            _log_attempt(email, False, "Credenciais inválidas")
            return render_template("finance_login.html")

        session["finance_user_id"] = user.id
        session["finance_user_email"] = user.email
        flash("Bem-vindo ao painel financeiro!", "success")
        _log_attempt(email, True, user_id=user.id)

        next_url = request.args.get("next") or url_for("gerenciamento_financeiro.home")
        return redirect(next_url)

    return render_template("finance_login.html")


@gerenciamento_financeiro_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not email or not password:
            flash("Preencha todos os campos.", "danger")
            return render_template("finance_register.html")

        if "@" not in email:
            flash("E-mail inválido.", "danger")
            return render_template("finance_register.html")

        if password != confirm:
            flash("As senhas não coincidem.", "danger")
            return render_template("finance_register.html")

        if len(password) < 6:
            flash("Use uma senha com pelo menos 6 caracteres.", "danger")
            return render_template("finance_register.html")

        exists = User.query.filter(func.lower(User.email) == email).first()
        if exists:
            flash("Este e-mail já está cadastrado.", "warning")
            return render_template("finance_register.html")

        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()

        flash("Conta criada! Faça login para continuar.", "success")
        return redirect(url_for("gerenciamento_financeiro.login"))

    return render_template("finance_register.html")


@gerenciamento_financeiro_bp.route("/logout")
def logout():
    session.pop("finance_user_id", None)
    session.pop("finance_user_email", None)
    flash("Você saiu do painel financeiro.", "info")
    return redirect(url_for("gerenciamento_financeiro.login"))

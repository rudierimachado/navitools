from sqlalchemy import func
from werkzeug.security import check_password_hash

from extensions import db
from models import User, LoginAudit


def _log_attempt(email: str, succeeded: bool, message: str, request, user_id: int | None = None) -> None:
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


def process_login(email: str | None, password: str | None, request) -> dict:
    email = (email or "").strip().lower()
    password = password or ""

    if not email or not password:
        return {
            "success": False,
            "category": "danger",
            "message": "Informe e-mail e senha.",
            "user": None,
        }

    user = User.query.filter(func.lower(User.email) == email).first()

    if not user or not check_password_hash(user.password_hash, password):
        _log_attempt(email, False, "Credenciais inválidas", request)
        return {
            "success": False,
            "category": "danger",
            "message": "E-mail ou senha inválidos.",
            "user": None,
        }

    _log_attempt(email, True, "Login bem-sucedido", request, user_id=user.id)
    return {
        "success": True,
        "category": "success",
        "message": "Bem-vindo ao painel financeiro!",
        "user": user,
    }

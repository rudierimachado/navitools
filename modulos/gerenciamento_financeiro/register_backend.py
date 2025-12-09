from sqlalchemy import func
from werkzeug.security import generate_password_hash

from extensions import db
from models import User


def process_registration(email: str | None, password: str | None, confirm: str | None) -> dict:
    email = (email or "").strip().lower()
    password = password or ""
    confirm = confirm or ""

    if not email or not password:
        return {
            "success": False,
            "category": "danger",
            "message": "Preencha todos os campos.",
        }

    if "@" not in email:
        return {
            "success": False,
            "category": "danger",
            "message": "E-mail inválido.",
        }

    if password != confirm:
        return {
            "success": False,
            "category": "danger",
            "message": "As senhas não coincidem.",
        }

    if len(password) < 6:
        return {
            "success": False,
            "category": "danger",
            "message": "Use uma senha com pelo menos 6 caracteres.",
        }

    exists = User.query.filter(func.lower(User.email) == email).first()
    if exists:
        return {
            "success": False,
            "category": "warning",
            "message": "Este e-mail já está cadastrado.",
        }

    user = User(email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()

    return {
        "success": True,
        "category": "success",
        "message": "Conta criada! Faça login para continuar.",
    }

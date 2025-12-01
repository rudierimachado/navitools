from datetime import datetime

from werkzeug.security import generate_password_hash

from extensions import db

# Nota: Agora usando configuração centralizada do config_db.py
# Todas as configurações de banco estão em extensions.py


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email}>"


class LoginAudit(db.Model):
    __tablename__ = "login_audit"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    email = db.Column(db.String(255), nullable=False)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    succeeded = db.Column(db.Boolean, nullable=False)
    message = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref=db.backref("login_attempts", lazy="dynamic"))

    def __repr__(self) -> str:  # pragma: no cover
        status = "success" if self.succeeded else "failure"
        return f"<LoginAudit {self.email} {status}>"


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AdminUser {self.username}>"


class MenuItem(db.Model):
    __tablename__ = "menu_items"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    nivel = db.Column(db.Integer, nullable=False)
    ordem = db.Column(db.Integer, nullable=False, default=0)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    icone = db.Column(db.String(100))
    parent_id = db.Column(db.Integer)
    url = db.Column(db.String(255), nullable=False, default="/")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MenuItem {self.id} {self.nome} (nivel={self.nivel})>"

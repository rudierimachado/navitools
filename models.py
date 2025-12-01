from datetime import datetime

from extensions import db


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

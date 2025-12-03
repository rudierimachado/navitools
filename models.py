import json
from datetime import datetime

from flask import url_for
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


class BlogPost(db.Model):
    __tablename__ = "blog_posts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    subtitle = db.Column(db.String(255))
    slug = db.Column(db.String(255), unique=True, nullable=False)
    category = db.Column(db.String(100))
    section = db.Column(db.String(100))
    tags = db.Column(db.Text)
    cover = db.Column(db.Text)
    cta_text = db.Column(db.String(255))
    cta_link = db.Column(db.String(255))
    summary = db.Column(db.Text)
    content = db.Column(db.Text)
    priority = db.Column(db.String(20), default="normal")
    active = db.Column(db.Boolean, default=False, nullable=False)
    views = db.Column(db.Integer, default=0, nullable=False)
    reading_time = db.Column(db.String(50))
    meta_description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BlogPost {self.id} {self.slug}>"

    @property
    def tags_list(self) -> list[str]:
        try:
            return json.loads(self.tags or "[]")
        except json.JSONDecodeError:
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "slug": self.slug,
            "category": self.category,
            "section": self.section,
            "tags": self.tags_list,
            "cover": self.cover,
            "cta_text": self.cta_text,
            "cta_link": self.cta_link,
            "summary": self.summary,
            "content": self.content,
            "priority": self.priority,
            "active": self.active,
            "views": self.views,
            "reading_time": self.reading_time,
            "meta_description": self.meta_description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @property
    def cover_url(self) -> str | None:
        if not self.cover:
            return None
        if self.cover.startswith('http') or self.cover.startswith('data:'):
            return self.cover
        return url_for('static', filename=self.cover)

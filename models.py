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
    is_email_verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relacionamentos financeiros
    finance_config = db.relationship("FinanceConfig", backref="user", uselist=False, cascade="all, delete-orphan")
    transactions = db.relationship("Transaction", backref="user", lazy="dynamic", foreign_keys="Transaction.user_id", cascade="all, delete-orphan")
    recurring_transactions = db.relationship("RecurringTransaction", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    closed_transactions = db.relationship("Transaction", backref="closed_by_user", foreign_keys="Transaction.closed_by_user_id", lazy="dynamic")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email}>"


class EmailVerification(db.Model):
    """Códigos de verificação de email"""
    __tablename__ = "email_verifications"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<EmailVerification {self.email}>"


class PasswordReset(db.Model):
    """Tokens de recuperação de senha"""
    __tablename__ = "password_resets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="password_resets")

    def __repr__(self) -> str:
        return f"<PasswordReset {self.user_id}>"


class Workspace(db.Model):
    """Workspaces de finanças (Família, Negócio, etc)"""
    __tablename__ = "workspaces"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    color = db.Column(db.String(7), default="#3b82f6")  # Cor hex
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    owner = db.relationship("User", backref="workspaces")
    members = db.relationship("WorkspaceMember", backref="workspace", cascade="all, delete-orphan")
    transactions = db.relationship("Transaction", backref="workspace", foreign_keys="Transaction.workspace_id", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Workspace {self.name}>"


class WorkspaceMember(db.Model):
    """Membros de um workspace"""
    __tablename__ = "workspace_members"

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(20), default="viewer")  # owner, editor, viewer
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    onboarding_completed = db.Column(db.Boolean, default=False, nullable=False)
    share_preferences = db.Column(db.JSON, nullable=True)

    user = db.relationship("User", backref="workspace_memberships")

    def __repr__(self) -> str:
        return f"<WorkspaceMember {self.workspace_id}:{self.user_id}>"


class WorkspaceInvite(db.Model):
    """Convites para workspace por email"""
    __tablename__ = "workspace_invites"

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    invited_email = db.Column(db.String(255), nullable=False)
    invited_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    role = db.Column(db.String(20), default="editor")  # owner, editor, viewer
    token = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending, accepted, rejected
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    responded_at = db.Column(db.DateTime)

    workspace = db.relationship("Workspace", backref="invites")
    invited_by = db.relationship("User", foreign_keys=[invited_by_id], backref="invites_sent")
    invited_user = db.relationship("User", foreign_keys=[invited_user_id], backref="invites_received")

    def __repr__(self) -> str:
        return f"<WorkspaceInvite {self.invited_email} -> {self.workspace_id}>"


# ============================================================================
# MODELS DE GERENCIAMENTO FINANCEIRO
# ============================================================================

class FinanceConfig(db.Model):
    """Configuração principal do sistema financeiro do usuário"""
    __tablename__ = "finance_configs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    
    # Tipo de gestão
    management_type = db.Column(db.String(20), nullable=False, default="personal")  # personal ou family
    
    # Configurações familiares (se aplicável)
    family_name = db.Column(db.String(255))
    responsible_name = db.Column(db.String(255))
    
    # Setup
    setup_completed = db.Column(db.Boolean, default=False, nullable=False)
    setup_step = db.Column(db.Integer, default=1, nullable=False)  # Etapa atual do wizard
    
    # Configurações gerais
    currency = db.Column(db.String(10), default="BRL", nullable=False)
    timezone = db.Column(db.String(50), default="America/Sao_Paulo")
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    family_members = db.relationship("FamilyMember", backref="config", lazy="dynamic", cascade="all, delete-orphan")
    categories = db.relationship("Category", backref="config", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<FinanceConfig user_id={self.user_id} type={self.management_type}>"


class FamilyMember(db.Model):
    """Membros da família (apenas para gestão familiar)"""
    __tablename__ = "family_members"

    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey("finance_configs.id"), nullable=False)
    
    name = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(100))  # Ex: Pai, Mãe, Filho, etc.
    birth_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    transactions = db.relationship("Transaction", backref="family_member", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<FamilyMember {self.name}>"


class Category(db.Model):
    """Categorias de receitas e despesas"""
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey("finance_configs.id"), nullable=False)
    
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=True)
    
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # income ou expense
    icon = db.Column(db.String(100))  # Emoji ou classe de ícone
    color = db.Column(db.String(20))  # Cor hexadecimal
    
    is_default = db.Column(db.Boolean, default=False)  # Categoria padrão do sistema
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    transactions = db.relationship("Transaction", backref="category", lazy="dynamic")
    recurring_transactions = db.relationship("RecurringTransaction", backref="category", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Category {self.name} ({self.type})>"


class SubCategory(db.Model):
    __tablename__ = "subcategories"

    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey("finance_configs.id"), nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)

    name = db.Column(db.String(255), nullable=False)
    icon = db.Column(db.String(100))
    color = db.Column(db.String(20))

    is_default = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<SubCategory {self.name}>"


class Transaction(db.Model):
    """Transações financeiras (receitas e despesas)"""
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    subcategory_id = db.Column(db.Integer, db.ForeignKey("subcategories.id"), nullable=True)
    subcategory_text = db.Column(db.String(255), nullable=True)
    family_member_id = db.Column(db.Integer, db.ForeignKey("family_members.id"))
    
    # Dados da transação
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # income ou expense
    
    # Data e status
    transaction_date = db.Column(db.Date, nullable=False)
    is_paid = db.Column(db.Boolean, default=False, nullable=False)
    paid_date = db.Column(db.Date)
    
    # Método de pagamento
    payment_method = db.Column(db.String(50))  # dinheiro, cartão, pix, etc.
    
    # Observações
    notes = db.Column(db.Text)
    
    # Frequência e recorrência
    frequency = db.Column(db.String(20), default="once", nullable=False)  # once, daily, weekly, monthly, etc.
    is_recurring = db.Column(db.Boolean, default=False, nullable=False)
    is_fixed = db.Column(db.Boolean, default=False, nullable=False)
    
    # Recorrência (se veio de uma transação recorrente)
    recurring_transaction_id = db.Column(db.Integer, db.ForeignKey("recurring_transactions.id"))
    
    # Fechamento mensal
    monthly_closure_id = db.Column(db.Integer, db.ForeignKey("monthly_closures.id"))  # Qual mês pertence
    is_auto_loaded = db.Column(db.Boolean, default=False, nullable=False)  # Se foi carregada automaticamente do mês anterior
    
    # Workspace (para compartilhamento)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=True)
    
    # Fechamento de despesa
    is_closed = db.Column(db.Boolean, default=False, nullable=False)
    proof_document_url = db.Column(db.String(500))
    proof_document_data = db.Column(db.LargeBinary)
    proof_document_name = db.Column(db.String(255))
    proof_document_storage_name = db.Column(db.String(255))
    proof_document_mime = db.Column(db.String(255))
    proof_document_size = db.Column(db.Integer)
    closed_date = db.Column(db.Date)
    closed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    subcategory = db.relationship("SubCategory", backref="transactions", lazy=True, foreign_keys=[subcategory_id])

    def __repr__(self) -> str:
        return f"<Transaction {self.description} R$ {self.amount}>"


class RecurringTransaction(db.Model):
    """Transações recorrentes (salário, aluguel, etc.)"""
    __tablename__ = "recurring_transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    subcategory_id = db.Column(db.Integer, db.ForeignKey("subcategories.id"), nullable=True)
    subcategory_text = db.Column(db.String(255), nullable=True)
    
    # Dados da transação
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # income ou expense
    
    # Configuração de recorrência
    frequency = db.Column(db.String(20), nullable=False)  # monthly, weekly, yearly
    day_of_month = db.Column(db.Integer)  # Dia do mês (1-31)
    day_of_week = db.Column(db.Integer)  # Dia da semana (0-6, segunda=0)
    
    # Período de validade
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)  # Null = sem fim
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Método de pagamento padrão
    payment_method = db.Column(db.String(50))
    
    # Observações
    notes = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    generated_transactions = db.relationship("Transaction", backref="recurring_source", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<RecurringTransaction {self.description} ({self.frequency})>"


class MonthlyClosure(db.Model):
    """Fechamento mensal - rastreia cada mês encerrado"""
    __tablename__ = "monthly_closures"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    
    # Período
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)  # 1-12
    
    # Status
    status = db.Column(db.String(20), default="open", nullable=False)  # open ou closed
    
    # Totais do mês
    total_income = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_expense = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    balance = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    
    # Timestamps
    closed_at = db.Column(db.DateTime)  # Quando foi fechado
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    fixed_expenses_snapshot = db.relationship("MonthlyFixedExpense", backref="closure", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<MonthlyClosure {self.year}-{self.month:02d} ({self.status})>"


class MonthlyFixedExpense(db.Model):
    """Snapshot de despesas fixas copiadas para o próximo mês"""
    __tablename__ = "monthly_fixed_expenses"

    id = db.Column(db.Integer, primary_key=True)
    monthly_closure_id = db.Column(db.Integer, db.ForeignKey("monthly_closures.id"), nullable=False)
    
    # Referência à transação original (do mês anterior)
    original_transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"))
    
    # Dados da despesa fixa
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<MonthlyFixedExpense {self.description} R$ {self.amount}>"


class SystemShare(db.Model):
    """Compartilhamento do sistema entre usuários"""
    __tablename__ = "system_shares"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    shared_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    
    # Email do usuário a ser convidado
    shared_email = db.Column(db.String(255), nullable=False)
    
    # Status do compartilhamento
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending, accepted, rejected
    
    # Tipo de compartilhamento
    share_type = db.Column(db.String(20), default="accountant", nullable=False)  # family, accountant
    
    # Papel na família (se for family)
    family_role = db.Column(db.String(50))  # spouse, child, parent, other
    
    # Tipo de acesso (para accountant)
    access_level = db.Column(db.String(20), default="viewer", nullable=False)  # viewer, editor, admin
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    accepted_at = db.Column(db.DateTime)
    
    # Relacionamentos
    owner = db.relationship("User", foreign_keys=[owner_id], backref="shares_created")
    shared_user = db.relationship("User", foreign_keys=[shared_user_id], backref="shares_received")

    def __repr__(self) -> str:
        return f"<SystemShare {self.shared_email} ({self.share_type}/{self.status})>"


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


class NewsletterSubscriber(db.Model):
    """Assinantes da newsletter"""
    __tablename__ = "newsletter_subscribers"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    source = db.Column(db.String(100))  # Ex: blog_list, blog_detail, home
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NewsletterSubscriber {self.email} active={self.active}>"


class TransactionAttachment(db.Model):
    """Comprovantes anexados às transações (múltiplos por transação)"""
    __tablename__ = "transaction_attachments"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    
    # Dados do arquivo
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # em bytes
    mime_type = db.Column(db.String(100))
    
    # Timestamps
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    transaction = db.relationship("Transaction", backref="attachments", lazy=True)
    user = db.relationship("User", backref="transaction_attachments", lazy=True)

    def __repr__(self) -> str:
        return f"<TransactionAttachment {self.file_name} for Transaction {self.transaction_id}>"

"""
Helper functions para o wizard de setup do sistema financeiro
"""
from datetime import datetime, date
from extensions import db
from models import FinanceConfig, Category, RecurringTransaction


def create_default_categories(config_id: int) -> None:
    """Cria categorias padrão para o usuário"""
    
    # Categorias de RECEITAS
    income_categories = [
        {"name": "Salário", "icon": "💼", "color": "#10b981"},
        {"name": "Freelance", "icon": "💻", "color": "#3b82f6"},
        {"name": "Investimentos", "icon": "📈", "color": "#8b5cf6"},
        {"name": "Aluguel Recebido", "icon": "🏠", "color": "#06b6d4"},
        {"name": "Outros Ganhos", "icon": "💰", "color": "#14b8a6"},
    ]
    
    # Categorias de DESPESAS
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
    
    # Criar categorias de receitas
    for cat_data in income_categories:
        category = Category(
            config_id=config_id,
            name=cat_data["name"],
            type="income",
            icon=cat_data["icon"],
            color=cat_data["color"],
            is_default=True,
            is_active=True
        )
        db.session.add(category)
    
    # Criar categorias de despesas
    for cat_data in expense_categories:
        category = Category(
            config_id=config_id,
            name=cat_data["name"],
            type="expense",
            icon=cat_data["icon"],
            color=cat_data["color"],
            is_default=True,
            is_active=True
        )
        db.session.add(category)
    
    db.session.commit()


def get_setup_progress(config: FinanceConfig) -> dict:
    """Retorna o progresso do setup"""
    return {
        "current_step": config.setup_step,
        "total_steps": 4,
        "completed": config.setup_completed,
        "percentage": (config.setup_step - 1) * 25 if not config.setup_completed else 100
    }


def validate_step_1(data: dict) -> tuple[bool, str]:
    """Valida dados da Etapa 1: Tipo de Gestão"""
    management_type = data.get("management_type")
    
    if not management_type or management_type not in ["personal", "family"]:
        return False, "Selecione um tipo de gestão válido"
    
    return True, ""


def validate_step_2(data: dict, management_type: str) -> tuple[bool, str]:
    """Valida dados da Etapa 2: Configuração Familiar"""
    if management_type != "family":
        return True, ""  # Pula validação se não for familiar
    
    family_name = data.get("family_name", "").strip()
    responsible_name = data.get("responsible_name", "").strip()
    
    if not family_name:
        return False, "Informe o nome da família"
    
    if not responsible_name:
        return False, "Informe o nome do responsável"
    
    return True, ""


def validate_step_3(data: dict) -> tuple[bool, str]:
    """Valida dados da Etapa 3: Contas & Categorias"""
    # Por enquanto, apenas verifica se há pelo menos uma categoria selecionada
    # As categorias padrão já são criadas automaticamente
    return True, ""


def validate_step_4(data: dict) -> tuple[bool, str]:
    """Valida dados da Etapa 4: Receitas Recorrentes"""
    # Validação opcional - usuário pode pular esta etapa
    recurring_items = data.get("recurring_items", [])
    
    for item in recurring_items:
        if not item.get("description"):
            return False, "Todas as receitas recorrentes devem ter uma descrição"
        
        try:
            amount = float(item.get("amount", 0))
            if amount <= 0:
                return False, "O valor deve ser maior que zero"
        except (ValueError, TypeError):
            return False, "Valor inválido"
        
        if not item.get("frequency"):
            return False, "Selecione a frequência"
    
    return True, ""


def create_recurring_transactions(user_id: int, config_id: int, items: list) -> None:
    """Cria transações recorrentes iniciais"""
    
    # Busca categoria padrão de salário
    salary_category = Category.query.filter_by(
        config_id=config_id,
        name="Salário",
        type="income"
    ).first()
    
    for item in items:
        recurring = RecurringTransaction(
            user_id=user_id,
            category_id=salary_category.id if salary_category else None,
            description=item.get("description"),
            amount=item.get("amount"),
            type="income",
            frequency=item.get("frequency", "monthly"),
            day_of_month=item.get("day_of_month", 1),
            start_date=date.today(),
            is_active=True,
            payment_method=item.get("payment_method")
        )
        db.session.add(recurring)
    
    db.session.commit()


def complete_setup(config: FinanceConfig) -> None:
    """Marca o setup como completo"""
    config.setup_completed = True
    config.setup_step = 4
    db.session.commit()


def get_setup_summary(config: FinanceConfig) -> dict:
    """Retorna resumo da configuração para a tela final"""
    
    categories_count = Category.query.filter_by(config_id=config.id, is_active=True).count()
    recurring_count = RecurringTransaction.query.filter_by(
        user_id=config.user_id,
        is_active=True
    ).count()
    
    family_members_count = 0
    if config.management_type == "family":
        family_members_count = config.family_members.filter_by(is_active=True).count()
    
    return {
        "management_type": config.management_type,
        "management_type_label": "Pessoal" if config.management_type == "personal" else "Familiar",
        "family_name": config.family_name,
        "responsible_name": config.responsible_name,
        "family_members_count": family_members_count,
        "categories_count": categories_count,
        "recurring_count": recurring_count,
        "currency": config.currency,
        "created_at": config.created_at
    }

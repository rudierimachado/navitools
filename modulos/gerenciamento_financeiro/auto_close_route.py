"""
Rota para verificação automática de virada de mês
"""
from flask import jsonify, session
from datetime import datetime, date, timedelta
from sqlalchemy import func
from extensions import db
from models import MonthlyClosure, Transaction, MonthlyFixedExpense

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
                    import calendar
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
        return jsonify({"error": str(e)}), 500

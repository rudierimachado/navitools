"""
Script para adicionar índices na tabela transactions para melhorar performance do dashboard.
Execute uma vez: python add_transaction_indexes.py
"""

from extensions import db
from run import app

def add_indexes():
    """Adiciona índices compostos para otimizar queries do dashboard"""
    
    with app.app_context():
        try:
            # Índice composto para queries de dashboard (user_id + transaction_date + type + is_paid)
            db.session.execute("""
                CREATE INDEX IF NOT EXISTS idx_transactions_dashboard 
                ON transactions(user_id, transaction_date, type, is_paid);
            """)
            
            # Índice para queries de categorias
            db.session.execute("""
                CREATE INDEX IF NOT EXISTS idx_transactions_category 
                ON transactions(user_id, category_id, transaction_date, is_paid);
            """)
            
            # Índice para queries de transações recorrentes
            db.session.execute("""
                CREATE INDEX IF NOT EXISTS idx_transactions_recurring 
                ON transactions(user_id, recurring_transaction_id, transaction_date);
            """)
            
            db.session.commit()
            print("✓ Índices criados com sucesso!")
            print("  - idx_transactions_dashboard")
            print("  - idx_transactions_category")
            print("  - idx_transactions_recurring")
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Erro ao criar índices: {e}")

if __name__ == "__main__":
    add_indexes()

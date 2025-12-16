# Endpoint para limpar workspace - adicionar ao routes.py

@gerenciamento_financeiro_bp.route("/api/workspace/clear", methods=["POST"])
def api_clear_workspace():
    """Limpa todas as transações do workspace atual"""
    if "finance_user_id" not in session:
        return jsonify({"error": "Não autorizado"}), 401
    
    if "active_workspace_id" not in session:
        return jsonify({"error": "Nenhum workspace ativo"}), 400
    
    user_id = session["finance_user_id"]
    workspace_id = session["active_workspace_id"]
    
    try:
        # Verificar se o usuário tem permissão (owner ou editor)
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            return jsonify({"error": "Workspace não encontrado"}), 404
        
        # Verificar se é owner
        is_owner = workspace.owner_id == user_id
        
        # Verificar se é membro com permissão de edição
        is_editor = False
        if not is_owner:
            member = WorkspaceMember.query.filter_by(
                workspace_id=workspace_id,
                user_id=user_id
            ).first()
            is_editor = member and member.role in ['editor', 'owner']
        
        if not (is_owner or is_editor):
            return jsonify({"error": "Sem permissão para limpar este workspace"}), 403
        
        # Deletar todas as transações do workspace
        deleted_count = Transaction.query.filter_by(workspace_id=workspace_id).delete()
        
        # Deletar transações recorrentes
        RecurringTransaction.query.filter_by(workspace_id=workspace_id).delete()
        
        # Deletar despesas fixas mensais
        MonthlyFixedExpense.query.filter_by(workspace_id=workspace_id).delete()
        
        # Deletar fechamentos mensais
        MonthlyClosure.query.filter_by(workspace_id=workspace_id).delete()
        
        db.session.commit()
        
        return jsonify({
            "message": "Workspace limpo com sucesso",
            "transactions_deleted": deleted_count
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

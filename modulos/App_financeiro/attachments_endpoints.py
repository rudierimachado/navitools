"""
Endpoints para gerenciar comprovantes de transações
"""
import os
from flask import request, jsonify, send_file
from werkzeug.utils import secure_filename
from datetime import datetime

from extensions import db
from models import Transaction, TransactionAttachment


UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'uploads', 'attachments')
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB em bytes
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _cors_wrap(resp, origin: str):
    try:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    except Exception:
        pass
    return resp


def upload_attachment(api_bp):
    """POST /api/transactions/<id>/attachments - Upload de comprovante"""
    @api_bp.route("/api/transactions/<int:tx_id>/attachments", methods=["POST", "OPTIONS"])
    def api_upload_attachment(tx_id):
        origin = request.headers.get("Origin", "*")
        
        if request.method == "OPTIONS":
            resp = jsonify({"ok": True})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp, 200
        
        try:
            user_id = request.args.get("user_id") or request.form.get("user_id")
            if not user_id:
                return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400
            
            user_id_int = int(user_id)
            
            # Verificar se a transação existe e pertence ao usuário
            tx = Transaction.query.filter_by(id=tx_id, user_id=user_id_int).first()
            if not tx:
                return _cors_wrap(jsonify({"success": False, "message": "Transação não encontrada"}), origin), 404
            
            # Verificar se a transação está marcada como paga
            if not tx.is_paid:
                return _cors_wrap(jsonify({"success": False, "message": "Apenas transações pagas podem ter comprovantes"}), origin), 400
            
            # Verificar se há arquivo no request
            if 'file' not in request.files:
                return _cors_wrap(jsonify({"success": False, "message": "Nenhum arquivo enviado"}), origin), 400
            
            file = request.files['file']
            if file.filename == '':
                return _cors_wrap(jsonify({"success": False, "message": "Nome de arquivo vazio"}), origin), 400
            
            # Validar extensão
            if not allowed_file(file.filename):
                return _cors_wrap(jsonify({"success": False, "message": f"Tipo de arquivo não permitido. Use: {', '.join(ALLOWED_EXTENSIONS)}"}), origin), 400
            
            # Ler arquivo para validar tamanho
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            
            if file_size > MAX_FILE_SIZE:
                return _cors_wrap(jsonify({"success": False, "message": "Arquivo maior que 1MB"}), origin), 400
            
            # Criar diretório se não existir
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            
            # Gerar nome único para o arquivo
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_filename = f"{user_id_int}_{tx_id}_{timestamp}_{filename}"
            file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            
            # Salvar arquivo
            file.save(file_path)
            
            # Criar registro no banco
            attachment = TransactionAttachment(
                transaction_id=tx_id,
                user_id=user_id_int,
                file_name=filename,
                file_path=file_path,
                file_size=file_size,
                mime_type=file.content_type
            )
            db.session.add(attachment)
            db.session.commit()
            
            return _cors_wrap(jsonify({
                "success": True,
                "attachment": {
                    "id": attachment.id,
                    "file_name": attachment.file_name,
                    "file_size": attachment.file_size,
                    "uploaded_at": attachment.uploaded_at.isoformat()
                }
            }), origin), 201
            
        except Exception as e:
            db.session.rollback()
            return _cors_wrap(jsonify({"success": False, "message": f"Erro ao fazer upload: {str(e)}"}), origin), 500


def list_attachments(api_bp):
    """GET /api/transactions/<id>/attachments - Listar comprovantes"""
    @api_bp.route("/api/transactions/<int:tx_id>/attachments", methods=["GET", "OPTIONS"])
    def api_list_attachments(tx_id):
        origin = request.headers.get("Origin", "*")
        
        if request.method == "OPTIONS":
            resp = jsonify({"ok": True})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp, 200
        
        try:
            user_id = request.args.get("user_id")
            if not user_id:
                return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400
            
            user_id_int = int(user_id)
            
            # Verificar se a transação existe e pertence ao usuário
            tx = Transaction.query.filter_by(id=tx_id, user_id=user_id_int).first()
            if not tx:
                return _cors_wrap(jsonify({"success": False, "message": "Transação não encontrada"}), origin), 404
            
            # Buscar comprovantes
            attachments = TransactionAttachment.query.filter_by(transaction_id=tx_id).order_by(TransactionAttachment.uploaded_at.desc()).all()
            
            attachments_list = []
            for att in attachments:
                attachments_list.append({
                    "id": att.id,
                    "file_name": att.file_name,
                    "file_size": att.file_size,
                    "mime_type": att.mime_type,
                    "uploaded_at": att.uploaded_at.isoformat(),
                    "view_url": f"/gerenciamento-financeiro/api/transactions/{tx_id}/attachments/{att.id}/file?user_id={user_id_int}",
                })
            
            return _cors_wrap(jsonify({
                "success": True,
                "attachments": attachments_list,
                "count": len(attachments_list)
            }), origin), 200
            
        except Exception as e:
            return _cors_wrap(jsonify({"success": False, "message": f"Erro ao listar comprovantes: {str(e)}"}), origin), 500


def delete_attachment(api_bp):
    """DELETE /api/transactions/<id>/attachments/<attachment_id> - Remover comprovante"""
    @api_bp.route("/api/transactions/<int:tx_id>/attachments/<int:attachment_id>", methods=["DELETE", "OPTIONS"])
    def api_delete_attachment(tx_id, attachment_id):
        origin = request.headers.get("Origin", "*")
        
        if request.method == "OPTIONS":
            resp = jsonify({"ok": True})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = "DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp, 200
        
        try:
            user_id = request.args.get("user_id")
            if not user_id:
                return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400
            
            user_id_int = int(user_id)
            
            # Verificar se a transação existe e pertence ao usuário
            tx = Transaction.query.filter_by(id=tx_id, user_id=user_id_int).first()
            if not tx:
                return _cors_wrap(jsonify({"success": False, "message": "Transação não encontrada"}), origin), 404
            
            # Buscar comprovante
            attachment = TransactionAttachment.query.filter_by(id=attachment_id, transaction_id=tx_id).first()
            if not attachment:
                return _cors_wrap(jsonify({"success": False, "message": "Comprovante não encontrado"}), origin), 404
            
            # Remover arquivo físico
            try:
                if os.path.exists(attachment.file_path):
                    os.remove(attachment.file_path)
            except Exception as e:
                print(f"[ATTACHMENT] Erro ao remover arquivo: {e}")
            
            # Remover registro do banco
            db.session.delete(attachment)
            db.session.commit()
            
            return _cors_wrap(jsonify({
                "success": True,
                "message": "Comprovante removido com sucesso"
            }), origin), 200
            
        except Exception as e:
            db.session.rollback()
            return _cors_wrap(jsonify({"success": False, "message": f"Erro ao remover comprovante: {str(e)}"}), origin), 500


def view_attachment(api_bp):
    """GET /api/transactions/<id>/attachments/<attachment_id>/file - Visualizar/baixar comprovante"""
    @api_bp.route(
        "/api/transactions/<int:tx_id>/attachments/<int:attachment_id>/file",
        methods=["GET", "OPTIONS"],
    )
    def api_view_attachment(tx_id, attachment_id):
        origin = request.headers.get("Origin", "*")

        if request.method == "OPTIONS":
            resp = jsonify({"ok": True})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp, 200

        try:
            user_id = request.args.get("user_id")
            if not user_id:
                return _cors_wrap(jsonify({"success": False, "message": "user_id obrigatório"}), origin), 400

            user_id_int = int(user_id)

            tx = Transaction.query.filter_by(id=tx_id, user_id=user_id_int).first()
            if not tx:
                return _cors_wrap(jsonify({"success": False, "message": "Transação não encontrada"}), origin), 404

            attachment = TransactionAttachment.query.filter_by(
                id=attachment_id,
                transaction_id=tx_id,
                user_id=user_id_int,
            ).first()
            if not attachment:
                return _cors_wrap(jsonify({"success": False, "message": "Comprovante não encontrado"}), origin), 404

            if not attachment.file_path or not os.path.exists(attachment.file_path):
                return _cors_wrap(jsonify({"success": False, "message": "Arquivo não encontrado no servidor"}), origin), 404

            resp = send_file(
                attachment.file_path,
                mimetype=attachment.mime_type or "application/octet-stream",
                as_attachment=False,
                download_name=attachment.file_name,
            )
            return _cors_wrap(resp, origin)

        except Exception as e:
            return _cors_wrap(jsonify({"success": False, "message": f"Erro ao abrir comprovante: {str(e)}"}), origin), 500


def register_attachment_routes(api_bp):
    """Registra todas as rotas de comprovantes"""
    upload_attachment(api_bp)
    list_attachments(api_bp)
    delete_attachment(api_bp)
    view_attachment(api_bp)

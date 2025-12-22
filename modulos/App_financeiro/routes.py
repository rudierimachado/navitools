"""
Rotas Web (HTML) - Gerenciamento Financeiro
============================================

Interface web para gestão financeira via navegador.
"""

import os
from datetime import datetime
from flask import (
    Blueprint,
    render_template,
    send_file,
    abort,
    request,
    flash,
    redirect,
    url_for,
    session,
    jsonify,
)

from extensions import db
from models import WorkspaceInvite, Workspace, WorkspaceMember, User

# Blueprint das rotas web
gerenciamento_financeiro_bp = Blueprint(
    "gerenciamento_financeiro",
    __name__,
)


@gerenciamento_financeiro_bp.route("/")
def home():
    """Página inicial do módulo financeiro"""
    return "Gerenciamento Financeiro - Em desenvolvimento"


@gerenciamento_financeiro_bp.route("/apresentacao")
def apresentacao():
    """Página de apresentação do app financeiro com download do APK"""
    return render_template("finance_apresentacao.html")


@gerenciamento_financeiro_bp.route("/download/apk")
def download_apk():
    """Download do APK do aplicativo financeiro"""
    module_dir = os.path.dirname(__file__)

    # Opcional: escolher ABI via querystring (?abi=arm64-v8a|armeabi-v7a|x86_64)
    abi = (request.args.get("abi") or "").strip().lower()

    preferred_names = [
        "app-release.apk",
        "app-arm64-v8a-release.apk",
        "app-armeabi-v7a-release.apk",
        "app-x86_64-release.apk",
    ]

    if abi:
        # Normaliza para o formato do nome do arquivo
        if abi in ("arm64", "arm64-v8a", "arm64_v8a"):
            preferred_names = ["app-arm64-v8a-release.apk"] + [n for n in preferred_names if n != "app-arm64-v8a-release.apk"]
        elif abi in ("armeabi", "armeabi-v7a", "armeabi_v7a"):
            preferred_names = ["app-armeabi-v7a-release.apk"] + [n for n in preferred_names if n != "app-armeabi-v7a-release.apk"]
        elif abi in ("x86_64", "x86-64"):
            preferred_names = ["app-x86_64-release.apk"] + [n for n in preferred_names if n != "app-x86_64-release.apk"]

    apk_path = None
    for name in preferred_names:
        candidate = os.path.join(module_dir, name)
        if os.path.exists(candidate):
            apk_path = candidate
            break

    # Fallback: APK em static/downloads (caso você prefira manter em static)
    if apk_path is None:
        static_apk_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "static",
            "downloads",
            "finance-app.apk",
        )
        apk_path = static_apk_path
    
    if not os.path.exists(apk_path):
        abort(404, description="APK não encontrado no servidor.")
    
    filename = os.path.basename(apk_path)
    resp = send_file(
        apk_path,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.android.package-archive"
    )

    # Evitar cache (para não baixar APK antigo)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@gerenciamento_financeiro_bp.route("/invite/accept/<token>")
def accept_workspace_invite(token):
    """Processa o link de convite enviado por email"""
    # 1. DETECTAR DISPOSITIVO
    user_agent = request.headers.get('User-Agent', '').lower()
    is_mobile = ('mobile' in user_agent or 
                'android' in user_agent or 
                'iphone' in user_agent or 
                'ipad' in user_agent or
                'windows phone' in user_agent or
                'blackberry' in user_agent)
    print(f"[INVITE] User-Agent: {request.headers.get('User-Agent', '')}")
    print(f"[INVITE] Is Mobile: {is_mobile}")
    
    invite = WorkspaceInvite.query.filter_by(token=token).first()

    if not invite:
        if is_mobile:
            deep_link = f"nexusfinance://invite/error?message=convite_invalido"
            return render_template("finance_invite_status.html", 
                                 title="Convite Inválido",
                                 message="Este convite é inválido ou não existe.",
                                 is_error=True,
                                 deep_link=deep_link,
                                 show_app_button=True)
        else:
            flash("Convite inválido ou inexistente.", "danger")
            return render_template("finance_invite_status.html", status="error", message="Convite inválido.")

    if invite.status != "pending":
        if is_mobile:
            deep_link = f"nexusfinance://invite/error?message=convite_utilizado"
            return render_template("finance_invite_status.html",
                                 title="Convite Já Utilizado", 
                                 message="Este convite já foi utilizado ou cancelado.",
                                 is_error=True,
                                 deep_link=deep_link,
                                 show_app_button=True)
        else:
            flash("Este convite já foi utilizado ou cancelado.", "danger")
            return render_template("finance_invite_status.html", status="error", message="Convite já utilizado.")

    if invite.expires_at and invite.expires_at < datetime.utcnow():
        invite.status = "expired"
        invite.responded_at = datetime.utcnow()
        db.session.commit()
        if is_mobile:
            deep_link = f"nexusfinance://invite/error?message=convite_expirado"
            return render_template("finance_invite_status.html",
                                 title="Convite Expirado",
                                 message="Este convite expirou.",
                                 is_error=True,
                                 deep_link=deep_link,
                                 show_app_button=True)
        else:
            flash("Este convite expirou.", "danger")
            return render_template("finance_invite_status.html", status="error", message="Convite expirado.")

    workspace = Workspace.query.get(invite.workspace_id)
    if not workspace:
        invite.status = "cancelled"
        invite.responded_at = datetime.utcnow()
        db.session.commit()
        if is_mobile:
            deep_link = f"nexusfinance://invite/error?message=workspace_inexistente"
            return render_template("finance_invite_status.html",
                                 title="Workspace Inexistente",
                                 message="O workspace deste convite não existe mais.",
                                 is_error=True,
                                 deep_link=deep_link,
                                 show_app_button=True)
        else:
            flash("O workspace deste convite não existe mais.", "danger")
            return render_template("finance_invite_status.html", status="error", message="Workspace inexistente.")

    # Verificar se usuário existe
    user = None
    if invite.invited_email:
        user = User.query.filter_by(email=invite.invited_email).first()
    
    print(f"[INVITE] User exists: {user is not None}")

    # 3. LÓGICA DE REDIRECIONAMENTO
    print(f"[INVITE] Starting redirect logic - is_mobile: {is_mobile}")
    if is_mobile:
        print(f"[INVITE] Mobile path taken")
        if not user:
            # Usuário não existe - precisa criar conta no app
            deep_link = f"nexusfinance://invite/register?email={invite.invited_email}&token={token}&workspace_name={workspace.name}"
            print(f"[INVITE] New user - deep_link: {deep_link}")
            return render_template("finance_invite_status.html", 
                                 title="Convite Recebido!",
                                 message="Você foi convidado! Toque no botão abaixo para abrir o app e criar sua conta.",
                                 is_error=False,
                                 deep_link=deep_link,
                                 show_app_button=True,
                                 workspace_name=workspace.name,
                                 invite_email=invite.invited_email)
            existing_member = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=user.id).first()
            if existing_member or workspace.owner_id == user.id:
                # Já é membro - apenas informar
                deep_link = f"nexusfinance://workspace?workspace_id={workspace.id}"
                print(f"[INVITE] Already member - deep_link: {deep_link}")
                return render_template("finance_invite_status.html",
                                     title="Você Já é Membro!",
                                     message="Você já faz parte deste workspace! Toque para abrir o app.",
                                     is_error=False,
                                     deep_link=deep_link,
                                     show_app_button=True,
                                     workspace_name=workspace.name)
            else:
                # Usuário existe - adicionar como membro E redirecionar
                print(f"[INVITE] Adding existing user as member")
                member = WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=invite.role or "viewer",
                )
                db.session.add(member)
                invite.status = "accepted"
                invite.responded_at = datetime.utcnow()
                
                # CRÍTICO: Definir o workspace como ativo na sessão
                session[f"active_workspace_{user.id}"] = workspace.id
                print(f"[INVITE] Definindo workspace ativo na sessão: user_id={user.id}, workspace_id={workspace.id}")
                
                db.session.commit()
                
                deep_link = (
                    f"nexusfinance://workspace/onboarding"
                    f"?workspace_id={workspace.id}"
                    f"&role={member.role}"
                    f"&workspace_name={workspace.name}"
                    f"&user_id={user.id}"
                )
                print(f"[INVITE] User added as member - onboarding deep_link: {deep_link}")
                return render_template("finance_invite_status.html",
                                     title="Convite Aceito!", 
                                     message="Convite aceito com sucesso! Toque no botão para configurar o compartilhamento no app.",
                                     is_error=False,
                                     deep_link=deep_link,
                                     show_app_button=True,
                                     workspace_name=workspace.name)
    else:
        print(f"[INVITE] Desktop path taken")
        # Desktop - manter URLs web atuais
        if not user:
            flash("Crie sua conta para entrar no workspace.", "info")
            register_url = f"/gerenciamento-financeiro/register?email={invite.invited_email}&invite_token={token}"
            print(f"[INVITE] Desktop new user - redirecting to: {register_url}")
            return redirect(register_url)
        else:
            # Verificar se já é membro
            existing_member = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=user.id).first()
            if existing_member or workspace.owner_id == user.id:
                flash("Você já faz parte deste workspace!", "info")
                session["finance_user_id"] = user.id
                print(f"[INVITE] Desktop already member - redirecting to /app")
                return redirect("/gerenciamento-financeiro/app")
            else:
                # Adicionar usuário existente como membro
                print(f"[INVITE] Desktop adding user as member")
                member = WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=invite.role or "viewer",
                )
                db.session.add(member)
                invite.status = "accepted"
                invite.responded_at = datetime.utcnow()
                db.session.commit()
                
                session["finance_user_id"] = user.id
                onboarding_url = url_for("gerenciamento_financeiro.workspace_onboarding", workspace_id=workspace.id)
                flash("Bem-vindo! Complete as preferências de compartilhamento.", "success")
                print(f"[INVITE] Desktop user added - redirecting to onboarding {onboarding_url}")
                return redirect(onboarding_url)


@gerenciamento_financeiro_bp.route("/workspace/<int:workspace_id>/onboarding", methods=["GET", "POST"])
def workspace_onboarding(workspace_id):
    """Tela web simples para concluir onboarding do workspace."""
    workspace = Workspace.query.get(workspace_id)
    if not workspace:
        flash("Workspace não encontrado.", "danger")
        return redirect("/gerenciamento-financeiro/")

    user_id = session.get("finance_user_id")
    member = WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=user_id).first() if user_id else None

    if not user_id or (workspace.owner_id != user_id and not member):
        flash("Faça login para continuar o onboarding.", "danger")
        return redirect("/gerenciamento-financeiro/login" if hasattr(gerenciamento_financeiro_bp, "login") else "/")

    if member and member.onboarding_completed:
        flash("Onboarding já concluído.", "success")
        return redirect("/gerenciamento-financeiro/app")

    if request.method == "POST":
        share_transactions = bool(request.form.get("share_transactions"))
        share_categories = bool(request.form.get("share_categories"))
        share_files = bool(request.form.get("share_files"))

        prefs = {
            "share_transactions": share_transactions,
            "share_categories": share_categories,
            "share_files": share_files,
        }

        if member:
            member.onboarding_completed = True
            member.share_preferences = prefs
        db.session.commit()
        flash("Onboarding concluído com sucesso!", "success")
        session[f"active_workspace_{user_id}"] = workspace_id
        return redirect("/gerenciamento-financeiro/app")

    return render_template(
        "finance_onboarding.html",
        workspace=workspace,
        member=member,
    )

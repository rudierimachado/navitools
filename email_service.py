#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Serviço de envio de emails para o NEXUSRDR"""

from flask import Flask, render_template_string
from flask_mail import Mail, Message
import os
from dotenv import load_dotenv
from threading import Thread
import logging
import traceback
import requests
from email.utils import parseaddr

load_dotenv()

mail = Mail()
logger = logging.getLogger(__name__)


def _env_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    v = str(value).strip().lower()
    return v in ("1", "true", "t", "yes", "y", "on")

def init_mail(app: Flask):
    """Inicializa o serviço de email com Brevo"""
    # Configuração padrão para Brevo
    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp-relay.brevo.com')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = _env_bool(os.getenv('MAIL_USE_TLS', 'true'), default=True)
    app.config['MAIL_USE_SSL'] = _env_bool(os.getenv('MAIL_USE_SSL', 'false'), default=False)
    # Estrito: usar SOMENTE MAIL_DEFAULT_SENDER e MAIL_DEFAULT_SENDER_SENHA
    # - MAIL_DEFAULT_SENDER: email remetente (e também login SMTP)
    # - MAIL_DEFAULT_SENDER_SENHA: senha/chave SMTP
    raw_sender = os.getenv('MAIL_DEFAULT_SENDER')
    if raw_sender:
        _, parsed_email = parseaddr(raw_sender)
        app.config['MAIL_DEFAULT_SENDER'] = parsed_email or raw_sender
    else:
        app.config['MAIL_DEFAULT_SENDER'] = None
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME') or os.getenv('MAIL_DEFAULT_SENDER')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD') or os.getenv('MAIL_DEFAULT_SENDER_SENHA')
    
    # Timeout aumentado para evitar problemas de conexão
    app.config['MAIL_TIMEOUT'] = int(os.getenv('MAIL_TIMEOUT', 120))
    
    # Base da URL da aplicação para montar links de convite
    # Ex.: APP_BASE_URL=http://localhost:5000 ou https://nexusrdr.com
    app.config['APP_BASE_URL'] = os.getenv('APP_BASE_URL', '').rstrip('/')

    app.config['BREVO_API_KEY'] = os.getenv('BREVO_API_KEY')
    app.config['BREVO_SENDER_NAME'] = os.getenv('BREVO_SENDER_NAME')
    app.config['BREVO_SENDER_EMAIL'] = os.getenv('BREVO_SENDER_EMAIL')

    mail.init_app(app)


def _send_brevo_email(app: Flask, subject: str, recipients: list[str], html: str):
    api_key = app.config.get('BREVO_API_KEY')
    if not api_key:
        print("❌ [BREVO] API Key ausente. Defina BREVO_API_KEY no .env")
        return False

    sender_email = app.config.get('BREVO_SENDER_EMAIL') or app.config.get('MAIL_DEFAULT_SENDER')
    sender_name = app.config.get('BREVO_SENDER_NAME')
    if not sender_email:
        print("❌ [BREVO] Remetente ausente. Defina BREVO_SENDER_EMAIL (ou MAIL_DEFAULT_SENDER).")
        return False
    
    print(f"[BREVO] Tentando enviar email para {recipients} com remetente {sender_email}")

    payload = {
        "sender": {"email": sender_email},
        "to": [{"email": r} for r in recipients],
        "subject": subject,
        "htmlContent": html,
    }
    if sender_name:
        payload["sender"]["name"] = sender_name

    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
    }

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers=headers,
            json=payload,
            timeout=int(app.config.get('MAIL_TIMEOUT', 120)),
        )
        if 200 <= resp.status_code < 300:
            print(f"✅ [BREVO] Email enviado para {recipients}")
            return True

        print(f"❌ [BREVO] Falha ao enviar email (status={resp.status_code}): {resp.text}")
        return False
    except Exception as e:
        print(f"❌ [BREVO] Erro ao enviar email: {e}")
        print(traceback.format_exc())
        return False


def _brevo_enabled(app: Flask) -> bool:
    return bool(app.config.get('BREVO_API_KEY'))

def _send_async_email(app: Flask, msg: Message):
    """Envia email em thread separada (não bloqueia a requisição)"""
    try:
        with app.app_context():
            mail.send(msg)
            logger.info(f"✅ Email enviado para {msg.recipients}")
            print(f"✅ Email enviado para {msg.recipients}")
    except Exception as e:
        logger.error(f"❌ Erro ao enviar email: {str(e)}")
        print(f"❌ Erro ao enviar email: {str(e)}")
        print(traceback.format_exc())

def _send_email_background(app: Flask, msg: Message):
    """Envia email em background thread"""
    thread = Thread(target=_send_async_email, args=(app, msg))
    thread.daemon = True
    thread.start()

def send_share_invitation(recipient_email: str, owner_email: str, access_level: str, share_id: int, app: Flask):
    """
    Envia email de convite de compartilhamento
    
    Args:
        recipient_email: Email do destinatário
        owner_email: Email de quem está compartilhando
        access_level: Nível de acesso (viewer, editor, admin)
        share_id: ID do compartilhamento
        app: Aplicação Flask
    """
    try:
        with app.app_context():
            # Traduzir nível de acesso
            access_levels = {
                'viewer': 'Visualizador (apenas leitura)',
                'editor': 'Editor (pode editar)',
                'admin': 'Administrador (controle total)'
            }
            access_label = access_levels.get(access_level, access_level)

            # URL de aceitação baseada na configuração APP_BASE_URL
            # Vamos direcionar para a tela de login financeiro com o ID do compartilhamento
            # Ex.: http://localhost:5000/gerenciamento-financeiro/login?accept_share_id=6
            from flask import url_for

            base_url = app.config.get('APP_BASE_URL', '').rstrip('/')
            login_path = url_for('gerenciamento_financeiro.login')  # ex.: /gerenciamento-financeiro/login

            if base_url:
                accept_url = f"{base_url}{login_path}?accept_share_id={share_id}"
            else:
                # fallback: caminho relativo (caso APP_BASE_URL não esteja configurado)
                accept_url = f"{login_path}?accept_share_id={share_id}"
            
            # Template do email
            email_template = """
            <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: linear-gradient(135deg, #3b82f6, #1e40af); color: white; padding: 20px; border-radius: 8px; }
                        .content { background: #f8fafc; padding: 20px; border-radius: 8px; margin: 20px 0; }
                        .button { display: inline-block; background: #3b82f6; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; margin: 10px 0; }
                        .footer { text-align: center; color: #999; font-size: 12px; margin-top: 20px; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>🎉 Você foi convidado!</h1>
                        </div>
                        
                        <div class="content">
                            <p>Olá,</p>
                            
                            <p><strong>{{ owner_email }}</strong> está compartilhando o sistema de gestão financeira NEXUSRDR com você!</p>
                            
                            <p><strong>Nível de acesso:</strong> {{ access_label }}</p>
                            
                            <p>Com este acesso você poderá:</p>
                            <ul>
                                <li>✅ Visualizar todas as transações e relatórios</li>
                                <li>✅ Acompanhar o saldo e movimentações</li>
                                <li>✅ Gerenciar despesas e receitas</li>
                            </ul>
                            
                            <p>Clique no botão abaixo para aceitar o convite:</p>
                            <a href="{{ accept_url }}" class="button">Aceitar Convite</a>
                            
                            <p>Ou copie e cole este link no seu navegador:</p>
                            <p><small>{{ accept_url }}</small></p>
                        </div>
                        
                        <div class="footer">
                            <p>Este é um email automático. Por favor, não responda.</p>
                            <p>NEXUSRDR - Sistema de Gestão Financeira</p>
                        </div>
                    </div>
                </body>
            </html>
            """
            
            # Renderizar template
            html_body = render_template_string(
                email_template,
                owner_email=owner_email,
                access_label=access_label,
                accept_url=accept_url
            )
            
            subject = 'Convite de Compartilhamento - NEXUSRDR'

            brevo_ok = _send_brevo_email(
                app=app,
                subject=subject,
                recipients=[recipient_email],
                html=html_body,
            )
            if brevo_ok:
                return True

            if _brevo_enabled(app):
                return False

            # Criar mensagem
            msg = Message(
                subject=subject,
                recipients=[recipient_email],
                html=html_body
            )

            # DEBUG: envio síncrono para expor erro SMTP no terminal imediatamente
            try:
                if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD') or not app.config.get('MAIL_DEFAULT_SENDER'):
                    print("❌ [SMTP] Credenciais SMTP ausentes. Verifique no .env:")
                    print("   - MAIL_DEFAULT_SENDER")
                    print("   - MAIL_DEFAULT_SENDER_SENHA")
                    return False
                mail.send(msg)
                print(f"✅ [SMTP] Convite enviado para {recipient_email}")
                return True
            except Exception as e:
                print(f"❌ [SMTP] Falha ao enviar convite para {recipient_email}: {e}")
                print(traceback.format_exc())
                return False
            
    except Exception as e:
        logger.error(f"❌ Erro ao enviar convite: {str(e)}")
        print(f"❌ Erro ao montar/enviar convite: {str(e)}")
        print(traceback.format_exc())
        return False

def send_share_accepted(owner_email: str, shared_email: str, app: Flask):
    """
    Envia email notificando que o convite foi aceito
    
    Args:
        owner_email: Email de quem compartilhou
        shared_email: Email de quem aceitou
        app: Aplicação Flask
    """
    try:
        with app.app_context():
            email_template = """
            <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: linear-gradient(135deg, #22c55e, #16a34a); color: white; padding: 20px; border-radius: 8px; }
                        .content { background: #f8fafc; padding: 20px; border-radius: 8px; margin: 20px 0; }
                        .footer { text-align: center; color: #999; font-size: 12px; margin-top: 20px; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>✅ Convite Aceito!</h1>
                        </div>
                        
                        <div class="content">
                            <p>Olá,</p>
                            
                            <p><strong>{{ shared_email }}</strong> aceitou seu convite para compartilhar o NEXUSRDR!</p>
                            
                            <p>Agora vocês podem trabalhar juntos no sistema de gestão financeira.</p>
                            
                            <p>Acesse o sistema para começar: <a href="https://seu-dominio.com/finance">NEXUSRDR</a></p>
                        </div>
                        
                        <div class="footer">
                            <p>Este é um email automático. Por favor, não responda.</p>
                            <p>NEXUSRDR - Sistema de Gestão Financeira</p>
                        </div>
                    </div>
                </body>
            </html>
            """
            
            html_body = render_template_string(
                email_template,
                shared_email=shared_email
            )

            subject = '✅ Seu convite foi aceito!'

            brevo_ok = _send_brevo_email(
                app=app,
                subject=subject,
                recipients=[owner_email],
                html=html_body,
            )
            if brevo_ok:
                return True

            if _brevo_enabled(app):
                return False
            
            msg = Message(
                subject=subject,
                recipients=[owner_email],
                html=html_body
            )
            
            # Enviar em background (não bloqueia a requisição)
            if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
                print("❌ [SMTP] Credenciais SMTP ausentes. Verifique no .env:")
                print("   - MAIL_DEFAULT_SENDER")
                print("   - MAIL_DEFAULT_SENDER_SENHA")
                return False
            _send_email_background(app, msg)
            print(f"📧 Email de confirmação enfileirado para {owner_email}")
            return True
            
    except Exception as e:
        print(f"❌ Erro ao preparar email: {str(e)}")
        return False


def send_verification_code(recipient_email: str, code: str, app: Flask):
    """Envia código de verificação de email"""
    try:
        with app.app_context():
            email_template = """
            <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: linear-gradient(135deg, #3b82f6, #1e40af); color: white; padding: 20px; border-radius: 8px; text-align: center; }
                        .content { background: #f8fafc; padding: 30px; border-radius: 8px; margin: 20px 0; text-align: center; }
                        .code { font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #3b82f6; background: white; padding: 15px; border-radius: 8px; margin: 20px 0; }
                        .footer { text-align: center; color: #999; font-size: 12px; margin-top: 20px; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>Código de Verificação</h1>
                        </div>
                        <div class="content">
                            <p>Use o código abaixo para verificar seu email:</p>
                            <div class="code">{{ code }}</div>
                            <p><small>Este código expira em 15 minutos.</small></p>
                        </div>
                        <div class="footer">
                            <p>NEXUSRDR - Sistema de Gestão Financeira</p>
                        </div>
                    </div>
                </body>
            </html>
            """
            
            html_body = render_template_string(email_template, code=code)
            subject = 'Código de Verificação - NEXUSRDR'

            brevo_ok = _send_brevo_email(
                app=app,
                subject=subject,
                recipients=[recipient_email],
                html=html_body,
            )
            if brevo_ok:
                return True

            if _brevo_enabled(app):
                return False

            msg = Message(subject=subject, recipients=[recipient_email], html=html_body)
            
            # Enviar em background (não bloqueia a requisição)
            if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
                print("❌ [SMTP] Credenciais SMTP ausentes. Verifique no .env:")
                print("   - MAIL_DEFAULT_SENDER")
                print("   - MAIL_DEFAULT_SENDER_SENHA")
                return False
            _send_email_background(app, msg)
            print(f"📧 Código de verificação enfileirado para {recipient_email}")
            return True
    except Exception as e:
        print(f"❌ Erro ao preparar código: {str(e)}")
        return False


def send_password_reset(recipient_email: str, reset_link: str, app: Flask):
    """Envia link de recuperação de senha"""
    try:
        with app.app_context():
            email_template = """
            <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: linear-gradient(135deg, #ef4444, #dc2626); color: white; padding: 20px; border-radius: 8px; }
                        .content { background: #f8fafc; padding: 20px; border-radius: 8px; margin: 20px 0; }
                        .button { display: inline-block; background: #ef4444; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; margin: 10px 0; }
                        .footer { text-align: center; color: #999; font-size: 12px; margin-top: 20px; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>Recuperação de Senha</h1>
                        </div>
                        <div class="content">
                            <p>Clique no botão abaixo para redefinir sua senha:</p>
                            <a href="{{ reset_link }}" class="button">Redefinir Senha</a>
                            <p><small>Este link expira em 1 hora.</small></p>
                        </div>
                        <div class="footer">
                            <p>NEXUSRDR - Sistema de Gestão Financeira</p>
                        </div>
                    </div>
                </body>
            </html>
            """
            
            html_body = render_template_string(email_template, reset_link=reset_link)
            subject = 'Recuperação de Senha - NEXUSRDR'

            brevo_ok = _send_brevo_email(
                app=app,
                subject=subject,
                recipients=[recipient_email],
                html=html_body,
            )
            if brevo_ok:
                return True

            if _brevo_enabled(app):
                return False

            msg = Message(subject=subject, recipients=[recipient_email], html=html_body)
            
            # Enviar em background (não bloqueia a requisição)
            if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
                print("❌ [SMTP] Credenciais SMTP ausentes. Verifique no .env:")
                print("   - MAIL_DEFAULT_SENDER")
                print("   - MAIL_DEFAULT_SENDER_SENHA")
                return False
            _send_email_background(app, msg)
            print(f"📧 Link de recuperação enfileirado para {recipient_email}")
            return True
    except Exception as e:
        print(f"❌ Erro ao preparar link: {str(e)}")
        return False


def send_workspace_invitation(recipient_email: str, inviter_email: str, token: str, workspace_name: str, role: str, app: Flask):
    print(f"[WORKSPACE_INVITE] Iniciando envio para {recipient_email} (workspace={workspace_name}, role={role})")
    try:
        with app.app_context():
            from flask import url_for

            # Debug: mostrar configurações de email
            brevo_key = app.config.get('BREVO_API_KEY')
            brevo_sender = app.config.get('BREVO_SENDER_EMAIL')
            mail_sender = app.config.get('MAIL_DEFAULT_SENDER')
            print(f"[WORKSPACE_INVITE] BREVO_API_KEY={'configurada' if brevo_key else 'AUSENTE'}")
            print(f"[WORKSPACE_INVITE] BREVO_SENDER_EMAIL={brevo_sender or 'AUSENTE'}")
            print(f"[WORKSPACE_INVITE] MAIL_DEFAULT_SENDER={mail_sender or 'AUSENTE'}")

            base_url = app.config.get('APP_BASE_URL', '').rstrip('/')
            invite_path = url_for('gerenciamento_financeiro.open_workspace_invite', token=token)
            accept_url = f"{base_url}{invite_path}" if base_url else invite_path
            print(f"[WORKSPACE_INVITE] URL do convite: {accept_url}")

            role_labels = {
                'viewer': 'Visualizador (apenas leitura)',
                'editor': 'Editor (pode editar)',
                'owner': 'Proprietário',
            }
            role_label = role_labels.get(role, role)

            email_template = """
            <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: linear-gradient(135deg, #3b82f6, #1e40af); color: white; padding: 20px; border-radius: 8px; }
                        .content { background: #f8fafc; padding: 20px; border-radius: 8px; margin: 20px 0; }
                        .button { display: inline-block; background: #3b82f6; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; margin: 10px 0; }
                        .footer { text-align: center; color: #999; font-size: 12px; margin-top: 20px; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>🎉 Convite para Workspace</h1>
                        </div>

                        <div class="content">
                            <p>Olá,</p>
                            <p><strong>{{ inviter_email }}</strong> convidou você para participar do workspace <strong>{{ workspace_name }}</strong>.</p>
                            <p><strong>Permissão:</strong> {{ role_label }}</p>

                            <p>Clique no botão abaixo para aceitar o convite:</p>
                            <a href="{{ accept_url }}" class="button">Aceitar Convite</a>

                            <p>Ou copie e cole este link no seu navegador:</p>
                            <p><small>{{ accept_url }}</small></p>
                        </div>

                        <div class="footer">
                            <p>Este é um email automático. Por favor, não responda.</p>
                            <p>NEXUSRDR - Sistema de Gestão Financeira</p>
                        </div>
                    </div>
                </body>
            </html>
            """

            html_body = render_template_string(
                email_template,
                inviter_email=inviter_email,
                workspace_name=workspace_name,
                role_label=role_label,
                accept_url=accept_url,
            )

            subject = f"Convite para o workspace: {workspace_name}"

            brevo_ok = _send_brevo_email(
                app=app,
                subject=subject,
                recipients=[recipient_email],
                html=html_body,
            )
            if brevo_ok:
                return True

            if _brevo_enabled(app):
                return False

            msg = Message(
                subject=subject,
                recipients=[recipient_email],
                html=html_body,
            )

            try:
                if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD') or not app.config.get('MAIL_DEFAULT_SENDER'):
                    print("❌ [SMTP] Credenciais SMTP ausentes. Verifique no .env:")
                    print("   - MAIL_DEFAULT_SENDER")
                    print("   - MAIL_DEFAULT_SENDER_SENHA")
                    return False
                mail.send(msg)
                print(f"✅ [SMTP] Convite de workspace enviado para {recipient_email}")
                return True
            except Exception as e:
                print(f"❌ [SMTP] Falha ao enviar convite de workspace para {recipient_email}: {e}")
                print(traceback.format_exc())
                return False

    except Exception as e:
        logger.error(f"❌ Erro ao montar/enviar convite de workspace: {str(e)}")
        print(f"❌ Erro ao montar/enviar convite de workspace: {str(e)}")
        print(traceback.format_exc())
        return False

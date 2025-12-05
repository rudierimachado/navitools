#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Serviço de envio de emails para o NEXUSRDR"""

from flask import Flask, render_template_string
from flask_mail import Mail, Message
import os
from dotenv import load_dotenv

load_dotenv()

mail = Mail()

def init_mail(app: Flask):
    """Inicializa o serviço de email com Brevo"""
    # Configuração padrão para Brevo
    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp-relay.brevo.com')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', True)
    app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', False)
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@nexusrdr.com')
    
    # Timeout aumentado para evitar problemas de conexão
    app.config['MAIL_TIMEOUT'] = int(os.getenv('MAIL_TIMEOUT', 120))
    
    # Base da URL da aplicação para montar links de convite
    # Ex.: APP_BASE_URL=http://localhost:5000 ou https://nexusrdr.com
    app.config['APP_BASE_URL'] = os.getenv('APP_BASE_URL', '').rstrip('/')

    mail.init_app(app)

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
    # Se não houver credenciais de email, apenas log
    if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        print(f"📧 [MODO TESTE] Email seria enviado para {recipient_email}")
        print(f"   De: {owner_email}")
        print(f"   Tipo: Convite de Compartilhamento")
        return True
    
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
            
            # Criar mensagem
            msg = Message(
                subject=f'🎉 Convite para compartilhar NEXUSRDR',
                recipients=[recipient_email],
                html=html_body
            )
            
            # Enviar
            mail.send(msg)
            print(f"✅ Email enviado para {recipient_email}")
            return True
            
    except Exception as e:
        print(f"❌ Erro ao enviar email: {str(e)}")
        return False

def send_share_accepted(owner_email: str, shared_email: str, app: Flask):
    """
    Envia email notificando que o convite foi aceito
    
    Args:
        owner_email: Email de quem compartilhou
        shared_email: Email de quem aceitou
        app: Aplicação Flask
    """
    # Se não houver credenciais de email, apenas log
    if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        print(f"📧 [MODO TESTE] Email seria enviado para {owner_email}")
        print(f"   De: {shared_email}")
        print(f"   Tipo: Confirmação de Aceitação")
        return True
    
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
            
            msg = Message(
                subject='✅ Seu convite foi aceito!',
                recipients=[owner_email],
                html=html_body
            )
            
            mail.send(msg)
            print(f"✅ Email de confirmação enviado para {owner_email}")
            return True
            
    except Exception as e:
        print(f"❌ Erro ao enviar email: {str(e)}")
        return False


def send_verification_code(recipient_email: str, code: str, app: Flask):
    """Envia código de verificação de email"""
    if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        print(f"📧 [MODO TESTE] Código de verificação para {recipient_email}: {code}")
        return True
    
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
            msg = Message(subject='Código de Verificação - NEXUSRDR', recipients=[recipient_email], html=html_body)
            mail.send(msg)
            print(f"✅ Código enviado para {recipient_email}")
            return True
    except Exception as e:
        print(f"❌ Erro ao enviar código: {str(e)}")
        return False


def send_password_reset(recipient_email: str, reset_link: str, app: Flask):
    """Envia link de recuperação de senha"""
    if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        print(f"📧 [MODO TESTE] Link de recuperação para {recipient_email}: {reset_link}")
        return True
    
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
            msg = Message(subject='Recuperação de Senha - NEXUSRDR', recipients=[recipient_email], html=html_body)
            mail.send(msg)
            print(f"✅ Link de recuperação enviado para {recipient_email}")
            return True
    except Exception as e:
        print(f"❌ Erro ao enviar link: {str(e)}")
        return False

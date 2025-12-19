"""
Rotas Web (HTML) - Gerenciamento Financeiro
============================================

Interface web para gestão financeira via navegador.
"""

import os
from flask import Blueprint, render_template, send_file, abort

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
    # Prioridade 1: APK versionado dentro do módulo (mais simples para deploy)
    module_apk_path = os.path.join(
        os.path.dirname(__file__),
        "app-armeabi-v7a-release.apk",
    )

    # Fallback: APK em static/downloads (caso você prefira manter em static)
    static_apk_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "static",
        "downloads",
        "finance-app.apk",
    )

    apk_path = module_apk_path if os.path.exists(module_apk_path) else static_apk_path
    
    if not os.path.exists(apk_path):
        abort(404, description="APK não encontrado no servidor.")
    
    return send_file(
        apk_path,
        as_attachment=True,
        download_name="nexus-financeiro.apk",
        mimetype="application/vnd.android.package-archive"
    )

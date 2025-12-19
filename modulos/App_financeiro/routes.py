"""
Rotas Web (HTML) - Gerenciamento Financeiro
============================================

Interface web para gestão financeira via navegador.
"""

import os
from flask import Blueprint, render_template, send_file, abort, request

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

from flask import Flask
from flask_cors import CORS
from .routes import gerenciamento_financeiro_bp

app = Flask(__name__)
CORS(app, origins=["*"], supports_credentials=True)

# Registrar o blueprint
app.register_blueprint(gerenciamento_financeiro_bp)

# Configurações se precisar
app.config['SECRET_KEY'] = 'sua-chave-secreta'
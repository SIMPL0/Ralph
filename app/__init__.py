# /home/ubuntu/ralph_deploy_novo_refactored/app/__init__.py
import os
from flask import Flask
from flask_cors import CORS

# Importar configurações se existirem (opcional)
# from .. import config

def create_app():
    app = Flask(__name__, 
                static_folder=\'static\', 
                template_folder=\'templates\')
    
    # Configuração de CORS
    CORS(app, resources={r"/*": {"origins": "*"}})

    # Configurações da aplicação (ex: chave secreta, se necessário)
    # app.config.from_object(config.Config)
    app.config[\'SECRET_KEY\'] = os.getenv(\'FLASK_SECRET_KEY\', \'uma-chave-secreta-muito-segura\')

    # Registrar Blueprints ou rotas diretamente
    with app.app_context():
        from . import main # Importa as rotas de main.py
        # Se usar Blueprints:
        # from .main import main_bp
        # app.register_blueprint(main_bp)

    print("Flask app created.")
    return app


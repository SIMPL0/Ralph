# /home/ubuntu/ralph_deploy_novo_refactored/run.py
import os
from app import create_app

# Carregar variáveis de ambiente (opcional, se usar .env)
# from dotenv import load_dotenv
# load_dotenv()

app = create_app()

if __name__ == \"__main__\":
    # Obtém a porta da variável de ambiente ou usa 5000 como padrão
    port = int(os.environ.get(\"PORT\", 5000))
    # Executa o app em modo de debug (ideal para desenvolvimento)
    # Para produção, use um servidor WSGI como Gunicorn
    app.run(host=\"0.0.0.0\", port=port, debug=True)


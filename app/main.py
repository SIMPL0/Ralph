# /home/ubuntu/ralph_deploy_novo_refactored/app/main.py
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from flask import Blueprint, request, jsonify, send_file, current_app, render_template # Import current_app

# Importar funções do módulo pdf_utils
from .pdf_utils.generator import generate_pdf_report_weasyprint, generate_summary_analysis

# --- Configurações (Idealmente viriam de config.py ou variáveis de ambiente) ---
# Estas podem ser acessadas via current_app.config se configuradas no __init__.py
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "simploai.ofc@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "simploai.ofc@gmail.com")

# --- Função de Envio de Email (Mantida para compatibilidade, se necessário) ---
def send_email_notification(subject, text_body, recipient_email, attachment_path=None):
    """Função genérica para enviar emails com ou sem anexo."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("WARN: Credenciais de email não configuradas. Pulando envio.")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(text_body, "plain"))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as file:
                part = MIMEApplication(file.read(), Name=os.path.basename(attachment_path))
            part["Content-Disposition"] = f"attachment; filename=\"{os.path.basename(attachment_path)}\""
            msg.attach(part)
            print(f"DEBUG: Anexando arquivo: {attachment_path}")
        elif attachment_path:
            print(f"WARN: Caminho do anexo fornecido mas arquivo não encontrado: {attachment_path}")

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"Email enviado com sucesso para {recipient_email}")
        return True

    except Exception as e:
        print(f"Erro ao enviar email para {recipient_email}: {e}")
        import traceback
        traceback.print_exc()
        return False

# --- Rotas da API --- 
# Se usar Blueprint:
# main_bp = Blueprint("main", __name__)
# @main_bp.route("/analyze", methods=["POST"])

# Usando rotas diretamente no app (requer importação em __init__.py)
from flask import current_app as app # Importar app diretamente se não usar blueprint

@app.route("/analyze", methods=["POST"])
def analyze_chat():
    """Endpoint para analisar o histórico de chat e gerar um SUMÁRIO."""
    print("=== Endpoint /analyze chamado ===")
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data received"}), 400

        chat_history = data.get("chatHistory", [])
        user_name = data.get("userName", "User")
        profile = data.get("profile", "unknown")

        if not chat_history:
            return jsonify({"error": "Chat history is empty"}), 400

        print(f"DEBUG: Gerando sumário para {user_name} ({profile})...")
        # Chama a função de sumário do generator.py
        summary_text, success = generate_summary_analysis(chat_history, profile, user_name)

        response_data = {
            "analysis_text": summary_text,
            "status": "success" if success else "error",
            "pdf_ready": success # PDF só pode ser gerado se sumário foi ok
        }
        print(f"DEBUG: Retornando sumário. Status: {response_data["status"]}")
        return jsonify(response_data), 200

    except Exception as e:
        print(f"ERROR CRÍTICO no endpoint /analyze: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "analysis_text": f"Erro interno ao processar o sumário: {str(e)}",
            "status": "error",
            "pdf_ready": False
        }), 500

@app.route("/generate-pdf", methods=["POST"])
def generate_pdf():
    """Endpoint para gerar e retornar PDF usando WeasyPrint."""
    print("=== Endpoint /generate-pdf chamado ===")
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data received"}), 400

        chat_history = data.get("chatHistory", [])
        user_name = data.get("userName", "User")
        profile = data.get("profile", "unknown")

        if not chat_history:
             return jsonify({"error": "Chat history is empty"}), 400

        print(f"DEBUG: Iniciando geração de PDF (WeasyPrint) para {user_name} ({profile})")

        # Chama a nova função de geração de PDF com WeasyPrint
        pdf_path, pdf_filename = generate_pdf_report_weasyprint(
            chat_history, profile, user_name
        )

        if pdf_path and pdf_filename:
            print(f"DEBUG: PDF gerado: {pdf_filename}. Enviando cópia para Simplo (se configurado)...")

            # Tenta enviar cópia para o Simplo (opcional)
            try:
                if EMAIL_RECEIVER and EMAIL_SENDER and EMAIL_PASSWORD:
                    simplo_subject = f"Ralph Analysis PDF - {user_name} ({profile})"
                    simplo_body = f"Anexo relatório PDF gerado para {user_name} ({profile}).\nData: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"
                    
                    email_sent_to_simplo = send_email_notification(
                        subject=simplo_subject,
                        text_body=simplo_body,
                        recipient_email=EMAIL_RECEIVER,
                        attachment_path=pdf_path
                    )
                    if email_sent_to_simplo:
                        print(f"DEBUG: Cópia do PDF enviada para {EMAIL_RECEIVER}")
                    else:
                        print(f"WARN: Falha ao enviar cópia do PDF para {EMAIL_RECEIVER}")
                else:
                    print("INFO: Envio de email para Simplo não configurado.")
            except Exception as email_error:
                print(f"WARN: Erro não crítico ao tentar enviar cópia do email para Simplo: {email_error}")

            print(f"DEBUG: Retornando PDF {pdf_filename} para download.")
            # Retorna o PDF para download
            return send_file(
                pdf_path,
                as_attachment=True,
                download_name=pdf_filename,
                mimetype=\"application/pdf\"
            )
        else:
             # A função generate_pdf_report_weasyprint já logou o erro específico
             print("ERROR: Falha na geração do PDF (generate_pdf_report_weasyprint retornou None).")
             return jsonify({"error": "Falha interna ao gerar o relatório PDF. Verifique os logs do servidor."}), 500

    except Exception as e:
        print(f"ERROR CRÍTICO no endpoint /generate-pdf: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erro inesperado no servidor durante a geração do PDF: {str(e)}"}), 500

@app.route("/health")
def health_check():
    """Endpoint para verificar a saúde do serviço."""
    # Verifica se o cliente OpenAI (DeepSeek) foi inicializado no generator.py
    from .pdf_utils import generator
    deepseek_ok = generator.client is not None
    email_ok = bool(EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER)
    return jsonify({
        "status": "healthy",
        "deepseek_configured": deepseek_ok,
        "email_configured": email_ok
    })

# Rota para servir o index.html principal (se necessário)
@app.route("/")
def index():
    # Assume que index.html está na pasta static configurada no __init__.py
    return app.send_static_file("index.html")



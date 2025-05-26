import os
import smtplib
import json
import random
import re
import html
import uuid # Para nomes de arquivo únicos
from openai import OpenAI # Importa OpenAI para API compatível com DeepSeek
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication # Para anexar arquivos
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
app = Flask(__name__, static_folder='static')
CORS(app) # Permite requisições do frontend

# --- Configuração de Variáveis de Ambiente ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "simploai.ofc@gmail.com") # Email padrão do usuário
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") # Chave da API DeepSeek
# -------------------------------------------

# Configura cliente OpenAI para DeepSeek (apenas se a chave for fornecida)
deepseek_client = None
if DEEPSEEK_API_KEY:
    try:
        deepseek_client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com/v1" # URL base da API DeepSeek
        )
        print("Cliente DeepSeek (via OpenAI SDK) configurado com sucesso.")
    except Exception as e:
        print(f"Erro ao configurar cliente DeepSeek: {e}")
        deepseek_client = None # Garante que o cliente seja None se a configuração falhar
else:
    print("Aviso: Variável de ambiente DEEPSEEK_API_KEY não definida. Análise da IA será pulada.")

def format_conversation_to_text(chat_history, user_name="User"):
    """Formata o histórico do chat em uma string de texto simples."""
    text_log = f"Conversation Log for {user_name}:\n" + "="*30 + "\n\n"
    for msg in chat_history:
        sender = msg.get("sender")
        content = msg.get("content", "(empty)")
        # Remove HTML simples que pode vir do frontend (ex: indicador de digitação)
        clean_content = re.sub("<.*?>", "", content).strip()
        if not clean_content:
            continue # Pula mensagens vazias ou apenas com HTML

        if sender == "bot":
            text_log += f"Ralph (Bot): {clean_content}\n"
        elif sender == "user":
            text_log += f"{user_name}: {clean_content}\n"
        text_log += "---\n"
    return text_log

def save_conversation_to_file(conversation_text):
    """Salva a string da conversa em um arquivo TXT temporário."""
    try:
        # Cria um diretório temporário se não existir
        temp_dir = "/tmp/ralph_conversations"
        os.makedirs(temp_dir, exist_ok=True)

        filename = f"conversation_{uuid.uuid4()}.txt"
        filepath = os.path.join(temp_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(conversation_text)
        print(f"Conversa salva em: {filepath}")
        return filepath
    except Exception as e:
        print(f"Erro ao salvar arquivo de conversa: {e}")
        return None

def generate_deepseek_analysis(conversation_text):
    """Gera análise usando DeepSeek com base no texto da conversa."""
    if not deepseek_client:
        return "AI analysis could not be performed. Configuration missing."

    # Novo prompt conforme solicitado pelo usuário
    prompt = f"""(Based on the user responses in the following conversation log, what mistakes are they making, what could they improve, and subtly present a solution for some of their business problems? Within this solution, subtly introduce AI automations (without naming any specific AI tools) and explain how they would be beneficial for their business. Respond in English and with a maximum of 1000 characters.)

Conversation Log:
```txt
{conversation_text}
```
"""

    try:
        print("\n--- Enviando requisição para DeepSeek ---")
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat", # Modelo de chat padrão do DeepSeek
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350,  # Aproximação para ~1000 caracteres (ajustar se necessário)
            temperature=0.7,
        )
        print("--- Resposta do DeepSeek recebida ---")

        ai_analysis_text = response.choices[0].message.content.strip()

        # Garante que não exceda muito o limite (corte simples)
        if len(ai_analysis_text) > 1100: # Uma margem pequena
             ai_analysis_text = ai_analysis_text[:1000] + "... (truncated)"

        return ai_analysis_text

    except Exception as e:
        print(f"Erro ao chamar API DeepSeek: {e}")
        return f"An error occurred during the AI analysis generation using DeepSeek. Error details: {html.escape(str(e))}"

def send_email_notification(subject, text_body, attachment_path=None):
    """Envia um email com anexo opcional."""
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER, SMTP_SERVER]):
        print("Configuração de email incompleta. Pulando notificação por email.")
        return False

    message = MIMEMultipart()
    message["From"] = EMAIL_SENDER
    message["To"] = EMAIL_RECEIVER
    message["Subject"] = subject

    # Anexa o corpo do texto
    message.attach(MIMEText(text_body, "plain", "utf-8"))

    # Anexa o arquivo TXT, se fornecido
    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as attachment:
                part = MIMEApplication(attachment.read(), Name=os.path.basename(attachment_path))
            part["Content-Disposition"] = f"attachment; filename=\"{os.path.basename(attachment_path)}\""
            message.attach(part)
            print(f"Anexo {os.path.basename(attachment_path)} adicionado ao email.")
        except Exception as e:
            print(f"Erro ao anexar arquivo {attachment_path}: {e}")

    try:
        print(f"Conectando ao servidor SMTP: {SMTP_SERVER}:{SMTP_PORT}")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.ehlo()
        server.starttls()
        server.ehlo()
        print("Logando na conta de email...")
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        print("Enviando email...")
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, message.as_string())
        server.quit()
        print(f"Email enviado com sucesso para {EMAIL_RECEIVER}")
        # Tenta remover o arquivo temporário após o envio
        if attachment_path and os.path.exists(attachment_path):
             try:
                 os.remove(attachment_path)
                 print(f"Arquivo temporário {attachment_path} removido.")
             except Exception as e:
                 print(f"Erro ao remover arquivo temporário {attachment_path}: {e}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"Erro de Autenticação SMTP: {e}. Verifique email/senha (Senha de App?).")
        return False
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        return False

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(app.static_folder, path)

@app.route("/analyze", methods=["POST"])
def analyze_data():
    """Recebe dados, salva conversa, gera análise IA (DeepSeek), envia email, retorna análise."""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Nenhum dado recebido"}), 400

        log_data = {k: v for k, v in data.items() if k != 'images'} # Não loga imagens base64
        print("Dados recebidos para análise (sem imagens):", json.dumps(log_data, indent=2))

        user_name = data.get("userName", "User")
        chat_history = data.get("chatHistory", [])

        # --- Formatar e Salvar Conversa --- 
        conversation_text = format_conversation_to_text(chat_history, user_name)
        conversation_filepath = save_conversation_to_file(conversation_text)
        # -----------------------------------

        # --- Gerar Análise IA (DeepSeek) --- 
        ai_analysis_text = "Analysis skipped (file saving failed)." # Mensagem padrão
        print("DEBUG: Verificando se o arquivo de conversa foi salvo...") # Log 1
        if conversation_filepath:
             print("DEBUG: Arquivo salvo. Chamando generate_deepseek_analysis...") # Log 2
             ai_analysis_text = generate_deepseek_analysis(conversation_text)
             print(f"DEBUG: Resultado de generate_deepseek_analysis: {str(ai_analysis_text)[:200]}...") # Log 3
        else:
             print("Pulando análise da IA porque o arquivo de conversa não pôde ser salvo.")
        
        # Garante que ai_analysis_text nunca seja None ou vazio para jsonify
        if not ai_analysis_text:
            print("WARN: ai_analysis_text estava vazio ou None. Definindo para mensagem padrão.")
            ai_analysis_text = "Analysis result was empty or could not be generated."
        # -----------------------------------

        # --- Preparar e Enviar Email --- 
        email_subject = f"Ralph Analysis Completed for {user_name}"
        email_body = f"Analysis generated by Ralph (DeepSeek AI) for {user_name}:\n\n{ai_analysis_text}\n\n---\nFull conversation log attached."
        
        send_email_notification(email_subject, email_body, conversation_filepath)
        # -------------------------------

        # --- Retornar Análise para Frontend --- 
        # Retorna o texto plano da análise
        response_data = {"analysis_text": ai_analysis_text}
        print(f"DEBUG: Preparando para retornar JSON: {json.dumps(response_data)}") # Log 4
        return jsonify(response_data)
        # ---------------------------------------

    except Exception as e:
        print(f"Erro no endpoint /analyze: {e}")
        # Fornece uma mensagem de erro genérica para o frontend
        return jsonify({"analysis_text": f"An unexpected error occurred processing your request. Please try again later. Error: {html.escape(str(e))}"}), 500

if __name__ == "__main__":
    # Esta parte é principalmente para teste local, Render usa o comando gunicorn
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))




@app.route('/', methods=['POST'])
def handle_root_post():
    print("\n--- WARNING: POST request received at root ('/') ---")
    try:
        data = request.get_data(as_text=True)
        print(f"Request Headers: {request.headers}")
        print(f"Request Body: {data[:500]}... (truncated)") # Log first 500 chars
    except Exception as e:
        print(f"Error logging root POST request: {e}")
    return jsonify({"error": "Endpoint not found. Use /analyze for analysis."}), 404


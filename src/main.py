import os
import smtplib
import json
import random
import re
import html
import uuid # Para nomes de arquivo únicos
from openai import OpenAI # Importa OpenAI corretamente para SDK v1+
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication # Para anexar arquivos
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# --- Determinar Caminhos Absolutos ---
# Diretório onde main.py está localizado (src)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Diretório raiz do projeto (um nível acima de src)
PROJECT_ROOT = os.path.dirname(APP_DIR)
# Caminho absoluto para a pasta static
STATIC_FOLDER_PATH = os.path.join(PROJECT_ROOT, 'static')
print(f"DEBUG: Project Root: {PROJECT_ROOT}")
print(f"DEBUG: Static Folder Path: {STATIC_FOLDER_PATH}")
# -------------------------------------

app = Flask(__name__, static_folder=STATIC_FOLDER_PATH)
CORS(app) # Permite requisições do frontend

# --- Configuração de Variáveis de Ambiente ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "simploai.ofc@gmail.com") # Email padrão do usuário
OPENAI_API_KEY = "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" # TODO: Use environment variable for security
# -------------------------------------------

# --- Configuração Global do Cliente OpenAI para ChatGPT (v1+ SDK) ---
client = None
if OPENAI_API_KEY:
    try:
        client = OpenAI(
            api_key=OPENAI_API_KEY
            # base_url é omitido para usar o padrão da OpenAI
        )
        print("Cliente OpenAI (ChatGPT) configurado com sucesso.")
    except Exception as e:
        print(f"Erro ao configurar cliente OpenAI: {e}")
        client = None
else:
    print("Aviso: Variável OPENAI_API_KEY não definida ou inválida. Análise da IA será pulada.")
# ---------------------------------------------------------------------

def format_conversation_to_text(chat_history, user_name="User", profile="unknown"):
    """Formata o histórico do chat em uma string de texto simples."""
    text_log = f"Real Estate Business Analysis for {user_name}\n"
    text_log += f"Profile: {profile.title()}\n"
    text_log += "="*50 + "\n\n"
    
    for i, msg in enumerate(chat_history):
        sender = msg.get("sender")
        content = msg.get("content", "(empty)")
        # Remove HTML simples que pode vir do frontend
        clean_content = re.sub("<.*?>", "", content).strip()
        if not clean_content or "To start, please tell me" in clean_content:
            continue # Pula mensagens vazias ou de seleção de perfil

        if sender == "bot":
            text_log += f"Ralph (AI): {clean_content}\n\n"
        elif sender == "user":
            text_log += f"{user_name}: {clean_content}\n\n"
        
        text_log += "-" * 30 + "\n\n"
    
    return text_log

def save_conversation_to_file(conversation_text):
    """Salva a string da conversa em um arquivo TXT temporário."""
    try:
        # Usa diretório temporário do sistema
        import tempfile
        temp_dir = tempfile.gettempdir()
        
        filename = f"ralph_conversation_{uuid.uuid4().hex[:8]}.txt"
        filepath = os.path.join(temp_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(conversation_text)
        
        print(f"Conversa salva em: {filepath}")
        return filepath
    except Exception as e:
        print(f"Erro ao salvar arquivo de conversa: {e}")
        return None

def generate_chatgpt_analysis(conversation_text, profile):
    """Gera análise usando ChatGPT com base no texto da conversa."""
    if not client:
        return "AI analysis could not be performed. OpenAI API configuration missing or failed."

    # Prompt melhorado baseado no perfil
    profile_context = {
        'individual': 'independent real estate agent',
        'employee': 'real estate company employee',
        'owner': 'real estate business owner'
    }
    
    context = profile_context.get(profile, 'real estate professional')
    
    prompt = f"""You are Ralph, an AI business analyst specializing in real estate. Based on the conversation below with a {context}, provide a comprehensive business analysis.

Your analysis should include:
1. Current business strengths and weaknesses identified
2. Key areas for improvement
3. Specific actionable recommendations
4. How AI automation could solve their biggest pain points (without naming specific tools)
5. Potential ROI and efficiency gains from implementing your suggestions

Keep the tone professional yet conversational, as if you're their personal business consultant. Limit response to 800 words maximum.

Conversation Data:
{conversation_text}

Analysis:"""

    try:
        print("\n--- Enviando requisição para OpenAI API ---")
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo", # Modelo OpenAI
            messages=[
                {
                    "role": "system", 
                    "content": "You are Ralph, an expert AI business analyst for real estate professionals. Provide actionable, specific advice based on the conversation data."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            max_tokens=1000,
            temperature=0.7,
        )
        
        print("--- Resposta da OpenAI API recebida ---")
        
        ai_analysis_text = response.choices[0].message.content.strip()
        
        if not ai_analysis_text:
            return "Analysis could not be generated. Please try again."
            
        # Adiciona assinatura do Ralph
        ai_analysis_text += "\n\n---\nAnalysis generated by Ralph AI\nReal Estate Business Consultant"
        
        return ai_analysis_text

    except Exception as e:
        print(f"Erro ao chamar API OpenAI: {e}")
        error_msg = f"Error generating AI analysis: {str(e)}"
        return error_msg

def send_email_notification(subject, text_body, attachment_path=None):
    """Envia um email com anexo opcional."""
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("Configuração de email incompleta. Pulando notificação por email.")
        return False

    try:
        message = MIMEMultipart()
        message["From"] = EMAIL_SENDER
        message["To"] = EMAIL_RECEIVER
        message["Subject"] = subject

        # Anexa o corpo do texto
        message.attach(MIMEText(text_body, "plain", "utf-8"))

        # Anexa o arquivo TXT, se fornecido
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as attachment:
                part = MIMEApplication(attachment.read(), Name=os.path.basename(attachment_path))
            part["Content-Disposition"] = f"attachment; filename=\"{os.path.basename(attachment_path)}\""
            message.attach(part)
            print(f"Anexo {os.path.basename(attachment_path)} adicionado ao email.")

        print(f"Conectando ao servidor SMTP: {SMTP_SERVER}:{SMTP_PORT}")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, message.as_string())
        server.quit()
        
        print(f"Email enviado com sucesso para {EMAIL_RECEIVER}")
        
        # Remove arquivo temporário
        if attachment_path and os.path.exists(attachment_path):
            try:
                os.remove(attachment_path)
                print(f"Arquivo temporário removido: {attachment_path}")
            except Exception as e:
                print(f"Erro ao remover arquivo temporário: {e}")
                
        return True
        
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        return False

@app.route("/")
def index():
    print(f"DEBUG: Servindo index.html de {app.static_folder}")
    return send_from_directory(app.static_folder, 'index.html')

@app.route("/<path:path>")
def static_files(path):
    print(f"DEBUG: Servindo arquivo estático '{path}' de {app.static_folder}")
    file_path = os.path.join(app.static_folder, path)
    if os.path.isfile(file_path):
        return send_from_directory(app.static_folder, path)
    else:
        print(f"WARN: Arquivo estático não encontrado: {file_path}")
        return jsonify({"error": "Static file not found"}), 404

@app.route("/analyze", methods=["POST"])
def analyze_data():
    """Recebe dados, salva conversa, gera análise IA (DeepSeek), envia email, retorna análise."""
    print("=== DEBUG: Iniciando processo de análise ===")
    
    try:
        # Verificar se recebeu dados JSON
        if not request.is_json:
            print("ERROR: Request não é JSON")
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        if not data:
            print("ERROR: Nenhum dado JSON recebido")
            return jsonify({"error": "No data received"}), 400

        print(f"DEBUG: Dados recebidos: {list(data.keys())}")

        user_name = data.get("userName", "User")
        profile = data.get("profile", "unknown")
        chat_history = data.get("chatHistory", [])

        print(f"DEBUG: user_name={user_name}, profile={profile}, chat_history length={len(chat_history)}")

        if not chat_history:
            print("ERROR: Histórico de chat vazio")
            return jsonify({"error": "Chat history is empty"}), 400

        # --- Formatar e Salvar Conversa --- 
        print("DEBUG: Formatando conversa...")
        conversation_text = format_conversation_to_text(chat_history, user_name, profile)
        print(f"DEBUG: Texto da conversa criado ({len(conversation_text)} caracteres)")
        
        conversation_filepath = save_conversation_to_file(conversation_text)
        print(f"DEBUG: Arquivo salvo em: {conversation_filepath}")

        # --- Gerar Análise IA (ChatGPT) --- 
        print("DEBUG: Iniciando análise IA...")
        if not client:
            ai_analysis_text = "AI analysis unavailable - OpenAI API not configured properly."
            print("WARN: Cliente OpenAI não configurado")
        else:
            ai_analysis_text = generate_chatgpt_analysis(conversation_text, profile)
            print(f"DEBUG: Análise gerada ({len(ai_analysis_text)} caracteres)")

        # Verificar se a análise foi gerada
        if not ai_analysis_text or ai_analysis_text.strip() == "":
            ai_analysis_text = "Analysis could not be generated at this time. Please try again later."
            print("WARN: Análise vazia, usando mensagem padrão")

        # --- Enviar Email (em background, não bloqueia resposta) --- 
        try:
            email_subject = f"Ralph Analysis - {user_name} ({profile})"
            email_body = f"New analysis completed:\n\n{ai_analysis_text}"
            send_email_notification(email_subject, email_body, conversation_filepath)
        except Exception as email_error:
            print(f"WARN: Erro no envio de email (não crítico): {email_error}")

        # --- Retornar Resposta --- 
        response_data = {
            "analysis_text": ai_analysis_text,
            "status": "success"
        }
        
        print(f"DEBUG: Retornando análise com {len(ai_analysis_text)} caracteres")
        return jsonify(response_data), 200

    except Exception as e:
        print(f"ERROR CRÍTICO: {e}")
        import traceback
        traceback.print_exc()
        
        error_response = {
            "analysis_text": f"Sorry, an error occurred while processing your analysis. Please try again. If the problem persists, contact support.\n\nError details: {str(e)[:200]}",
            "status": "error"
        }
        return jsonify(error_response), 500

@app.route("/health")
def health_check():
    """Endpoint para verificar se o serviço está funcionando."""
    return jsonify({
        "status": "healthy",
        "deepseek_configured": client is not None,
        "email_configured": bool(EMAIL_SENDER and EMAIL_PASSWORD)
    })

if __name__ == "__main__":
    print("Iniciando Flask app...")
    print(f"DeepSeek configurado: {client is not None}")
    print(f"Email configurado: {bool(EMAIL_SENDER and EMAIL_PASSWORD)}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
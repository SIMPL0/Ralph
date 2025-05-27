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
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") # Lê a chave da variável de ambiente
# -------------------------------------------

# --- Configuração Global do Cliente para DeepSeek (via OpenAI SDK v1+) ---
client = None
if DEEPSEEK_API_KEY:
    try:
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        print("Cliente DeepSeek (via OpenAI SDK) configurado com sucesso.")
    except Exception as e:
        print(f"Erro ao configurar cliente DeepSeek (via OpenAI SDK): {e}")
        client = None
else:
    print("Aviso: Variável DEEPSEEK_API_KEY não definida ou inválida. Análise da IA será pulada.")
# ---------------------------------------------------------------------

def format_conversation_to_text(chat_history, user_name="User", profile="unknown", max_messages=15):
    """Formata o histórico do chat em uma string de texto simples, limitando o número de mensagens."""
    text_log = f"Real Estate Business Analysis for {user_name}\n"
    text_log += f"Profile: {profile.title()}\n"
    text_log += "="*50 + "\n\n"
    
    # Limita o número de mensagens para evitar prompts muito grandes
    if len(chat_history) > max_messages:
        # Mantém as primeiras 5 mensagens (contexto inicial)
        initial_messages = chat_history[:5]
        # E as últimas (max_messages - 5) mensagens (contexto mais recente)
        recent_messages = chat_history[-(max_messages-5):]
        # Combina para ter no máximo max_messages
        limited_history = initial_messages + recent_messages
        text_log += "Note: Conversation history was trimmed to focus on key interactions.\n\n"
    else:
        limited_history = chat_history
    
    for i, msg in enumerate(limited_history):
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

def generate_deepseek_analysis(chat_history, profile, user_name="User"):
    """Gera análise usando DeepSeek com base no histórico de chat formatado como texto."""
    if not client:
        return "AI analysis could not be performed. DeepSeek API configuration missing or failed."

    # --- Formatar histórico como texto único com limite de mensagens ---
    conversation_text = format_conversation_to_text(chat_history, user_name, profile, max_messages=15)
    # -----------------------------------------------------------------

    # --- Preparar Prompt para a API OpenAI (estilo antigo) ---
    profile_context = {
        'individual': 'independent real estate agent',
        'employee': 'real estate company employee',
        'owner': 'real estate business owner'
    }
    context = profile_context.get(profile, 'real estate professional')

    # Prompt mais conciso e focado
    prompt = f"""Based on the conversation with a {context} named {user_name}, provide a business analysis covering:
1. Business strengths and weaknesses
2. Key improvement areas
3. Actionable recommendations
4. How automation could solve their pain points
5. Potential ROI from implementing suggestions

Keep professional yet conversational. Max 600 words.

Conversation Data:
{conversation_text}

Analysis:"""
    # ---------------------------------------------------------

    try:
        print("\n--- Enviando requisição para DeepSeek API com prompt único ---")
        # print(f"DEBUG: Prompt enviado (início): {prompt[:500]}...") # Descomentar para depuração

        # Ajuste de parâmetros para evitar timeout e uso excessivo de memória
        response = client.chat.completions.create(
            model="deepseek-chat", # Modelo DeepSeek
            messages=[
                {
                    "role": "system",
                    "content": f"You are Ralph, an expert AI business analyst for real estate professionals. Provide actionable, specific advice based on the conversation data provided by the user ({context})."
                },
                {
                    "role": "user",
                    "content": prompt # Envia o prompt completo com o histórico formatado
                }
            ],
            max_tokens=2000,  # Reduzido para evitar respostas muito longas
            temperature=0.7,
            timeout=30,  # Timeout explícito para a requisição
        )

        print("--- Resposta da DeepSeek API recebida ---")

        ai_analysis_text = response.choices[0].message.content.strip()

        if not ai_analysis_text:
            # Se a resposta ainda vier vazia, pode ser outro problema (ex: API key, fundos, filtro de conteúdo)
            return "Analysis could not be generated. Empty response received from API."

        # Adiciona assinatura do Ralph
        ai_analysis_text += "\n\n---\nAnalysis generated by Ralph AI\nReal Estate Business Consultant"

        return ai_analysis_text

    except Exception as e:
        print(f"Erro ao chamar API DeepSeek: {e}")
        # Verifica se o erro é de autenticação (pode indicar chave inválida)
        if "authentication" in str(e).lower():
             error_msg = f"Error generating AI analysis: Authentication failed. Please check your DeepSeek API key configuration. ({str(e)})"
        # Verifica se o erro é de saldo (rate limit / quota)
        elif "quota" in str(e).lower() or "limit" in str(e).lower() or "insufficient_quota" in str(e).lower():
             error_msg = f"Error generating AI analysis: API quota exceeded or insufficient funds. Please check your DeepSeek account billing. ({str(e)})"
        # Verifica se é timeout
        elif "timeout" in str(e).lower() or "timed out" in str(e).lower():
             error_msg = f"Error generating AI analysis: Request timed out. The conversation may be too long or the server is experiencing high load. Try again with a shorter conversation. ({str(e)})"
        else:
             error_msg = f"Error generating AI analysis: An unexpected error occurred. ({str(e)})"
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
    """Recebe dados, salva conversa, gera análise IA (ChatGPT), envia email, retorna análise."""
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

        # --- Formatar e Salvar Conversa (para email) --- 
        print("DEBUG: Formatando conversa para email...")
        # Usa o mesmo limite de mensagens para o email
        conversation_text_for_email = format_conversation_to_text(chat_history, user_name, profile, max_messages=15)
        print(f"DEBUG: Texto da conversa para email criado ({len(conversation_text_for_email)} caracteres)")
        
        conversation_filepath = save_conversation_to_file(conversation_text_for_email)
        print(f"DEBUG: Arquivo para email salvo em: {conversation_filepath}")

        # --- Implementação de fallback para conversas muito longas ---
        if len(chat_history) > 30:
            print("WARN: Histórico de chat muito longo, usando análise simplificada")
            # Extrai apenas as últimas respostas do usuário para análise
            user_responses = [msg.get("content", "") for msg in chat_history if msg.get("sender") == "user"]
            key_responses = user_responses[-10:] if len(user_responses) > 10 else user_responses
            
            # Cria um resumo das respostas para análise de fallback
            fallback_text = "Based on your responses, here are some key observations:\n\n"
            fallback_text += "1. You appear to be looking for ways to optimize your real estate business processes.\n"
            fallback_text += "2. There may be opportunities to streamline your client communication and follow-up.\n"
            fallback_text += "3. Consider implementing digital tools to automate repetitive tasks like scheduling and document management.\n"
            fallback_text += "4. A more structured approach to lead tracking could improve your conversion rates.\n"
            fallback_text += "5. Modern automation solutions could help you focus more on high-value client interactions.\n\n"
            fallback_text += "For a more detailed analysis, please try again with a shorter conversation or contact support."
            
            # Usa o fallback se a API falhar com histórico longo
            ai_analysis_text = fallback_text
            print("DEBUG: Usando análise de fallback devido ao tamanho do histórico")
        else:
            # --- Gerar Análise IA (DeepSeek - usando prompt único) --- 
            print("DEBUG: Iniciando análise IA...")
            if not client:
                ai_analysis_text = "AI analysis unavailable - DeepSeek API not configured properly."
                print("WARN: Cliente DeepSeek não configurado")
            else:
                # Passa chat_history, profile e user_name para a função
                ai_analysis_text = generate_deepseek_analysis(chat_history, profile, user_name)
                print(f"DEBUG: Análise gerada ({len(ai_analysis_text)} caracteres)")

        # Verificar se a análise foi gerada ou se houve erro específico da API
        if not ai_analysis_text or "Error generating AI analysis:" in ai_analysis_text:
            # Se a análise falhou (seja por erro ou resposta vazia), usa uma mensagem padrão
            # A mensagem de erro específica já foi logada dentro de generate_deepseek_analysis
            analysis_result_text = f"Analysis could not be generated at this time. Please try again later. If the problem persists, check the server logs or contact support. (Details: {ai_analysis_text})"
            print(f"WARN: Análise falhou ou vazia, usando mensagem padrão. Detalhes: {ai_analysis_text}")
        else:
            analysis_result_text = ai_analysis_text # Usa o texto da análise bem-sucedida

        # --- Enviar Email (em background, não bloqueia resposta) --- 
        try:
            email_subject = f"Ralph Analysis - {user_name} ({profile})"
            # Usa o texto formatado para o corpo do email, não a análise bruta
            email_body = f"New analysis completed for {user_name} ({profile}).\n\nConversation log attached.\n\n--- Generated Analysis ---\n{analysis_result_text}"
            send_email_notification(email_subject, email_body, conversation_filepath)
        except Exception as email_error:
            print(f"WARN: Erro no envio de email (não crítico): {email_error}")

        # --- Retornar Resposta --- 
        # Retorna o resultado da análise (ou a mensagem de erro formatada)
        response_data = {
            "analysis_text": analysis_result_text,
            "status": "success" if "Error generating AI analysis:" not in analysis_result_text else "error"
        }
        
        print(f"DEBUG: Retornando análise/status: {response_data['status']}")
        return jsonify(response_data), 200

    except Exception as e:
        print(f"ERROR CRÍTICO no endpoint /analyze: {e}")
        import traceback
        traceback.print_exc()
        
        error_response = {
            "analysis_text": f"Sorry, a critical error occurred while processing your analysis. Please try again. If the problem persists, contact support.\n\nError details: {str(e)[:200]}",
            "status": "error"
        }
        return jsonify(error_response), 500

@app.route("/health")
def health_check():
    """Endpoint para verificar se o serviço está funcionando."""
    return jsonify({
        "status": "healthy",
        "openai_configured": client is not None,
        "email_configured": bool(EMAIL_SENDER and EMAIL_PASSWORD)
    })

if __name__ == "__main__":
    print("Iniciando Flask app...")
    print(f"DeepSeek configurado: {client is not None}")
    print(f"Email configurado: {bool(EMAIL_SENDER and EMAIL_PASSWORD)}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)

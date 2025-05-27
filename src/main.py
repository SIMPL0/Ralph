import os
import smtplib
import json
import random
import re
import html
import uuid # Para nomes de arquivo únicos
import tempfile
from datetime import datetime
from openai import OpenAI # Importa OpenAI corretamente para SDK v1+
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication # Para anexar arquivos
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration

# --- Determinar Caminhos Absolutos ---
# Diretório onde main.py está localizado (src)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Diretório raiz do projeto (um nível acima de src)
PROJECT_ROOT = os.path.dirname(APP_DIR)
# Caminho absoluto para a pasta static
STATIC_FOLDER_PATH = os.path.join(PROJECT_ROOT, 'static')
# Pasta para armazenar PDFs temporários
PDF_FOLDER = os.path.join(tempfile.gettempdir(), 'ralph_reports')
os.makedirs(PDF_FOLDER, exist_ok=True)

print(f"DEBUG: Project Root: {PROJECT_ROOT}")
print(f"DEBUG: Static Folder Path: {STATIC_FOLDER_PATH}")
print(f"DEBUG: PDF Folder Path: {PDF_FOLDER}")
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
             error_msg = f"Error generating AI analysis: Request timed out. The conversation may be too long or the server is experiencing high load. ({str(e)})"
        else:
             error_msg = f"Error generating AI analysis: An unexpected error occurred. ({str(e)})"
        return error_msg

def extract_key_points_from_chat(chat_history, user_name):
    """Extrai pontos-chave do histórico de chat para uso no PDF de fallback."""
    user_messages = [msg.get("content", "") for msg in chat_history if msg.get("sender") == "user"]
    
    # Extrai informações básicas
    business_info = {
        "name": user_name,
        "focus_areas": [],
        "challenges": [],
        "tools_used": [],
        "goals": []
    }
    
    # Palavras-chave para categorizar respostas
    focus_keywords = ["focus", "specialize", "primary", "mainly", "mostly", "area", "market"]
    challenge_keywords = ["challenge", "difficult", "struggle", "problem", "issue", "pain point"]
    tool_keywords = ["tool", "software", "app", "platform", "system", "crm", "technology"]
    goal_keywords = ["goal", "aim", "target", "objective", "plan", "future", "growth"]
    
    # Analisa cada mensagem do usuário
    for msg in user_messages:
        msg_lower = msg.lower()
        
        # Categoriza com base em palavras-chave
        if any(keyword in msg_lower for keyword in focus_keywords):
            business_info["focus_areas"].append(msg)
        
        if any(keyword in msg_lower for keyword in challenge_keywords):
            business_info["challenges"].append(msg)
            
        if any(keyword in msg_lower for keyword in tool_keywords):
            business_info["tools_used"].append(msg)
            
        if any(keyword in msg_lower for keyword in goal_keywords):
            business_info["goals"].append(msg)
    
    return business_info

def generate_pdf_report(chat_history, profile, user_name="User"):
    """Gera um relatório PDF profissional com base no histórico do chat."""
    try:
        # Extrai informações-chave do chat
        business_info = extract_key_points_from_chat(chat_history, user_name)
        
        # Define o nome do arquivo PDF
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_filename = f"ralph_analysis_{user_name.lower().replace(' ', '_')}_{timestamp}.pdf"
        pdf_path = os.path.join(PDF_FOLDER, pdf_filename)
        
        # Prepara o conteúdo HTML para o PDF
        profile_title = {
            'individual': 'Independent Real Estate Agent',
            'employee': 'Real Estate Company Employee',
            'owner': 'Real Estate Business Owner'
        }.get(profile, 'Real Estate Professional')
        
        # Gera recomendações personalizadas com base nas informações extraídas
        recommendations = []
        automation_suggestions = []
        
        # Recomendações baseadas em desafios
        if business_info["challenges"]:
            recommendations.append("Implement a structured follow-up system to address client communication gaps")
            recommendations.append("Develop a clear process for lead qualification to focus on high-value prospects")
            automation_suggestions.append("Automated follow-up sequences for different client categories")
        else:
            recommendations.append("Create a systematic approach to track and analyze your business performance metrics")
            recommendations.append("Establish clear processes for each stage of your client journey")
            automation_suggestions.append("Automated performance tracking and reporting system")
        
        # Recomendações baseadas em ferramentas
        if business_info["tools_used"]:
            recommendations.append("Integrate your existing tools to create a seamless workflow")
            recommendations.append("Evaluate your current tech stack for redundancies and gaps")
            automation_suggestions.append("Workflow automation connecting your existing tools")
        else:
            recommendations.append("Invest in a comprehensive CRM system tailored to real estate")
            recommendations.append("Adopt digital tools for document management and transaction tracking")
            automation_suggestions.append("Document processing and management automation")
        
        # Recomendações baseadas em objetivos
        if business_info["goals"]:
            recommendations.append("Create measurable KPIs aligned with your stated business goals")
            recommendations.append("Develop a strategic plan with quarterly milestones")
            automation_suggestions.append("Goal tracking and progress notification system")
        else:
            recommendations.append("Set specific, measurable goals for the next 12 months")
            recommendations.append("Create a vision board for your ideal business in 3 years")
            automation_suggestions.append("Automated goal setting and tracking assistant")
            
        # Cria o HTML para o PDF
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Ralph Business Analysis for {user_name}</title>
            <style>
                @page {{
                    size: letter;
                    margin: 2.5cm 1.5cm;
                    @top-center {{
                        content: "Ralph Business Analysis";
                        font-family: 'Noto Sans CJK SC', sans-serif;
                        font-size: 9pt;
                        color: #666;
                    }}
                    @bottom-center {{
                        content: "Page " counter(page) " of " counter(pages);
                        font-family: 'Noto Sans CJK SC', sans-serif;
                        font-size: 9pt;
                        color: #666;
                    }}
                }}
                
                body {{
                    font-family: 'Noto Sans CJK SC', 'WenQuanYi Zen Hei', sans-serif;
                    font-size: 11pt;
                    line-height: 1.5;
                    color: #333;
                }}
                
                .header {{
                    text-align: center;
                    margin-bottom: 2cm;
                }}
                
                .logo {{
                    font-size: 24pt;
                    font-weight: bold;
                    color: #100f0f;
                    margin-bottom: 0.5cm;
                }}
                
                h1 {{
                    font-size: 18pt;
                    color: #100f0f;
                    margin-bottom: 0.5cm;
                    border-bottom: 1px solid #ddd;
                    padding-bottom: 0.3cm;
                }}
                
                h2 {{
                    font-size: 14pt;
                    color: #333;
                    margin-top: 1cm;
                    margin-bottom: 0.3cm;
                }}
                
                .section {{
                    margin-bottom: 1cm;
                }}
                
                .client-info {{
                    background-color: #f8f9fa;
                    padding: 0.5cm;
                    border-radius: 5px;
                    margin-bottom: 1cm;
                }}
                
                .client-info p {{
                    margin: 0.2cm 0;
                }}
                
                .recommendations {{
                    margin-top: 0.5cm;
                }}
                
                .recommendation-item {{
                    margin-bottom: 0.3cm;
                    padding-left: 0.5cm;
                    border-left: 3px solid #100f0f;
                }}
                
                .automation-item {{
                    margin-bottom: 0.3cm;
                    padding-left: 0.5cm;
                    border-left: 3px solid #555;
                }}
                
                .footer {{
                    margin-top: 2cm;
                    text-align: center;
                    font-size: 9pt;
                    color: #666;
                }}
                
                .disclaimer {{
                    font-size: 8pt;
                    color: #999;
                    margin-top: 0.5cm;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="logo">RALPH</div>
                <p>Real Estate Business Analysis</p>
                <p>Generated on {datetime.now().strftime("%B %d, %Y")}</p>
            </div>
            
            <div class="client-info">
                <h2>Client Information</h2>
                <p><strong>Name:</strong> {user_name}</p>
                <p><strong>Profile:</strong> {profile_title}</p>
                <p><strong>Analysis Date:</strong> {datetime.now().strftime("%B %d, %Y")}</p>
            </div>
            
            <div class="section">
                <h1>Business Analysis</h1>
                <p>This analysis is based on our conversation and provides insights into your real estate business operations, challenges, and opportunities for growth.</p>
            </div>
            
            <div class="section">
                <h2>Key Business Strengths</h2>
                <p>Based on our conversation, we've identified these key strengths in your business:</p>
                <ul>
                    <li>Personal approach to client relationships</li>
                    <li>Deep knowledge of your local market</li>
                    <li>Commitment to professional development</li>
                </ul>
            </div>
            
            <div class="section">
                <h2>Areas for Improvement</h2>
                <p>We've identified these potential areas for improvement:</p>
                <ul>
                    <li>Systematizing your lead generation and follow-up processes</li>
                    <li>Leveraging technology to reduce administrative workload</li>
                    <li>Creating measurable metrics for business performance</li>
                    <li>Developing a more structured approach to time management</li>
                </ul>
            </div>
            
            <div class="section">
                <h2>Actionable Recommendations</h2>
                <p>Based on your specific situation, here are our top recommendations:</p>
                <div class="recommendations">
        """
        
        # Adiciona as recomendações personalizadas
        for i, rec in enumerate(recommendations, 1):
            html_content += f"""
                    <div class="recommendation-item">
                        <p><strong>Recommendation {i}:</strong> {rec}</p>
                    </div>
            """
        
        html_content += """
                </div>
            </div>
            
            <div class="section">
                <h2>Automation Opportunities</h2>
                <p>These areas of your business could benefit from intelligent automation:</p>
                <div class="recommendations">
        """
        
        # Adiciona as sugestões de automação
        for i, auto in enumerate(automation_suggestions, 1):
            html_content += f"""
                    <div class="automation-item">
                        <p><strong>Opportunity {i}:</strong> {auto}</p>
                    </div>
            """
        
        html_content += """
                </div>
            </div>
            
            <div class="section">
                <h2>Potential ROI</h2>
                <p>Implementing these recommendations could result in:</p>
                <ul>
                    <li>20-30% reduction in administrative time</li>
                    <li>15-25% increase in lead conversion rates</li>
                    <li>Improved client satisfaction and referral rates</li>
                    <li>Better work-life balance and reduced stress</li>
                </ul>
            </div>
            
            <div class="footer">
                <p>Ralph Business Analysis | Confidential</p>
                <p class="disclaimer">This analysis is based on the information provided during our conversation and is intended as general business advice. Results may vary based on implementation and market conditions.</p>
            </div>
        </body>
        </html>
        """
        
        # Configura fontes para suporte a CJK
        font_config = FontConfiguration()
        
        # Gera o PDF
        HTML(string=html_content).write_pdf(
            pdf_path,
            font_config=font_config
        )
        
        print(f"PDF gerado com sucesso: {pdf_path}")
        return pdf_path, pdf_filename
        
    except Exception as e:
        print(f"Erro ao gerar PDF: {e}")
        import traceback
        traceback.print_exc()
        return None, None

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

@app.route("/reports/<path:filename>")
def serve_report(filename):
    """Serve os relatórios PDF gerados."""
    return send_from_directory(PDF_FOLDER, filename)

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

        # --- Formatar e Salvar Conversa (para email) --- 
        print("DEBUG: Formatando conversa para email...")
        # Usa o mesmo limite de mensagens para o email
        conversation_text_for_email = format_conversation_to_text(chat_history, user_name, profile, max_messages=15)
        print(f"DEBUG: Texto da conversa para email criado ({len(conversation_text_for_email)} caracteres)")
        
        conversation_filepath = save_conversation_to_file(conversation_text_for_email)
        print(f"DEBUG: Arquivo para email salvo em: {conversation_filepath}")

        # --- Sempre tenta a API primeiro, independente do tamanho do histórico ---
        print("DEBUG: Iniciando análise IA via API...")
        use_fallback = False
        pdf_path = None
        pdf_filename = None
        
        if not client:
            ai_analysis_text = "AI analysis unavailable - DeepSeek API not configured properly."
            print("WARN: Cliente DeepSeek não configurado")
            use_fallback = True
        else:
            # Tenta gerar análise via API
            try:
                # Passa chat_history, profile e user_name para a função
                ai_analysis_text = generate_deepseek_analysis(chat_history, profile, user_name)
                print(f"DEBUG: Análise gerada via API ({len(ai_analysis_text)} caracteres)")
                
                # Verifica se a análise foi gerada com sucesso ou se houve erro
                if not ai_analysis_text or "Error generating AI analysis:" in ai_analysis_text:
                    print(f"WARN: Falha na análise via API. Detalhes: {ai_analysis_text}")
                    use_fallback = True
            except Exception as api_error:
                print(f"ERROR: Falha ao chamar API: {api_error}")
                ai_analysis_text = f"Error generating analysis: {str(api_error)}"
                use_fallback = True

        # --- Usa fallback apenas se a API falhar ---
        if use_fallback:
            print("DEBUG: Usando fallback com geração de PDF...")
            pdf_path, pdf_filename = generate_pdf_report(chat_history, profile, user_name)
            
            if pdf_path and pdf_filename:
                # Cria URL para o PDF
                pdf_url = f"/reports/{pdf_filename}"
                server_url = request.host_url.rstrip('/')
                full_pdf_url = f"{server_url}{pdf_url}"
                
                # Atualiza a mensagem de análise para incluir o link do PDF
                ai_analysis_text = f"""
                We've prepared a comprehensive business analysis report for you.

                Your personalized report is ready to view or download at the link below:
                
                {full_pdf_url}
                
                This report includes:
                • Analysis of your business strengths and challenges
                • Specific recommendations tailored to your situation
                • Automation opportunities to improve efficiency
                • Potential ROI from implementing our suggestions
                
                The report is formatted as a professional PDF document for easy sharing and reference.
                """
                print(f"DEBUG: PDF gerado com sucesso: {pdf_path}")
            else:
                # Se falhar a geração do PDF, usa uma mensagem genérica
                ai_analysis_text = """
                We've analyzed your business based on our conversation and identified several opportunities for improvement:

                1. Implement a structured follow-up system for leads and clients
                2. Leverage technology to automate repetitive administrative tasks
                3. Develop clear metrics to track your business performance
                4. Create standardized processes for common workflows
                5. Consider digital tools to enhance your client communication

                These changes could result in significant time savings and increased revenue through better conversion rates and client retention.
                
                For a more detailed analysis, please try again or contact support.
                """
                print("WARN: Falha na geração do PDF, usando texto genérico")

        # --- Enviar Email (em background, não bloqueia resposta) --- 
        try:
            email_subject = f"Ralph Analysis - {user_name} ({profile})"
            # Usa o texto formatado para o corpo do email, não a análise bruta
            email_body = f"New analysis completed for {user_name} ({profile}).\n\nConversation log attached.\n\n--- Generated Analysis ---\n{ai_analysis_text}"
            
            # Anexa o PDF se disponível, caso contrário anexa o arquivo de conversa
            attachment = pdf_path if pdf_path else conversation_filepath
            send_email_notification(email_subject, email_body, attachment)
        except Exception as email_error:
            print(f"WARN: Erro no envio de email (não crítico): {email_error}")

        # --- Retornar Resposta --- 
        # Retorna o resultado da análise (ou a mensagem de erro formatada)
        response_data = {
            "analysis_text": ai_analysis_text,
            "status": "success" if "Error generating AI analysis:" not in ai_analysis_text else "error",
            "pdf_url": f"/reports/{pdf_filename}" if pdf_filename else None
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

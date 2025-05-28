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
from fpdf import FPDF

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
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "simploai.ofc@gmail.com") # Email padrão do Simplo
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

def generate_deepseek_analysis(chat_history, profile, user_name="User", for_pdf=False):
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

    # Prompt diferente dependendo se é para PDF ou não
    if for_pdf:
        prompt = f"""Based on the conversation with a {context} named {user_name}, create a comprehensive business analysis report with the following sections:

1. EXECUTIVE SUMMARY: Brief overview of the business situation and key findings (100-150 words)

2. BUSINESS STRENGTHS: Identify 3-5 key strengths of the business based on the conversation (150-200 words)

3. AREAS FOR IMPROVEMENT: Identify 3-5 specific areas where the business could improve (150-200 words)

4. ACTIONABLE RECOMMENDATIONS: Provide 5-7 specific, actionable recommendations that address the areas for improvement (250-300 words)

5. AUTOMATION OPPORTUNITIES: Suggest 3-5 specific processes that could be automated to improve efficiency (without mentioning specific AI tools by name, but implying how modern technology could help) (150-200 words)

6. POTENTIAL ROI: Explain the potential return on investment from implementing these recommendations, with specific metrics where possible (100-150 words)

Format each section with clear headings. Keep the tone professional yet conversational, as if you're their personal business consultant. The total report should be around 1000 words.

Conversation Data:
{conversation_text}

Analysis Report:"""
    else:
        # Prompt mais conciso para resposta direta no chat
        prompt = f"""Based on the conversation with a {context} named {user_name}, provide a brief business analysis summary covering:
1. Key business strengths identified
2. Main areas for improvement
3. 2-3 actionable recommendations

Keep professional yet conversational. Max 250 words. End by mentioning that a detailed PDF report will be sent to their email.

Conversation Data:
{conversation_text}

Analysis:"""
    # ---------------------------------------------------------

    try:
        print(f"\n--- Enviando requisição para DeepSeek API com prompt {'para PDF' if for_pdf else 'padrão'} ---")
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
            max_tokens=3000 if for_pdf else 1000,  # Mais tokens para o PDF
            temperature=0.7,
            timeout=45 if for_pdf else 30,  # Timeout maior para o PDF
        )

        print("--- Resposta da DeepSeek API recebida ---")

        ai_analysis_text = response.choices[0].message.content.strip()

        if not ai_analysis_text:
            # Se a resposta ainda vier vazia, pode ser outro problema (ex: API key, fundos, filtro de conteúdo)
            return "Analysis could not be generated. Empty response received from API."

        # Adiciona assinatura do Ralph apenas para a versão não-PDF
        if not for_pdf:
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

class RalphPDF(FPDF):
    """Classe personalizada para criar PDFs profissionais."""
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)
        self.add_page()
        self.set_font("Helvetica", size=11)
        
    def header(self):
        # Logo (texto como logo)
        self.set_font("Helvetica", "B", 24)
        self.set_text_color(16, 15, 15)  # Cor escura (#100f0f)
        self.cell(0, 10, "RALPH", align="C")
        self.ln(8)
        
        # Subtítulo
        self.set_font("Helvetica", "", 12)
        self.set_text_color(80, 80, 80)
        self.cell(0, 10, "Real Estate Business Analysis", align="C")
        self.ln(5)
        
        # Data
        self.set_font("Helvetica", "", 10)
        self.cell(0, 10, f"Generated on {datetime.now().strftime('%B %d, %Y')}", align="C")
        self.ln(20)
        
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")
        
    def chapter_title(self, title):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(16, 15, 15)
        self.cell(0, 10, title, ln=True)
        self.ln(4)
        
    def chapter_body(self, body):
        self.set_font("Helvetica", "", 11)
        self.set_text_color(0, 0, 0)
        
        # Divide o texto em parágrafos
        paragraphs = body.split('\n')
        for paragraph in paragraphs:
            if paragraph.strip():
                self.multi_cell(0, 5, paragraph)
                self.ln(3)
        self.ln(5)
        
    def add_info_box(self, title, content):
        # Salva a posição atual
        x, y = self.get_x(), self.get_y()
        
        # Desenha o fundo do box
        self.set_fill_color(248, 249, 250)  # Cor de fundo cinza claro
        self.rect(x, y, 190, 30, style="F")
        
        # Adiciona o título
        self.set_xy(x + 5, y + 5)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(16, 15, 15)
        self.cell(0, 5, title, ln=True)
        
        # Adiciona o conteúdo
        self.set_xy(x + 5, y + 12)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(0, 0, 0)
        self.multi_cell(180, 5, content)
        
        # Restaura a posição após o box (com espaço adicional)
        self.set_y(y + 35)

def generate_pdf_report_with_ai_content(chat_history, profile, user_name="User"):
    """Gera um relatório PDF profissional com conteúdo gerado pela IA."""
    try:
        # Gera o conteúdo do relatório usando a API da IA
        print("DEBUG: Gerando conteúdo do PDF via API...")
        ai_content = generate_deepseek_analysis(chat_history, profile, user_name, for_pdf=True)
        
        if "Error generating AI analysis:" in ai_content:
            print(f"WARN: Erro ao gerar conteúdo do PDF via API: {ai_content}")
            return None, None
            
        # Define o nome do arquivo PDF
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_filename = f"ralph_analysis_{user_name.lower().replace(' ', '_')}_{timestamp}.pdf"
        pdf_path = os.path.join(PDF_FOLDER, pdf_filename)
        
        # Cria o PDF
        pdf = RalphPDF()
        
        # Adiciona informações do cliente
        profile_title = {
            'individual': 'Independent Real Estate Agent',
            'employee': 'Real Estate Company Employee',
            'owner': 'Real Estate Business Owner'
        }.get(profile, 'Real Estate Professional')
        
        pdf.add_info_box("Client Information", 
                        f"Name: {user_name}\nProfile: {profile_title}\nAnalysis Date: {datetime.now().strftime('%B %d, %Y')}")
        
        # Processa o conteúdo da IA para extrair seções
        sections = {}
        current_section = None
        section_content = []
        
        # Divide o conteúdo em linhas
        lines = ai_content.split('\n')
        
        # Identifica seções pelo formato (cabeçalhos em maiúsculas ou com números)
        section_patterns = [
            r'^EXECUTIVE\s+SUMMARY',
            r'^BUSINESS\s+STRENGTHS',
            r'^AREAS\s+FOR\s+IMPROVEMENT',
            r'^ACTIONABLE\s+RECOMMENDATIONS',
            r'^AUTOMATION\s+OPPORTUNITIES',
            r'^POTENTIAL\s+ROI',
            r'^1\.\s+EXECUTIVE',
            r'^2\.\s+BUSINESS',
            r'^3\.\s+AREAS',
            r'^4\.\s+ACTIONABLE',
            r'^5\.\s+AUTOMATION',
            r'^6\.\s+POTENTIAL'
        ]
        
        # Combina os padrões em uma expressão regular
        section_pattern = '|'.join(section_patterns)
        
        for line in lines:
            # Verifica se a linha é um cabeçalho de seção
            if re.search(section_pattern, line, re.IGNORECASE):
                # Se já temos uma seção atual, salvamos seu conteúdo
                if current_section:
                    sections[current_section] = '\n'.join(section_content)
                
                # Define a nova seção atual
                current_section = line.strip()
                section_content = []
            elif current_section:
                # Adiciona a linha ao conteúdo da seção atual
                section_content.append(line)
        
        # Adiciona a última seção
        if current_section and section_content:
            sections[current_section] = '\n'.join(section_content)
        
        # Se não conseguimos extrair seções, usamos o texto completo
        if not sections:
            pdf.chapter_title("Business Analysis")
            pdf.chapter_body(ai_content)
        else:
            # Adiciona cada seção ao PDF
            for title, content in sections.items():
                pdf.chapter_title(title)
                pdf.chapter_body(content)
        
        # Adiciona disclaimer
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(150, 150, 150)
        pdf.multi_cell(0, 5, "This analysis is based on the information provided during our conversation and is intended as general business advice. Results may vary based on implementation and market conditions.")
        
        # Salva o PDF
        pdf.output(pdf_path)
        
        print(f"PDF gerado com sucesso: {pdf_path}")
        return pdf_path, pdf_filename
        
    except Exception as e:
        print(f"Erro ao gerar PDF: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def send_email_with_pdf(recipient_email, user_name, profile, pdf_path, send_copy_to_simplo=True):
    """Envia um email com o PDF anexado para o usuário e opcionalmente para o Simplo."""
    if not pdf_path or not os.path.exists(pdf_path):
        print(f"ERRO: PDF não encontrado em {pdf_path}")
        return False
        
    try:
        # Prepara o email para o usuário
        subject = f"Your Ralph Business Analysis Report"
        
        # Corpo do email para o usuário
        body = f"""Hello {user_name},

Thank you for chatting with Ralph, your Real Estate Business Analyst.

Attached is your personalized business analysis report based on our conversation. This report includes:

• Executive summary of your business situation
• Analysis of your business strengths
• Key areas for improvement
• Actionable recommendations
• Automation opportunities to improve efficiency
• Potential ROI from implementing our suggestions

We hope you find this analysis valuable for your real estate business.

Best regards,
Ralph AI
Real Estate Business Consultant
"""
        
        # Envia o email para o usuário
        success = send_email_notification(
            subject=subject,
            text_body=body,
            attachment_path=pdf_path,
            recipient_email=recipient_email
        )
        
        if not success:
            print(f"ERRO: Falha ao enviar email para {recipient_email}")
            return False
            
        # Envia uma cópia para o Simplo, se solicitado
        if send_copy_to_simplo and EMAIL_RECEIVER:
            # Corpo do email para o Simplo
            simplo_body = f"""New Ralph Analysis Report

User: {user_name}
Profile: {profile}
Email: {recipient_email}
Date: {datetime.now().strftime('%B %d, %Y')}

The user's analysis report is attached.
"""
            
            # Envia o email para o Simplo
            send_email_notification(
                subject=f"[COPY] Ralph Analysis - {user_name} ({profile})",
                text_body=simplo_body,
                attachment_path=pdf_path,
                recipient_email=EMAIL_RECEIVER
            )
            
        return True
        
    except Exception as e:
        print(f"Erro ao enviar email com PDF: {e}")
        return False

def send_email_notification(subject, text_body, attachment_path=None, recipient_email=None):
    """Envia um email com anexo opcional."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("Configuração de email incompleta. Pulando notificação por email.")
        return False
        
    # Se não for especificado um destinatário, usa o padrão
    if not recipient_email:
        recipient_email = EMAIL_RECEIVER
        
    if not recipient_email:
        print("Email do destinatário não especificado. Pulando notificação por email.")
        return False

    try:
        message = MIMEMultipart()
        message["From"] = EMAIL_SENDER
        message["To"] = recipient_email
        message["Subject"] = subject

        # Anexa o corpo do texto
        message.attach(MIMEText(text_body, "plain", "utf-8"))

        # Anexa o arquivo, se fornecido
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
        
        server.sendmail(EMAIL_SENDER, recipient_email, message.as_string())
        server.quit()
        
        print(f"Email enviado com sucesso para {recipient_email}")
        
        # Não remove o arquivo PDF, pois pode ser necessário para outros emails
        # Será removido automaticamente pelo sistema operacional quando o servidor for reiniciado
                
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
        user_email = data.get("userEmail")  # Novo campo para o email do usuário

        print(f"DEBUG: user_name={user_name}, profile={profile}, chat_history length={len(chat_history)}, user_email={user_email}")

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

        # --- Gera uma análise resumida para exibir no chat ---
        print("DEBUG: Gerando análise resumida para o chat...")
        chat_analysis = generate_deepseek_analysis(chat_history, profile, user_name, for_pdf=False)
        
        if "Error generating AI analysis:" in chat_analysis:
            # Se falhar, usa uma mensagem genérica
            chat_analysis = f"""
            Obrigado por conversar com Ralph, seu Analista de Negócios Imobiliários.
            
            Com base em nossa conversa, identificamos algumas oportunidades para melhorar seu negócio. 
            
            Um relatório detalhado será enviado para seu email em breve, com uma análise completa e recomendações personalizadas.
            """
            print("WARN: Falha na análise para chat, usando texto genérico")

        # --- Se o email do usuário foi fornecido, gera e envia o PDF ---
        pdf_path = None
        pdf_filename = None
        
        if user_email:
            print(f"DEBUG: Email do usuário fornecido: {user_email}. Gerando PDF...")
            
            # Gera o PDF com conteúdo da API
            pdf_path, pdf_filename = generate_pdf_report_with_ai_content(chat_history, profile, user_name)
            
            if pdf_path and pdf_filename:
                print(f"DEBUG: PDF gerado com sucesso: {pdf_path}. Enviando por email...")
                
                # Envia o PDF por email para o usuário e para o Simplo
                email_sent = send_email_with_pdf(
                    recipient_email=user_email,
                    user_name=user_name,
                    profile=profile,
                    pdf_path=pdf_path,
                    send_copy_to_simplo=True
                )
                
                if email_sent:
                    print(f"DEBUG: Email enviado com sucesso para {user_email} e para o Simplo")
                    
                    # Adiciona mensagem sobre o email enviado à análise do chat
                    chat_analysis += f"\n\nUm relatório detalhado foi enviado para {user_email}. Verifique sua caixa de entrada (e pasta de spam, se necessário)."
                else:
                    print("WARN: Falha ao enviar email com o PDF")
                    
                    # Adiciona mensagem sobre a falha no envio do email
                    chat_analysis += "\n\nHouve um problema ao enviar o relatório por email. Por favor, entre em contato com o suporte."
            else:
                print("WARN: Falha ao gerar o PDF")
                
                # Adiciona mensagem sobre a falha na geração do PDF
                chat_analysis += "\n\nHouve um problema ao gerar seu relatório detalhado. Por favor, entre em contato com o suporte."
        else:
            print("INFO: Email do usuário não fornecido. Pulando geração e envio de PDF.")
            
            # Adiciona mensagem sobre a necessidade de fornecer o email
            chat_analysis += "\n\nPara receber um relatório detalhado por email, por favor forneça seu endereço de email."

        # --- Enviar Email com a conversa para o Simplo (mesmo sem PDF) --- 
        try:
            if not user_email:  # Se não enviamos o PDF, enviamos pelo menos a conversa
                email_subject = f"Ralph Analysis - {user_name} ({profile})"
                email_body = f"New analysis completed for {user_name} ({profile}).\n\nConversation log attached.\n\n--- Generated Analysis ---\n{chat_analysis}"
                send_email_notification(
                    subject=email_subject,
                    text_body=email_body,
                    attachment_path=conversation_filepath,
                    recipient_email=EMAIL_RECEIVER
                )
        except Exception as email_error:
            print(f"WARN: Erro no envio de email (não crítico): {email_error}")

        # --- Retornar Resposta --- 
        response_data = {
            "analysis_text": chat_analysis,
            "status": "success" if "Error generating AI analysis:" not in chat_analysis else "error",
            "email_sent": user_email is not None and pdf_path is not None
        }
        
        print(f"DEBUG: Retornando análise/status: {response_data['status']}, email_sent: {response_data['email_sent']}")
        return jsonify(response_data), 200

    except Exception as e:
        print(f"ERROR CRÍTICO no endpoint /analyze: {e}")
        import traceback
        traceback.print_exc()
        
        error_response = {
            "analysis_text": f"Sorry, a critical error occurred while processing your analysis. Please try again. If the problem persists, contact support.\n\nError details: {str(e)[:200]}",
            "status": "error",
            "email_sent": False
        }
        return jsonify(error_response), 500

@app.route("/submit-email", methods=["POST"])
def submit_email():
    """Endpoint para receber o email do usuário e iniciar o processo de geração e envio do PDF."""
    print("=== DEBUG: Recebendo email do usuário ===")
    
    try:
        # Verificar se recebeu dados JSON
        if not request.is_json:
            print("ERROR: Request não é JSON")
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        if not data:
            print("ERROR: Nenhum dado JSON recebido")
            return jsonify({"error": "No data received"}), 400

        user_email = data.get("email")
        user_name = data.get("userName", "User")
        profile = data.get("profile", "unknown")
        chat_history = data.get("chatHistory", [])

        print(f"DEBUG: Recebido email={user_email}, user_name={user_name}, profile={profile}, chat_history length={len(chat_history)}")

        if not user_email:
            print("ERROR: Email não fornecido")
            return jsonify({"error": "Email is required"}), 400

        if not chat_history:
            print("ERROR: Histórico de chat vazio")
            return jsonify({"error": "Chat history is empty"}), 400

        # Inicia o processo de geração e envio do PDF em segundo plano
        # (Na prática, isso seria feito com uma tarefa assíncrona, mas para simplificar, fazemos aqui)
        
        # Gera o PDF
        pdf_path, pdf_filename = generate_pdf_report_with_ai_content(chat_history, profile, user_name)
        
        if pdf_path and pdf_filename:
            # Envia o PDF por email
            email_sent = send_email_with_pdf(
                recipient_email=user_email,
                user_name=user_name,
                profile=profile,
                pdf_path=pdf_path,
                send_copy_to_simplo=True
            )
            
            if email_sent:
                return jsonify({
                    "status": "success",
                    "message": f"Report sent to {user_email}"
                }), 200
            else:
                return jsonify({
                    "status": "error",
                    "message": "Failed to send email"
                }), 500
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to generate PDF report"
            }), 500

    except Exception as e:
        print(f"ERROR CRÍTICO no endpoint /submit-email: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            "status": "error",
            "message": f"An unexpected error occurred: {str(e)[:200]}"
        }), 500

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

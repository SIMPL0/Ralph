import os
import smtplib
import json
import random
import re
import html
import uuid # Para nomes de arquivo únicos
import tempfile
import threading # Importa o módulo de threading
from datetime import datetime
from openai import OpenAI # Importa OpenAI corretamente para SDK v1+
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication # Para anexar arquivos
from flask import Flask, request, jsonify, send_from_directory, send_file, current_app # Importa current_app
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
# Configuração de CORS para permitir qualquer origem (mantém para flexibilidade)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Configuração de Variáveis de Ambiente ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "simploai.ofc@gmail.com")
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

Keep professional yet conversational. Max 250 words. End by mentioning that a detailed PDF report will be sent to their email with the following exact text: "To receive your detailed PDF report, please enter your email address below."

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
            timeout=60 if for_pdf else 45,  # Aumenta ligeiramente os timeouts para dar mais margem
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
                # Usa html.unescape para decodificar entidades HTML antes de adicionar ao PDF
                decoded_paragraph = html.unescape(paragraph)
                self.multi_cell(0, 5, decoded_paragraph)
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
            return None, None, ai_content # Retorna o erro também

        # Define o nome do arquivo PDF
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_user_name = re.sub(r'\W+', '', user_name.lower().replace(' ', '_')) # Limpa nome para filename
        pdf_filename = f"ralph_analysis_{safe_user_name}_{timestamp}.pdf"
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
            match = re.search(section_pattern, line, re.IGNORECASE)
            if match:
                # Se já temos uma seção atual, salvamos seu conteúdo
                if current_section:
                    sections[current_section] = '\n'.join(section_content).strip()

                # Define a nova seção atual - usa o texto original da linha como título
                current_section = line.strip()
                # Remove prefixos numéricos (e.g., "1. ") para limpeza
                current_section = re.sub(r'^\d+\.\s*', '', current_section)
                section_content = []
            elif current_section:
                # Adiciona a linha ao conteúdo da seção atual
                section_content.append(line)

        # Adiciona a última seção
        if current_section and section_content:
            sections[current_section] = '\n'.join(section_content).strip()

        # Se não conseguimos extrair seções, usamos o texto completo
        if not sections:
            print("WARN: Não foi possível extrair seções do conteúdo da IA. Usando texto completo.")
            pdf.chapter_title("Business Analysis")
            pdf.chapter_body(ai_content)
        else:
            # Adiciona cada seção extraída
            print(f"DEBUG: Seções extraídas para o PDF: {list(sections.keys())}")
            for title, body in sections.items():
                pdf.chapter_title(title)
                pdf.chapter_body(body)

        # Salva o PDF
        pdf.output(pdf_path)
        print(f"DEBUG: PDF gerado com sucesso em: {pdf_path}")
        return pdf_path, pdf_filename, None # Retorna None para o erro

    except Exception as e:
        print(f"Erro CRÍTICO ao gerar PDF: {e}")
        import traceback
        traceback.print_exc() # Imprime traceback completo para depuração
        return None, None, f"Failed to generate PDF report due to an internal error: {e}"

def send_email_with_attachment(recipient_email, subject, body, attachment_path=None, attachment_filename=None):
    """Envia um email com um anexo opcional."""
    if not EMAIL_PASSWORD:
        print("ERRO: Senha do email não configurada. Não é possível enviar emails.")
        return False, "Email password not configured."

    message = MIMEMultipart()
    message['From'] = EMAIL_SENDER
    message['To'] = recipient_email
    message['Subject'] = subject

    message.attach(MIMEText(body, 'plain'))

    if attachment_path and attachment_filename and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as attachment:
                part = MIMEApplication(attachment.read(), Name=attachment_filename)
            part['Content-Disposition'] = f'attachment; filename="{attachment_filename}"'
            message.attach(part)
            print(f"DEBUG: Anexo {attachment_filename} adicionado ao email.")
        except Exception as e:
            print(f"Erro ao anexar arquivo {attachment_filename}: {e}")
            return False, f"Failed to attach file: {e}"
    elif attachment_path:
        print(f"WARN: Caminho do anexo fornecido ({attachment_path}), mas arquivo não encontrado ou nome não fornecido.")

    try:
        print(f"DEBUG: Conectando ao servidor SMTP {SMTP_SERVER}:{SMTP_PORT}...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls() # Inicia conexão segura
        print(f"DEBUG: Fazendo login como {EMAIL_SENDER}...")
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        print(f"DEBUG: Enviando email para {recipient_email}...")
        server.sendmail(EMAIL_SENDER, recipient_email, message.as_string())
        server.quit()
        print(f"Email enviado com sucesso para {recipient_email}")
        return True, "Email sent successfully."
    except smtplib.SMTPAuthenticationError as e:
        print(f"Erro de autenticação SMTP: {e}. Verifique EMAIL_SENDER e EMAIL_PASSWORD.")
        return False, f"SMTP Authentication Error: {e}. Check credentials."
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        import traceback
        traceback.print_exc()
        return False, f"Failed to send email: {e}"

# --- NOVA FUNÇÃO PARA PROCESSAMENTO ASSÍNCRONO --- 
def process_pdf_and_send_email_async(app_context, user_email, chat_history, profile, user_name):
    """Função executada em uma thread separada para gerar PDF e enviar email."""
    with app_context: # Usa o contexto da aplicação Flask na thread
        print(f"THREAD: Iniciando geração de PDF e envio para {user_email}")
        pdf_path, pdf_filename, pdf_error = None, None, None
        email_sent_to_user = False
        email_error = None

        try:
            # 1. Gerar PDF com conteúdo da IA
            pdf_path, pdf_filename, pdf_error = generate_pdf_report_with_ai_content(chat_history, profile, user_name)

            if pdf_path and pdf_filename:
                # 2. Enviar email para o usuário com o PDF
                email_subject = f"Your Ralph AI Business Analysis for {user_name}"
                email_body = f"Hello {user_name},\n\nThank you for using Ralph AI!\n\nPlease find attached your personalized business analysis report.\n\nWe hope this provides valuable insights for your real estate business.\n\nBest regards,\nThe Ralph AI Team"
                email_sent_to_user, email_error = send_email_with_attachment(user_email, email_subject, email_body, pdf_path, pdf_filename)

                if email_sent_to_user:
                    print(f"THREAD: Email com PDF enviado com sucesso para {user_email}.")
                else:
                    print(f"THREAD: Falha ao enviar email com PDF para {user_email}. Erro: {email_error}")

                # 3. Limpar o arquivo PDF após o envio (ou tentativa)
                try:
                    os.remove(pdf_path)
                    print(f"THREAD: Arquivo PDF temporário removido: {pdf_path}")
                except Exception as e:
                    print(f"THREAD: Erro ao remover arquivo PDF temporário {pdf_path}: {e}")
            else:
                print(f"THREAD: Geração do PDF falhou para {user_email}. Erro: {pdf_error}")
                # Opcional: Enviar email de erro para o admin/simploai?

        except Exception as e:
            print(f"THREAD: Erro inesperado no processamento assíncrono para {user_email}: {e}")
            import traceback
            traceback.print_exc()
            # Opcional: Enviar notificação de erro

        print(f"THREAD: Processamento assíncrono concluído para {user_email}.")
# ---------------------------------------------------

# --- Rota Principal (Frontend) --- 
@app.route('/')
def index():
    # Esta rota agora serve o index.html da pasta raiz (um nível acima de src)
    # Ajuste o caminho se sua estrutura for diferente
    # return send_from_directory(PROJECT_ROOT, 'index.html')
    # Comentado acima pois o frontend está no GitHub Pages. 
    # Esta rota pode retornar um status ou uma página de "API ativa".
    return jsonify({"status": "API is running", "message": "Welcome to Ralph AI Backend"}), 200
# --------------------------------

# --- Rota de Análise (Síncrona) --- 
@app.route('/analyze', methods=['POST', 'OPTIONS'])
def analyze_chat():
    if request.method == 'OPTIONS':
        # Trata a requisição preflight do CORS
        return _build_cors_preflight_response()

    print("\n=== DEBUG: Recebendo requisição de análise ===")
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    user_name = data.get('user_name', 'User')
    profile = data.get('profile')
    chat_history = data.get('chat_history')
    email = data.get('email') # Recebe o email se já foi fornecido

    print(f"DEBUG: Recebido user_name={user_name}, profile={profile}, chat_history length={len(chat_history) if chat_history else 0}, email={email}")

    if not profile or not chat_history:
        return jsonify({"error": "Missing profile or chat_history"}), 400

    # --- Geração da Análise (Síncrona) ---
    print("DEBUG: Gerando análise via API...")
    ai_analysis = generate_deepseek_analysis(chat_history, profile, user_name, for_pdf=False)
    # --------------------------------------

    # --- Salvar Conversa e Enviar Email para SimploAI (Opcional, Síncrono) ---
    conversation_text = format_conversation_to_text(chat_history, user_name, profile)
    conversation_filepath = save_conversation_to_file(conversation_text)

    if conversation_filepath:
        try:
            subject = f"Nova Análise Ralph AI - {user_name} ({profile})"
            body = f"Uma nova análise foi concluída para {user_name} (Perfil: {profile}).\n\nVeja a conversa completa no anexo."
            send_email_with_attachment(EMAIL_RECEIVER, subject, body, conversation_filepath, os.path.basename(conversation_filepath))
            print(f"Email de notificação interna enviado com sucesso para {EMAIL_RECEIVER}")
            # Limpar arquivo de conversa após envio
            try:
                os.remove(conversation_filepath)
            except Exception as e:
                print(f"Erro ao remover arquivo de conversa {conversation_filepath}: {e}")
        except Exception as e:
            print(f"Erro ao enviar email de notificação interna: {e}")
    # --------------------------------------------------------------------------

    # Verifica se a análise da IA retornou um erro
    analysis_error = None
    if "Error generating AI analysis:" in ai_analysis:
        analysis_error = ai_analysis
        ai_analysis = "I encountered an issue while generating the analysis. Please try again later or contact support." # Mensagem genérica para o usuário

    # Determina se precisa pedir o email
    need_email = not bool(email) and not analysis_error # Só pede email se não houver erro e email não foi dado

    response_data = {
        "analysis": ai_analysis,
        "status": "error" if analysis_error else "success",
        "need_email": need_email,
        "error_message": analysis_error # Inclui a mensagem de erro detalhada (para debug ou log)
    }

    print(f"DEBUG: Retornando análise/status: {response_data['status']}, need_email: {need_email}")
    return jsonify(response_data), 200
# -------------------------------------

# --- Rota de Submissão de Email (AGORA ASSÍNCRONA) --- 
@app.route('/submit-email', methods=['POST', 'OPTIONS'])
def submit_email():
    if request.method == 'OPTIONS':
        # Trata a requisição preflight do CORS
        return _build_cors_preflight_response()

    print("\n=== DEBUG: Recebendo email do usuário (Iniciando Processo Assíncrono) ===")
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    user_email = data.get('email')
    user_name = data.get('user_name')
    profile = data.get('profile')
    chat_history = data.get('chat_history')

    print(f"DEBUG: Recebido email={user_email}, user_name={user_name}, profile={profile}, chat_history length={len(chat_history) if chat_history else 0}")

    if not all([user_email, user_name, profile, chat_history]):
        return jsonify({"error": "Missing required data (email, user_name, profile, chat_history)"}), 400

    # --- INICIA A THREAD PARA PROCESSAMENTO EM SEGUNDO PLANO --- 
    # Passa o contexto da aplicação atual para a thread
    thread = threading.Thread(target=process_pdf_and_send_email_async,
                              args=(current_app.app_context(), user_email, chat_history, profile, user_name))
    thread.daemon = True # Permite que a aplicação saia mesmo se a thread ainda estiver rodando
    thread.start()
    # -----------------------------------------------------------

    # --- Resposta Imediata para o Frontend --- 
    print("DEBUG: Retornando resposta imediata ao frontend. PDF/Email sendo processado em background.")
    return jsonify({
        "status": "processing",
        "message": "Thank you! Your detailed PDF report is being generated and will be emailed to you shortly."
    }), 200 # Retorna 200 OK imediatamente
# -------------------------------------------------------

# --- Função auxiliar para CORS Preflight --- 
def _build_cors_preflight_response():
    response = jsonify(success=True)
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response
# -------------------------------------------

if __name__ == '__main__':
    # Obtém a porta do Render ou usa 5000 como padrão para desenvolvimento local
    port = int(os.environ.get('PORT', 5000))
    # Roda em 0.0.0.0 para ser acessível externamente (necessário para Render)
    app.run(host='0.0.0.0', port=port, debug=False) # Debug=False para produção


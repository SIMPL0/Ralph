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
# Configuração de CORS para permitir qualquer origem
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

    # <<< NEW PROMPTS START >>>
    if for_pdf:
        prompt = f"""Based on the conversation with a {context} named {user_name}, create an ULTRA-DETAILED business analysis report with these sections:

1. EXECUTIVE SUMMARY (200-250 words)
   - Comprehensive overview of current business status
   - Key findings from the analysis
   - Immediate opportunities identified

2. BUSINESS STRENGTHS (300-400 words)
   - 5-7 core strengths with specific examples
   - Competitive advantages to leverage
   - Unique value propositions

3. IMPROVEMENT AREAS (400-500 words)
   - 5-7 specific weaknesses with root cause analysis
   - Process bottlenecks identified
   - Revenue leakage points

4. ACTION PLAN (500-600 words)
   - Step-by-step 30/60/90 day implementation guide
   - Specific tasks with assigned priorities (High/Medium/Low)
   - Required resources for each action
   - Expected outcomes and KPIs

5. AUTOMATION ROADMAP (300-400 words)
   - 5-7 processes ripe for automation
   - Implementation sequence recommendation
   - Expected efficiency gains for each

6. ROI PROJECTIONS (200-300 words)
   - Financial impact projections
   - Time investment vs expected return
   - Key metrics to track

Format with professional headings and bullet points. Include concrete examples from the conversation. The total report should be 2000+ words of highly specific, actionable advice."""

    else: # Summary prompt
        prompt = f"""Provide a concise 250-word preview analysis for {user_name} covering:
1. 3 key strengths
2. 3 main improvement areas
3. 2 high-priority recommendations

IMPORTANT: Clearly state this is just a preview and the detailed PDF report will be available for download immediately after this summary.

Keep tone professional but conversational. Do NOT mention specific tools - focus on processes.

Conversation Data:
{conversation_text}"""
    # <<< NEW PROMPTS END >>>
    # ---------------------------------------------------------

    try:
        print(f"\n--- Enviando requisição para DeepSeek API com prompt {'para PDF' if for_pdf else 'de sumário'} ---")
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
            max_tokens=4000 if for_pdf else 1000,  # Mais tokens para o PDF (aumentado para 2000+ palavras)
            temperature=0.7,
            timeout=120 if for_pdf else 60,  # Timeout maior para o PDF (aumentado)
        )

        print("--- Resposta da DeepSeek API recebida ---")

        ai_analysis_text = response.choices[0].message.content.strip()

        if not ai_analysis_text:
            # Se a resposta ainda vier vazia, pode ser outro problema (ex: API key, fundos, filtro de conteúdo)
            return "Analysis could not be generated. Empty response received from API."

        # Adiciona assinatura do Ralph apenas para a versão não-PDF (sumário)
        if not for_pdf:
             # Não adiciona mais a assinatura aqui, o prompt já instrui a IA
             pass # ai_analysis_text += "\n\n---\nAnalysis generated by Ralph AI\nReal Estate Business Consultant"

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
        self.set_font("Helvetica", size=11) # Use Helvetica as fallback

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
        # Remove potential numbering like "1. " from title before printing
        clean_title = re.sub(r"^\d+\.\s*", "", title).strip()
        self.cell(0, 10, clean_title.upper(), ln=True) # Use UPPERCASE for titles
        self.ln(4)

    def chapter_body(self, body):
        self.set_font("Helvetica", "", 11)
        self.set_text_color(0, 0, 0)

        # Processa o texto para lidar com markdown básico (negrito, listas)
        lines = body.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                self.ln(3) # Espaço entre parágrafos
                continue

            # Detecta itens de lista (-, *, ou número seguido de ponto)
            list_match = re.match(r"^\s*[-*]\s+(.*)", line)
            numbered_list_match = re.match(r"^\s*\d+\.\s+(.*)", line)

            if list_match:
                self.set_x(15) # Indentação para item de lista
                self.multi_cell(0, 5, f"• {list_match.group(1).strip()}")
                self.set_x(10) # Volta para margem padrão
                self.ln(1) # Espaçamento menor após item de lista
            elif numbered_list_match:
                 self.set_x(15) # Indentação para item de lista numerada
                 # Mantém a numeração original
                 self.multi_cell(0, 5, f"{line.strip()}")
                 self.set_x(10) # Volta para margem padrão
                 self.ln(1)
            else:
                # Parágrafo normal
                # Tenta detectar negrito (**texto**) - FPDF não suporta nativamente
                # Apenas escreve o texto normal por enquanto
                self.multi_cell(0, 5, line)
                self.ln(2) # Espaçamento após parágrafo normal

        self.ln(5) # Espaço extra após o corpo do capítulo

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
        # Gera o conteúdo do relatório usando a API da IA (prompt detalhado)
        print("DEBUG: Gerando conteúdo DETALHADO do PDF via API...")
        ai_content = generate_deepseek_analysis(chat_history, profile, user_name, for_pdf=True)

        if "Error generating AI analysis:" in ai_content or "Analysis could not be generated" in ai_content:
            print(f"WARN: Erro ao gerar conteúdo do PDF via API: {ai_content}")
            # Retorna o erro para ser tratado no endpoint
            raise ValueError(f"Failed to generate PDF content from AI: {ai_content}")

        # Define o nome do arquivo PDF
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_user_name = re.sub(r'[^a-zA-Z0-9_]', '_', user_name.lower()) # Sanitize username
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
        current_section_title = None
        section_content = []

        # Divide o conteúdo em linhas
        lines = ai_content.split('\n')

        # Padrões para identificar cabeçalhos de seção (mais robustos)
        section_patterns = [
            r'^\s*1\.\s*EXECUTIVE SUMMARY\s*$',
            r'^\s*2\.\s*BUSINESS STRENGTHS\s*$',
            r'^\s*3\.\s*IMPROVEMENT AREAS\s*$',
            r'^\s*4\.\s*ACTION PLAN\s*$',
            r'^\s*5\.\s*AUTOMATION ROADMAP\s*$',
            r'^\s*6\.\s*ROI PROJECTIONS\s*$',
            # Fallback para títulos sem número ou em maiúsculas
            r'^\s*EXECUTIVE SUMMARY\s*$',
            r'^\s*BUSINESS STRENGTHS\s*$',
            r'^\s*IMPROVEMENT AREAS\s*$',
            r'^\s*ACTION PLAN\s*$',
            r'^\s*AUTOMATION ROADMAP\s*$',
            r'^\s*ROI PROJECTIONS\s*$'
        ]
        section_regex = re.compile('|'.join(f'({p})' for p in section_patterns), re.IGNORECASE)

        for line in lines:
            match = section_regex.match(line)
            if match:
                # Salva a seção anterior
                if current_section_title:
                    sections[current_section_title] = '\n'.join(section_content).strip()

                # Inicia nova seção
                # Pega o título que correspondeu (remove None dos grupos não correspondentes)
                current_section_title = next(g for g in match.groups() if g is not None).strip()
                section_content = []
                print(f"DEBUG: Found section: {current_section_title}") # Debug
            elif current_section_title:
                # Adiciona linha ao conteúdo da seção atual
                section_content.append(line)

        # Adiciona a última seção
        if current_section_title:
            sections[current_section_title] = '\n'.join(section_content).strip()

        # Adiciona seções ao PDF
        if not sections:
            print("WARN: Não foi possível extrair seções do conteúdo da IA. Adicionando como texto único.")
            pdf.chapter_title("Business Analysis Report")
            pdf.chapter_body(ai_content) # Usa a função chapter_body que lida com parágrafos
        else:
            # Ordem definida das seções (baseada nos novos prompts)
            ordered_sections = [
                "EXECUTIVE SUMMARY", "BUSINESS STRENGTHS", "IMPROVEMENT AREAS",
                "ACTION PLAN", "AUTOMATION ROADMAP", "ROI PROJECTIONS"
            ]
            for title_key in ordered_sections:
                 # Encontra a chave correspondente em 'sections' (ignorando caso e número)
                 found_title = None
                 for section_title in sections.keys():
                     # Limpa o título da seção (remove número, espaços, caixa alta)
                     clean_section_title = re.sub(r"^\d+\.\s*", "", section_title).strip().upper()
                     if clean_section_title == title_key:
                         found_title = section_title
                         break

                 if found_title and sections[found_title]:
                     print(f"DEBUG: Adding section to PDF: {found_title}") # Debug
                     pdf.chapter_title(found_title) # Usa o título original encontrado
                     pdf.chapter_body(sections[found_title])
                 else:
                     print(f"WARN: Section '{title_key}' not found or empty in AI content.")


        # Salva o PDF
        pdf.output(pdf_path)
        print(f"DEBUG: PDF gerado e salvo em: {pdf_path}")
        return pdf_path, pdf_filename

    except ValueError as ve: # Captura erro específico da geração de conteúdo
        print(f"ERROR: {ve}")
        return None, None
    except Exception as e:
        print(f"Erro CRÍTICO ao gerar PDF: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def send_email_notification(subject, text_body, recipient_email, attachment_path=None):
    """Função genérica para enviar emails com ou sem anexo."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("WARN: Credenciais de email não configuradas. Pulando envio.")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = recipient_email
        msg['Subject'] = subject

        # Adiciona o corpo do email
        msg.attach(MIMEText(text_body, 'plain'))

        # Adiciona anexo, se fornecido
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as file:
                attachment = MIMEApplication(file.read(), Name=os.path.basename(attachment_path))
                attachment['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
                msg.attach(attachment)
        elif attachment_path:
             print(f"WARN: Attachment path provided but file not found: {attachment_path}")


        # Conecta ao servidor SMTP e envia
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)

        print(f"Email enviado com sucesso para {recipient_email}")
        return True

    except Exception as e:
        print(f"Erro ao enviar email para {recipient_email}: {e}")
        return False

# <<< REMOVED send_email_with_pdf function as it's now handled by send_email_notification >>>
# (The logic is now within /generate-pdf endpoint)

# <<< NEW /analyze endpoint >>>
@app.route("/analyze", methods=["POST"])
def analyze_chat():
    """Endpoint para analisar o histórico de chat e gerar um SUMÁRIO."""
    print("=== DEBUG: Recebendo requisição de análise (sumário) ===")

    try:
        # Verificar se recebeu dados JSON
        if not request.is_json:
            print("ERROR: Request não é JSON")
            return jsonify({"error": "Request must be JSON"}), 400

        data = request.get_json()
        if not data:
            print("ERROR: Nenhum dado JSON recebido")
            return jsonify({"error": "No data received"}), 400

        # Extrair dados do request
        chat_history = data.get("chatHistory", [])
        user_name = data.get("userName", "User")
        profile = data.get("profile", "unknown")

        print(f"DEBUG: Recebido user_name={user_name}, profile={profile}, chat_history length={len(chat_history)}")

        if not chat_history:
            print("ERROR: Histórico de chat vazio")
            return jsonify({"error": "Chat history is empty"}), 400

        # --- Gerar análise de SUMÁRIO usando a API da IA ---
        print("DEBUG: Gerando análise de sumário via API...")
        # Chama generate_deepseek_analysis com for_pdf=False para obter o sumário
        chat_analysis = generate_deepseek_analysis(chat_history, profile, user_name, for_pdf=False)
        # ----------------------------------------

        # --- Verificar se a análise de sumário foi bem-sucedida ---
        is_error = "Error generating AI analysis:" in chat_analysis or "Analysis could not be generated" in chat_analysis

        # --- Retornar Resposta ---
        response_data = {
            "analysis_text": chat_analysis,
            "status": "error" if is_error else "success",
            # Indica ao frontend que o PDF pode ser gerado se o sumário foi ok
            "pdf_ready": not is_error
        }

        print(f"DEBUG: Retornando análise/status: {response_data['status']}, pdf_ready: {response_data['pdf_ready']}")
        return jsonify(response_data), 200

    except Exception as e:
        print(f"ERROR CRÍTICO no endpoint /analyze: {e}")
        import traceback
        traceback.print_exc()

        error_response = {
            "analysis_text": f"Sorry, a critical error occurred while processing your analysis summary. Please try again later.\n\nError details: {str(e)[:200]}",
            "status": "error",
            "pdf_ready": False # Não pode gerar PDF se o sumário falhou
        }
        return jsonify(error_response), 500

# <<< REMOVED /submit-email endpoint >>>

# <<< NEW /generate-pdf endpoint >>>
@app.route("/generate-pdf", methods=["POST"])
def generate_pdf():
    """Endpoint para gerar e retornar PDF diretamente"""
    print("=== DEBUG: Recebendo requisição para gerar PDF ===")
    try:
        data = request.get_json()
        if not data:
            print("ERROR: Nenhum dado JSON recebido em /generate-pdf")
            return jsonify({"error": "No data received"}), 400

        chat_history = data.get("chatHistory", [])
        user_name = data.get("userName", "User")
        profile = data.get("profile", "unknown")

        if not chat_history:
             print("ERROR: Histórico de chat vazio em /generate-pdf")
             return jsonify({"error": "Chat history is empty"}), 400

        print(f"DEBUG: Iniciando geração de PDF para {user_name} ({profile})")

        # Gera o PDF usando o conteúdo detalhado da IA
        pdf_path, pdf_filename = generate_pdf_report_with_ai_content(
            chat_history, profile, user_name
        )

        # Verifica se o PDF foi gerado com sucesso
        if pdf_path and pdf_filename:
            print(f"DEBUG: PDF gerado: {pdf_filename}. Enviando cópia para Simplo...")

            # Envia cópia para o Simplo (EMAIL_RECEIVER)
            try:
                if EMAIL_RECEIVER:
                    simplo_subject = f"Ralph Analysis PDF - {user_name} ({profile})"
                    simplo_body = f"Attached is the generated PDF analysis report for {user_name} ({profile}).\n\nGenerated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

                    # Usa a função genérica para enviar email com anexo
                    email_sent_to_simplo = send_email_notification(
                        subject=simplo_subject,
                        text_body=simplo_body,
                        recipient_email=EMAIL_RECEIVER, # Envia para o email do Simplo
                        attachment_path=pdf_path
                    )
                    if email_sent_to_simplo:
                        print(f"DEBUG: Cópia do PDF enviada para {EMAIL_RECEIVER}")
                    else:
                        print(f"WARN: Falha ao enviar cópia do PDF para {EMAIL_RECEIVER}")
                else:
                    print("WARN: EMAIL_RECEIVER não configurado. Não foi possível enviar cópia para Simplo.")

            except Exception as email_error:
                # Loga o erro mas não impede o usuário de baixar o PDF
                print(f"WARN: Erro não crítico ao enviar cópia do email para Simplo: {email_error}")

            print(f"DEBUG: Retornando PDF {pdf_filename} para download do usuário.")
            # Retorna o PDF para download no navegador do usuário
            return send_file(
                pdf_path,
                as_attachment=True,
                download_name=pdf_filename, # Nome que o arquivo terá ao ser baixado
                mimetype='application/pdf'
            )
        else:
             # Se generate_pdf_report_with_ai_content retornou None, a geração falhou
             print("ERROR: Falha na geração do PDF (generate_pdf_report_with_ai_content retornou None).")
             # Tenta obter o motivo do erro (se foi passado pela exceção em generate_pdf_report_with_ai_content)
             # Nota: A implementação atual de generate_pdf_report_with_ai_content não retorna a mensagem de erro específica aqui.
             # Seria melhor refatorar para retornar a mensagem de erro.
             # Por agora, uma mensagem genérica.
             error_message = "PDF generation failed internally. Check server logs for details."
             # Se a falha foi por erro da API, a mensagem já foi logada.
             if client: # Verifica se o cliente está configurado
                 try:
                     # Tenta gerar novamente só para pegar a mensagem de erro (não ideal)
                     error_check = generate_deepseek_analysis(chat_history, profile, user_name, for_pdf=True)
                     if "Error generating AI analysis:" in error_check:
                         error_message = error_check
                 except:
                     pass # Ignora erros aqui

             return jsonify({"error": error_message}), 500

    except Exception as e:
        print(f"ERROR CRÍTICO no endpoint /generate-pdf: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"An unexpected server error occurred during PDF generation: {str(e)}"}), 500


@app.route("/health")
def health_check():
    """Endpoint para verificar se o serviço está funcionando."""
    return jsonify({
        "status": "healthy",
        "openai_configured": client is not None,
        "email_configured": bool(EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER) # Check receiver too
    })

if __name__ == "__main__":
    print("Iniciando Flask app...")
    print(f"DeepSeek configurado: {client is not None}")
    print(f"Email (Sender/Password/Receiver) configurado: {bool(EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER)}")
    # Garante que a porta seja lida corretamente do ambiente ou use 8080 como padrão
    port = int(os.environ.get("PORT", 8080))
    print(f"Servidor rodando em http://0.0.0.0:{port}")
    # Desativa o modo debug para produção, mas mantém para desenvolvimento local
    # Para deploy, o debug=False é mais seguro.
    # O reloader pode causar problemas em alguns ambientes de deploy.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

import os
# import smtplib # Removido - não enviaremos mais email
import json
import random
import re
import html
import uuid # Para nomes de arquivo únicos
import tempfile
from datetime import datetime
from openai import OpenAI # Importa OpenAI corretamente para SDK v1+
# from email.mime.text import MIMEText # Removido
# from email.mime.multipart import MIMEMultipart # Removido
# from email.mime.application import MIMEApplication # Removido
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
        prompt = f"""Based on the conversation with a {context} named {user_name}, provide a brief business analysis summary covering:\n1. Key business strengths identified\n2. Main areas for improvement\n3. 2-3 actionable recommendations\n\nKeep professional yet conversational. Max 250 words. **This is just a summary.** You can generate the full, detailed PDF report with step-by-step guidance in the next step.\n\nConversation Data:\n{conversation_text}\n\nAnalysis:"""

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
            timeout=70 if for_pdf else 220,  # Timeout maior para o PDF
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
        
        # Salva o PDF
        pdf.output(pdf_path)
        
        print(f"DEBUG: PDF gerado com sucesso: {pdf_path}")
        return pdf_path, pdf_filename
        
    except Exception as e:
        print(f"Erro ao gerar PDF: {e}")
        import traceback
        traceback.print_exc()
        return None, None

@app.route("/analyze", methods=["POST"])
def analyze_chat():
    """Endpoint para analisar o histórico de chat e gerar uma resposta."""
    print("=== DEBUG: Recebendo requisição de análise ===")
    
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
        # user_email = data.get("email")  # Removido - não coletamos mais email
        
        print(f"DEBUG: Recebido user_name={user_name}, profile={profile}, chat_history length={len(chat_history)}") # Email removido do log
        
        if not chat_history:
            print("ERROR: Histórico de chat vazio")
            return jsonify({"error": "Chat history is empty"}), 400
            
        # --- Salvar conversa em arquivo para referência ---
        conversation_text = format_conversation_to_text(chat_history, user_name, profile)
        # conversation_filepath = save_conversation_to_file(conversation_text) # Removido - não precisamos mais salvar para email
        # ------------------------------------------------
        
        # --- Gerar APENAS a análise de resumo usando a API da IA ---
        print("DEBUG: Gerando análise de resumo via API...")
        chat_analysis = generate_deepseek_analysis(chat_history, profile, user_name, for_pdf=False) # Garante que for_pdf é False
        # ----------------------------------------

        # --- Lógica de Geração/Envio de PDF REMOVIDA daqui ---
        # O PDF será gerado por um endpoint separado chamado pelo frontend

        # --- Retornar Resposta (apenas resumo) --- 
        response_data = {
            "analysis_text": chat_analysis,
            "status": "success" if "Error generating AI analysis:" not in chat_analysis else "error",
            "pdf_ready": True # Sinaliza ao frontend que o PDF pode ser gerado
        }
        
        print(f"DEBUG: Retornando análise/status: {response_data['status']}, pdf_ready: {response_data['pdf_ready']}")
        return jsonify(response_data), 200

    except Exception as e:
        print(f"ERROR CRÍTICO no endpoint /analyze: {e}")
        import traceback
        traceback.print_exc()
        
        error_response = {
            "analysis_text": f"Sorry, a critical error occurred while processing your analysis. Please try again. If the problem persists, contact support.\n\nError details: {str(e)[:200]}",
            "status": "error",
            "email_sent": False,
            "need_email": False
        }
        return jsonify(error_response), 500

@app.route("/health")
def health_check():
    """Endpoint para verificar se o serviço está funcionando."""
    return jsonify({
        "status": "healthy",
        "openai_configured": client is not None
        # "email_configured": bool(EMAIL_SENDER and EMAIL_PASSWORD) # Removido
    })

if __name__ == "__main__":
    print("Iniciando Flask app...")
    print(f"DeepSeek configurado: {client is not None}")
    # print(f"Email configurado: {bool(EMAIL_SENDER and EMAIL_PASSWORD)}") # Removido
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)


@app.@app.route("/generate-pdf", methods=["POST"])
def generate_pdf():
    """Endpoint para gerar o relatório PDF detalhado e retorná-lo para download."""
    print("=== DEBUG: Recebendo requisição para gerar PDF ===")
    
    try:
        if not request.is_json:
            print("ERROR: Request não é JSON")
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        if not data:
            print("ERROR: Nenhum dado JSON recebido")
            return jsonify({"error": "No data received"}), 400
            
        chat_history = data.get("chatHistory", [])
        user_name = data.get("userName", "User")
        profile = data.get("profile", "unknown")
        
        print(f"DEBUG: Gerando PDF para user_name={user_name}, profile={profile}, chat_history length={len(chat_history)}")
        
        if not chat_history:
            print("ERROR: Histórico de chat vazio para gerar PDF")
            return jsonify({"error": "Chat history is empty"}), 400
            
        # Gera o PDF
        pdf_path, pdf_filename = generate_pdf_report_with_ai_content(chat_history, profile, user_name)
        
        if pdf_path and pdf_filename:
            print(f"DEBUG: PDF gerado: {pdf_path}. Enviando arquivo...")
            # Retorna o arquivo PDF para download
            # as_attachment=True força o download
            # download_name define o nome do arquivo para o usuário
            return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)
        else:
            print("ERROR: Falha ao gerar o PDF para download")
            return jsonify({"error": "Failed to generate PDF report"}), 500
            
    except Exception as e:
        print(f"ERROR CRÍTICO no endpoint /generate-pdf: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"An unexpected error occurred: {str(e)[:200]}"}), 5000
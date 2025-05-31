# /home/ubuntu/ralph_deploy_novo_refactored/app/pdf_utils/generator.py
import os
import re
import tempfile
from datetime import datetime
from openai import OpenAI
from flask import render_template_string # Para renderizar o template HTML
from weasyprint import HTML, CSS # Para converter HTML para PDF

# --- Configuração (Pode ser movida para config.py depois) ---
# Diretório raiz do projeto (assumindo que generator.py está em app/pdf_utils)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE_FOLDER = os.path.join(PROJECT_ROOT, 'app', 'templates')
STATIC_FOLDER = os.path.join(PROJECT_ROOT, 'app', 'static') # Para referenciar imagens/css no HTML
PDF_OUTPUT_FOLDER = os.path.join(tempfile.gettempdir(), 'ralph_reports_refactored')
os.makedirs(PDF_OUTPUT_FOLDER, exist_ok=True)

# --- Cliente OpenAI (DeepSeek) --- 
# Idealmente, inicializar no __init__.py do app ou via config
client = None
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if DEEPSEEK_API_KEY:
    try:
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        print("Cliente DeepSeek (via OpenAI SDK) configurado em generator.py.")
    except Exception as e:
        print(f"Erro ao configurar cliente DeepSeek em generator.py: {e}")
        client = None
else:
    print("Aviso: DEEPSEEK_API_KEY não definida. Análise da IA não funcionará.")

# --- Funções Auxiliares (Reutilizadas e Adaptadas) ---
def format_conversation_to_text(chat_history, user_name="User", profile="unknown", max_messages=20):
    """Formata o histórico do chat em uma string de texto simples, limitando o número de mensagens."""
    text_log = f"Contexto da Conversa com {user_name} (Perfil: {profile.title()})\n"
    text_log += "="*50 + "\n\n"

    if len(chat_history) > max_messages:
        initial_messages = chat_history[:5]
        recent_messages = chat_history[-(max_messages-5):]
        limited_history = initial_messages + recent_messages
        text_log += "(Nota: Histórico da conversa foi resumido para focar nos pontos chave)\n\n"
    else:
        limited_history = chat_history

    for msg in limited_history:
        sender = msg.get("sender")
        content = msg.get("content", "(vazio)")
        clean_content = re.sub("<.*?>", "", content).strip()
        if not clean_content or "To start, please tell me" in clean_content:
            continue

        if sender == "bot":
            text_log += f"Ralph (AI): {clean_content}\n"
        elif sender == "user":
            text_log += f"{user_name}: {clean_content}\n"
        text_log += "---\n"

    return text_log

# --- Funções de Geração de Conteúdo por Seção --- 
def generate_ai_section(section_name, conversation_text, user_name, context):
    """Gera o conteúdo para uma seção específica do PDF usando a IA."""
    if not client:
        return f"Erro: Cliente DeepSeek não configurado para gerar seção '{section_name}'."

    prompts = {
        "executive_summary": f"Com base no seguinte histórico de conversa com {user_name} ({context}), gere um 'Resumo Executivo' conciso (aproximadamente 150-200 palavras) destacando o status atual do negócio, principais desafios e oportunidades discutidas.\n\nHistórico:\n{conversation_text}",
        "best_tactics": f"Analisando a conversa com {user_name} ({context}), identifique e descreva 3 a 5 'Melhores Táticas' acionáveis que podem ser implementadas para melhorar o negócio. Seja específico e referencie pontos da conversa, se possível.\n\nHistórico:\n{conversation_text}",
        "areas_to_change": f"A partir da conversa com {user_name} ({context}), detalhe 3 a 5 'Áreas para Mudar' críticas na abordagem ou modelo de negócio atual. Explique POR QUE cada mudança é necessária com base na discussão.\n\nHistórico:\n{conversation_text}",
        "automations": f"Considerando as tarefas e processos mencionados por {user_name} ({context}), sugira 3 a 4 áreas ou processos chave para 'Automação'. Explique brevemente o benefício potencial (tempo/eficiência) de cada um, SEM nomear softwares específicos.\n\nHistórico:\n{conversation_text}",
        "next_10_months_plan": f"Sintetize os achados chave (táticas, mudanças, automações) da conversa com {user_name} ({context}). Crie um 'Plano para os Próximos 10 Meses' resumido, delineando os principais passos ou áreas de foco para atingir os objetivos mencionados.\n\nHistórico:\n{conversation_text}"
    }

    prompt = prompts.get(section_name)
    if not prompt:
        return f"Erro: Prompt não definido para a seção '{section_name}'."

    try:
        print(f"--- Gerando seção '{section_name}' via DeepSeek API ---")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": f"Você é Ralph, um analista de negócios AI especialista em imóveis. Forneça conteúdo claro e acionável para a seção solicitada, baseado nos dados da conversa com {user_name} ({context}). Responda APENAS com o conteúdo da seção pedida."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=500, # Limite razoável por seção
            temperature=0.6,
            timeout=45, # Timeout por seção
        )
        section_content = response.choices[0].message.content.strip()
        print(f"--- Seção '{section_name}' gerada com sucesso ---")
        # Simples limpeza para remover markdown básico que pode interferir no HTML
        section_content = section_content.replace("**", "") # Remove negrito
        section_content = section_content.replace("* ", "<br>• ") # Converte lista simples
        return section_content

    except Exception as e:
        print(f"Erro ao gerar seção '{section_name}' via API DeepSeek: {e}")
        error_msg = f"Erro ao gerar conteúdo para '{section_name}'. Tente novamente mais tarde."
        if "authentication" in str(e).lower():
             error_msg += " (Falha na autenticação da API)"
        elif "quota" in str(e).lower() or "limit" in str(e).lower() or "insufficient_quota" in str(e).lower():
             error_msg += " (Quota da API excedida)"
        elif "timeout" in str(e).lower() or "timed out" in str(e).lower():
             error_msg += " (Tempo limite da API excedido)"
        return error_msg

# --- Função Principal de Geração de PDF --- 
def generate_pdf_report_weasyprint(chat_history, profile, user_name="User"):
    """Gera o relatório PDF usando WeasyPrint e template HTML, com conteúdo por seção."""
    try:
        print("DEBUG: Iniciando geração de PDF com WeasyPrint...")
        # 1. Formatar histórico
        conversation_text = format_conversation_to_text(chat_history, user_name, profile)

        # 2. Definir contexto
        profile_context = {
            'individual': 'agente imobiliário autônomo',
            'employee': 'funcionário de imobiliária',
            'owner': 'dono de imobiliária'
        }.get(profile, 'profissional imobiliário')

        # 3. Gerar conteúdo para cada seção (sequencialmente)
        print("DEBUG: Gerando conteúdo das seções via IA...")
        report_data = {
            'user_name': user_name,
            'profile_title': profile_context.title(),
            'generation_date': datetime.now().strftime('%d de %B de %Y'),
            'sections': {}
        }

        section_keys = ["executive_summary", "best_tactics", "areas_to_change", "automations", "next_10_months_plan"]
        has_error = False
        for key in section_keys:
            content = generate_ai_section(key, conversation_text, user_name, profile_context)
            report_data['sections'][key] = content
            if "Erro:" in content or "Erro ao gerar" in content:
                print(f"WARN: Erro detectado ao gerar seção '{key}'.")
                has_error = True
                # Continuar gerando outras seções, mas marcar erro

        if has_error:
             # Decide se quer gerar um PDF parcial com erros ou falhar completamente
             # Aqui, vamos falhar para garantir um relatório completo
             raise ValueError("Falha ao gerar uma ou mais seções do relatório via IA.")

        # 4. Carregar Template HTML
        template_path = os.path.join(TEMPLATE_FOLDER, 'report_template.html')
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template HTML não encontrado em: {template_path}")

        with open(template_path, 'r', encoding='utf-8') as f:
            template_html_string = f.read()

        # 5. Renderizar HTML com os dados
        # Usando render_template_string (simples, sem necessidade de Jinja completo aqui)
        # Substituições manuais simples para este caso:
        rendered_html = template_html_string
        rendered_html = rendered_html.replace("{{ user_name }}", report_data['user_name'])
        rendered_html = rendered_html.replace("{{ profile_title }}", report_data['profile_title'])
        rendered_html = rendered_html.replace("{{ generation_date }}", report_data['generation_date'])
        for key, content in report_data['sections'].items():
             # Converte quebras de linha em <br> para HTML e escapa HTML potencialmente inseguro
             import html
             safe_content = html.escape(content).replace('\n', '<br>')
             rendered_html = rendered_html.replace(f"{{{{ sections.{key} }}}}", safe_content)

        # 6. Converter HTML para PDF com WeasyPrint
        print("DEBUG: Convertendo HTML renderizado para PDF com WeasyPrint...")
        # Passar o diretório base para WeasyPrint encontrar arquivos estáticos (CSS, imagens)
        html_obj = HTML(string=rendered_html, base_url=f"file://{PROJECT_ROOT}/") # Usar file:// para caminhos locais

        # Definir nome e caminho do arquivo PDF
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_user_name = re.sub(r'[^a-zA-Z0-9_]', '_', user_name.lower())
        pdf_filename = f"ralph_analysis_{safe_user_name}_{timestamp}.pdf"
        pdf_path = os.path.join(PDF_OUTPUT_FOLDER, pdf_filename)

        # Escrever o PDF
        html_obj.write_pdf(pdf_path)

        print(f"DEBUG: PDF gerado com WeasyPrint e salvo em: {pdf_path}")
        return pdf_path, pdf_filename

    except FileNotFoundError as fnf_error:
        print(f"ERROR: Arquivo não encontrado durante geração do PDF: {fnf_error}")
        return None, None
    except ValueError as ve_error: # Erro na geração de conteúdo IA
        print(f"ERROR: {ve_error}")
        return None, None
    except Exception as e:
        print(f"Erro CRÍTICO ao gerar PDF com WeasyPrint: {e}")
        import traceback
        traceback.print_exc()
        return None, None

# --- Função de Geração de Sumário (pode ficar em main.py ou aqui) ---
def generate_summary_analysis(chat_history, profile, user_name="User"):
    """Gera apenas o sumário de análise para exibição no chat."""
    if not client:
        return "Erro: Cliente DeepSeek não configurado para gerar sumário.", False

    conversation_text = format_conversation_to_text(chat_history, user_name, profile, max_messages=15)

    prompt = f"""Forneça uma prévia concisa da análise (máx 150 palavras) para {user_name} ({profile.title()}) cobrindo:
1. 2 pontos fortes chave.
2. 2 áreas principais para melhoria.
3. 1 recomendação de alta prioridade.

IMPORTANTE: Indique CLARAMENTE que esta é apenas uma prévia e que o relatório PDF detalhado estará disponível para download.

Use tom profissional, mas conversacional. NÃO mencione ferramentas específicas.

Dados da Conversa:
{conversation_text}"""

    try:
        print("--- Gerando SUMÁRIO via DeepSeek API ---")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": f"Você é Ralph, analista de negócios AI. Gere um sumário de pré-análise conciso e profissional para {user_name} ({profile.title()})."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=300,
            temperature=0.7,
            timeout=60,
        )
        summary_text = response.choices[0].message.content.strip()
        print("--- Sumário gerado com sucesso ---")
        return summary_text, True # Retorna texto e sucesso

    except Exception as e:
        print(f"Erro ao gerar SUMÁRIO via API DeepSeek: {e}")
        error_msg = f"Erro ao gerar o sumário da análise."
        if "authentication" in str(e).lower(): error_msg += " (Falha na autenticação da API)"
        elif "quota" in str(e).lower(): error_msg += " (Quota da API excedida)"
        elif "timeout" in str(e).lower(): error_msg += " (Tempo limite da API excedido)"
        return error_msg, False # Retorna erro e falha


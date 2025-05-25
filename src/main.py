import os
import smtplib
import json
import random
import re
import html
import cohere # Import Cohere library
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app) # Allow requests from the frontend

# --- Configuration from Environment Variables ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
COHERE_API_KEY = os.getenv("COHERE_API_KEY") # Use Cohere API Key
# -------------------------------------------

# Configure Cohere client (only if key is provided)
cohere_client = None
if COHERE_API_KEY:
    try:
        cohere_client = cohere.Client(COHERE_API_KEY)
        print("Cohere client configured successfully.")
    except Exception as e:
        print(f"Error configuring Cohere client: {e}")
        cohere_client = None # Ensure client is None if configuration fails
else:
    print("Warning: COHERE_API_KEY environment variable not set. AI analysis will be skipped.")

def format_currency(value):
    """Helper to format numbers as currency (e.g., $1,234.56). Placeholder."""
    try:
        num_value = float(re.sub(r"[^0-9.]", "", str(value)))
        return f"${num_value:,.2f}"
    except ValueError:
        return str(value)

def generate_ai_enhanced_diagnosis(data):
    """Generates an enhanced diagnosis using Cohere based on conversation data."""
    if not cohere_client:
        return "<div class=\"diagnosis-box\"><p><em>AI analysis could not be performed. Configuration missing.</em></p></div>"

    user_name = data.get("userName", "User")
    business_name = data.get("businessName", "their business")
    business_type = data.get("businessType", "real estate business")
    role = data.get("role", "")
    questions_data = data.get("questions", [])

    # Prepare context for AI (same as before)
    context = f"User Name: {user_name}\n"
    if data.get("companyName"): context += f"Company Name: {data['companyName']}\n"
    if business_name != "their business": context += f"Business Name: {business_name}\n"
    context += f"Business Type: {business_type}\n"
    if role: context += f"Role: {role}\n\n"
    context += "User Responses:\n"
    for item in questions_data:
        question = item.get("question", "Q").replace("\n", " ")
        answer = item.get("answer", "A").replace("\n", " ")
        context += f"- Q: {question}\n  A: {answer}\n"

    # Construct the prompt for Cohere (similar structure, Cohere is good with instructions)
    prompt = f"""
    Analyze the following conversation data from a real estate professional named {user_name} regarding their business ({business_name}, type: {business_type}, role: {role}).

    Conversation Data (Question & Answer format):
    {context}

    Based *only* on the provided conversation data, generate a detailed business analysis report in English, formatted in simple HTML (use `<h3>`, `<h4>`, `<p>`, `<ul>`, `<li>`, `<strong>`, `<em>`, `<br>`, and `<span>` for colored text). Do NOT include `<html>`, `<head>`, or `<body>` tags. Wrap the entire response in a single `<div class="diagnosis-box">`.

    Follow these instructions precisely:

    1.  **Main Title:** `<h3>Business Analysis for {user_name}</h3>`
    2.  **Introduction:** Briefly acknowledge the user and the purpose of the analysis.
    3.  **Key Findings:**
        *   `<h4>Areas for Improvement:</h4>` Identify 2-4 specific areas where the user's answers suggest potential for improvement or streamlining (e.g., challenges mentioned, processes described).
        *   `<h4>Significant Time Costs:</h4>` Identify the tasks or areas where the user seems to spend considerable time, based on their answers (e.g., administrative tasks, specific challenges). Quantify if possible (e.g., "spending <span style='color: #dc3545; font-weight: bold;'>{user_answer_about_time}</span> on admin"). Use red (#dc3545) for highlighting time costs or challenges.
    4.  **Automation Potential:**
        *   `<h4>Opportunities with Automation:</h4>` Based on the identified areas for improvement and time costs, subtly suggest how automation or AI-driven tools could help *without naming specific products*. Frame it around benefits like saving time, improving efficiency, or enhancing client management. Example: "Implementing automated follow-up sequences could potentially free up <span style='color: #28a745; font-weight: bold;'>significant time</span> currently spent on manual communication." or "Exploring tools that automate document preparation could reduce the burden of paperwork." Use green (#28a745) for highlighting potential benefits or savings.
    5.  **Conclusion:** A brief concluding remark.
    6.  **Tone:** Professional, insightful, helpful, and focused solely on the provided data.
    7.  **Constraint:** Do NOT invent information. Stick strictly to what the user provided in the Q&A.
    """

    try:
        print("\n--- Sending request to Cohere ---")
        # Generate content using Cohere's generate endpoint
        response = cohere_client.generate(
            model='command', # Or other suitable Cohere model like 'command-light'
            prompt=prompt,
            max_tokens=1024, # Adjust as needed, Cohere might have different token counts
            temperature=0.6,
            k=0,
            p=0.75,
            stop_sequences=[],
            return_likelihoods='NONE'
        )
        print("--- Cohere response received ---")

        # Extract the generated text
        ai_diagnosis_html = response.generations[0].text

        # Basic validation/cleanup (same as before)
        if not ai_diagnosis_html.strip().startswith('<div class="diagnosis-box">'):
             ai_diagnosis_html = f'<div class="diagnosis-box">{ai_diagnosis_html}</div>' # Ensure it's wrapped

        # Add disclaimer (same as before)
        ai_diagnosis_html += "<p style='font-size: 0.8em; color: #6c757d; margin-top: 15px;'><em>Disclaimer: This AI-generated analysis is based on the provided information and aims to highlight potential areas. A comprehensive business strategy requires deeper consultation.</em></p>"

        return ai_diagnosis_html

    except Exception as e:
        print(f"Error calling Cohere API: {e}")
        # Fallback message if Cohere fails
        return f"<div class=\"diagnosis-box\"><p><strong>Analysis Report for {html.escape(user_name)}</strong></p><p>We received your information about {html.escape(business_name)}. An error occurred during the AI-powered analysis generation using Cohere.</p><p><em>Common areas real estate professionals focus on include lead generation, client follow-up, and time management. Exploring tools and strategies in these areas can often yield significant improvements.</em></p><p><em>Error details: {html.escape(str(e))}</em></p></div>"

def send_email_notification(subject, html_body):
    """Sends an email using configured SMTP settings (No changes needed here)."""
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER, SMTP_SERVER]):
        print("Email configuration incomplete. Skipping email notification.")
        return False

    message = MIMEMultipart()
    message["From"] = EMAIL_SENDER
    message["To"] = EMAIL_RECEIVER
    message["Subject"] = subject
    message.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        print(f"Connecting to SMTP server: {SMTP_SERVER}:{SMTP_PORT}")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.ehlo()
        server.starttls()
        server.ehlo()
        print("Logging into email account...")
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        print("Sending email...")
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, message.as_string())
        server.quit()
        print(f"Email sent successfully to {EMAIL_RECEIVER}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP Authentication Error: {e}. Check email/password (App Password?).")
        return False
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(app.static_folder, path)

@app.route("/analyze", methods=["POST"])
def analyze_data():
    """Receives data, generates AI diagnosis (now using Cohere), sends email, returns diagnosis."""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data received"}), 400

        log_data = {k: v for k, v in data.items() if k != 'images'}
        print("Received data for analysis:", json.dumps(log_data, indent=2))

        user_name = data.get("userName", "User")
        company_name = data.get("companyName", "")
        business_name = data.get("businessName", "their business")
        business_type = data.get("businessType", "N/A")
        role = data.get("role", "N/A")
        chat_history = data.get("chatHistory", [])
        questions_answers = data.get("questions", [])

        # --- Generate AI Diagnosis (using Cohere function) --- 
        ai_diagnosis_html = generate_ai_enhanced_diagnosis(data)
        # -----------------------------------------------------

        # --- Prepare Email Content (No changes needed here) --- 
        subject_prefix = "Ralph Analysis Completed"
        subject_identifier = f"{user_name}"
        if company_name:
            subject_identifier += f" - {company_name}"
        elif business_name != "their business":
             subject_identifier += f" - {business_name}"
        else:
             subject_identifier += f" ({business_type})"
        email_subject = f"{subject_prefix}: {subject_identifier}"

        email_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{html.escape(email_subject)}</title>
<style>
  body {{ font-family: sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background-color: #f4f7f6; }}
  .container {{ max-width: 800px; margin: 20px auto; background-color: #ffffff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
  h1 {{ color: #100f0f; border-bottom: 2px solid #100f0f; padding-bottom: 10px; margin-top: 0; }}
  h2 {{ color: #333; margin-top: 30px; border-bottom: 1px solid #ccc; padding-bottom: 5px; }}
  .info-section p {{ margin: 6px 0; font-size: 0.95em; }}
  .info-section strong {{ color: #100f0f; min-width: 120px; display: inline-block; }}
  .chat-log {{ margin-top: 20px; border: 1px solid #e0e0e0; border-radius: 5px; background-color: #fdfdfd; padding: 15px; max-height: 700px; overflow-y: auto; font-size: 0.9em; }}
  .chat-message {{ margin-bottom: 12px; padding: 10px 12px; border-radius: 6px; word-wrap: break-word; }}
  .bot-message {{ background-color: #f0f0f0; border-left: 4px solid #555; }}
  .user-message {{ background-color: #e6f7ff; border-left: 4px solid #100f0f; }}
  .message-sender {{ font-weight: bold; margin-bottom: 5px; display: block; color: #100f0f; }}
  .message-content button, .business-type-selector {{ display: none !important; }}
  .diagnosis-box {{ margin-top: 30px; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px; background-color: #f9f9f9; }}
  .diagnosis-box h3 {{ color: #100f0f; margin-top: 0; border-bottom: 1px solid #ccc; padding-bottom: 8px; }}
  .diagnosis-box h4 {{ color: #333; margin-top: 20px; margin-bottom: 10px; }}
  .diagnosis-box ul {{ list-style: disc; padding-left: 25px; margin-top: 5px; }}
  .diagnosis-box li {{ margin-bottom: 8px; }}
  .diagnosis-positive {{ color: #28a745; font-weight: bold; }}
  .diagnosis-negative {{ color: #dc3545; font-weight: bold; }}
</style>
</head>
<body>
<div class="container">
  <h1>Ralph Real Estate Analysis Report</h1>
  <div class="info-section">
      <h2>User Information</h2>
      <p><strong>Name:</strong> {html.escape(user_name)}</p>
      <p><strong>Business Type:</strong> {html.escape(business_type.replace('_', ' ').title())}</p>
      {f'<p><strong>Company Name:</strong> {html.escape(company_name)}</p>' if company_name else ''}
      {f'<p><strong>Business Name:</strong> {html.escape(business_name)}</p>' if business_name != "their business" else ''}
      {f'<p><strong>Role:</strong> {html.escape(role)}</p>' if role else ''}
  </div>

  <h2>Full Conversation Log:</h2>
  <div class="chat-log">
"""
        if chat_history:
            for msg in chat_history:
                sender = msg.get("sender")
                content = msg.get("content", "(empty)")
                safe_content = re.sub(r'<script.*?</script>', '', content, flags=re.IGNORECASE | re.DOTALL)
                safe_content = re.sub(r'<div class="diagnosis-box.*?</div>', '', safe_content, flags=re.DOTALL | re.IGNORECASE)
                safe_content = re.sub(r'<div class="business-type-selector.*?</div>', '', safe_content, flags=re.DOTALL | re.IGNORECASE)

                if sender == "bot":
                    email_body += f"<div class='chat-message bot-message'><span class='message-sender'>Ralph (Bot):</span><div class='message-content'>{safe_content}</div></div>"
                elif sender == "user":
                    email_body += f"<div class='chat-message user-message'><span class='message-sender'>{html.escape(user_name)}:</span><div class='message-content'>{html.escape(content)}</div></div>"
        else:
            email_body += "<p><em>No chat history was recorded.</em></p>"
        email_body += """  </div>

  <h2>AI-Generated Analysis (Cohere):</h2>
"""
        email_body += ai_diagnosis_html
        email_body += """</div>
</body>
</html>"""
        # -----------------------------------------------------

        # --- Send Email Notification (Silently) ---
        send_email_notification(email_subject, email_body)
        # -----------------------------------------

        # --- Return AI Diagnosis to Frontend --- 
        return jsonify({"diagnosis_html": ai_diagnosis_html})
        # ---------------------------------------

    except Exception as e:
        print(f"Error in /analyze endpoint: {e}")
        # Provide a generic error message to the frontend
        return jsonify({"diagnosis_html": f"<div class=\"diagnosis-box\"><p>An unexpected error occurred processing your request. Please try again later. Error: {html.escape(str(e))}</p></div>"}), 500

if __name__ == "__main__":
    # This part is mainly for local testing, Render uses the gunicorn command
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

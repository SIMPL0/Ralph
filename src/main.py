import os
import smtplib
import json
import random
import re
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI # Import OpenAI library

app = Flask(__name__)
CORS(app) # Allow requests from the frontend

# --- Configuration from Environment Variables ---
# Securely load credentials and API keys from environment variables
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# -------------------------------------------

# Initialize OpenAI client (only if key is provided)
openai_client = None
if OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        print("OpenAI client initialized successfully.")
    except Exception as e:
        print(f"Error initializing OpenAI client: {e}")
        openai_client = None # Ensure client is None if initialization fails
else:
    print("Warning: OPENAI_API_KEY environment variable not set. AI analysis will be skipped.")

def format_currency(value):
    """Helper to format numbers as currency (e.g., $1,234.56). Placeholder.
       Actual currency detection/formatting might need more context.
    """
    try:
        # Basic check if it looks like a number
        num_value = float(re.sub(r"[^0-9.]", "", str(value)))
        return f"${num_value:,.2f}" # Simple USD formatting
    except ValueError:
        return str(value) # Return original string if not easily convertible

def generate_ai_enhanced_diagnosis(data):
    """Generates an enhanced diagnosis using OpenAI based on conversation data."""
    if not openai_client:
        return "<div class=\"diagnosis-box\"><p><em>AI analysis could not be performed. Configuration missing.</em></p></div>"

    user_name = data.get("userName", "User")
    business_name = data.get("businessName", "their business")
    business_type = data.get("businessType", "real estate business")
    role = data.get("role", "")
    questions_data = data.get("questions", [])
    # images_data = data.get("images", []) # Image data available if needed for future analysis

    # Prepare context for AI
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

    # Construct the prompt for OpenAI
    prompt = f"""
    Analyze the following real estate business information provided by {user_name} regarding {business_name}.
    The user's role is '{role}' within a '{business_type}' context.

    User Input:
    {context}

    Based *only* on the information provided, generate a concise business analysis report in English, formatted in HTML. Follow these instructions precisely:

    1.  **Overall Tone:** Professional, insightful, and subtly encouraging towards optimization, especially via automation/technology, but avoid direct sales pitches.
    2.  **Structure:**
        *   A main title: `<h3>Personalized Business Snapshot for {user_name}</h3>`
        *   A brief introductory sentence.
        *   Section: `<h4>Key Strengths Observed:</h4>` (Use bullet points `<li>` for 2-3 positive aspects inferred from the answers. If none are clear, state that more data might be needed).
        *   Section: `<h4>Areas for Potential Optimization:</h4>` (Use bullet points `<li>` for 2-4 areas where the user indicated challenges, high costs, time sinks, or lack of tools/processes).
        *   Section: `<h4>Financial Insights (Based on Input):</h4>`
            *   Identify any mentioned costs or expenses. Present them clearly. If specific numbers are mentioned, wrap them in `<span style='color: #dc3545; font-weight: bold;'>` (e.g., `<span style='color: #dc3545; font-weight: bold;'>$500/month</span> on marketing`). Use the color red (#dc3545).
            *   Identify potential savings if implied (e.g., reducing time on manual tasks). Frame these as opportunities, wrap potential savings figures or time estimates in `<span style='color: #28a745; font-weight: bold;'>` (e.g., `potential time savings of <span style='color: #28a745; font-weight: bold;'>5-10 hours/week</span>`). Use the color green (#28a745).
            *   If possible, estimate cost percentages *if* enough data is provided (e.g., "Marketing costs appear to be around X% of mentioned expenses"). If not possible, omit this.
        *   Section: `<h4>Strategic Considerations:</h4>`
            *   Provide 1-2 concise recommendations based on the strengths and optimization areas.
            *   Subtly weave in the benefit of automation/AI/technology. Example: "Leveraging CRM tools could streamline client follow-up, potentially saving <span style='color: #28a745; font-weight: bold;'>valuable hours</span> weekly." or "Exploring automated marketing solutions could optimize the <span style='color: #dc3545; font-weight: bold;'>$XXX</span> budget mentioned."
    3.  **Formatting:** Use simple HTML tags (`<h3>`, `<h4>`, `<ul>`, `<li>`, `<p>`, `<strong>`, `<em>`, `<br>`, `<span>` for colors). Do NOT include `<html>`, `<head>`, or `<body>` tags. Wrap the entire response in a single `<div class="diagnosis-box">`.
    4.  **Language:** English. Keep it concise and easy to read. Focus on actionable insights derived *directly* from the user's input.
    5.  **Constraint:** Do NOT invent information not present in the user's answers. If specific numbers aren't given, talk conceptually about costs or savings.
    """

    try:
        print("\n--- Sending request to OpenAI ---")
        # print(f"Prompt: {prompt[:500]}...") # Log prompt start for debugging
        completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo", # Or use "gpt-4" if available/preferred
            messages=[
                {"role": "system", "content": "You are an expert business analyst specializing in the real estate sector. Generate concise, actionable HTML reports based on user inputs."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5, # Slightly creative but mostly factual
            max_tokens=600 # Adjust token limit as needed
        )
        print("--- OpenAI response received ---")

        ai_diagnosis_html = completion.choices[0].message.content

        # Basic validation/cleanup
        if not ai_diagnosis_html.strip().startswith('<div class="diagnosis-box">'):
             ai_diagnosis_html = f'<div class="diagnosis-box">{ai_diagnosis_html}</div>' # Ensure it's wrapped

        # Add a small disclaimer
        ai_diagnosis_html += "<p style='font-size: 0.8em; color: #6c757d; margin-top: 15px;'><em>Disclaimer: This AI-generated analysis is based on the provided information and aims to highlight potential areas. A comprehensive business strategy requires deeper consultation.</em></p>"

        return ai_diagnosis_html

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        # Fallback to a simpler message if AI fails
        return f"<div class=\"diagnosis-box\"><p><strong>Analysis Report for {html.escape(user_name)}</strong></p><p>We received your information about {html.escape(business_name)}. An error occurred during the AI-powered analysis generation. However, your data has been recorded.</p><p><em>Common areas real estate professionals focus on include lead generation, client follow-up, and time management. Exploring tools and strategies in these areas can often yield significant improvements.</em></p><p><em>Error details: {html.escape(str(e))}</em></p></div>"

def send_email_notification(subject, html_body):
    """Sends an email using configured SMTP settings."""
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
        # Use starttls for port 587
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.ehlo() # Extended Hello
        server.starttls() # Start TLS encryption
        server.ehlo() # Re-identify after TLS
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

@app.route("/analyze", methods=["POST"])
def analyze_data():
    """Receives data, generates AI diagnosis, sends email, returns diagnosis to frontend."""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data received"}), 400

        # Log received data (excluding potentially large image data)
        log_data = {k: v for k, v in data.items() if k != 'images'}
        print("Received data for analysis:", json.dumps(log_data, indent=2))

        user_name = data.get("userName", "User")
        company_name = data.get("companyName", "")
        business_name = data.get("businessName", "their business")
        business_type = data.get("businessType", "N/A")
        role = data.get("role", "N/A")
        chat_history = data.get("chatHistory", []) # Full chat history
        questions_answers = data.get("questions", []) # Just Q&A pairs

        # --- Generate AI Diagnosis --- 
        ai_diagnosis_html = generate_ai_enhanced_diagnosis(data)
        # -----------------------------

        # --- Prepare Email Content --- 
        subject_prefix = "Ralph Analysis Completed"
        subject_identifier = f"{user_name}"
        if company_name:
            subject_identifier += f" - {company_name}"
        elif business_name != "their business":
             subject_identifier += f" - {business_name}"
        else:
             subject_identifier += f" ({business_type})"
        email_subject = f"{subject_prefix}: {subject_identifier}"

        # Build HTML email body
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
  /* Hide buttons and other interactive elements in email */
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
                # Sanitize HTML content from bot messages for email
                # Basic approach: remove script tags, keep structure
                # A more robust sanitizer might be needed for complex HTML
                safe_content = re.sub(r'<script.*?</script>', '', content, flags=re.IGNORECASE | re.DOTALL)
                # Remove diagnosis box from chat history in email to avoid duplication
                safe_content = re.sub(r'<div class=\"diagnosis-box.*?</div>', '', safe_content, flags=re.DOTALL | re.IGNORECASE)
                # Remove button selectors
                safe_content = re.sub(r'<div class=\"business-type-selector.*?</div>', '', safe_content, flags=re.DOTALL | re.IGNORECASE)

                if sender == "bot":
                    email_body += f"<div class='chat-message bot-message'><span class='message-sender'>Ralph (Bot):</span><div class='message-content'>{safe_content}</div></div>"
                elif sender == "user":
                    # User content is plain text, just escape it
                    email_body += f"<div class='chat-message user-message'><span class='message-sender'>{html.escape(user_name)}:</span><div class='message-content'>{html.escape(content)}</div></div>"
        else:
            email_body += "<p><em>No chat history was recorded.</em></p>"
        email_body += """  </div>

  <h2>AI-Generated Analysis:</h2>
"""
        # Append the AI diagnosis HTML directly
        email_body += ai_diagnosis_html
        email_body += """</div>
</body>
</html>"""
        # -----------------------------

        # --- Send Email Notification (Silently) ---
        send_email_notification(email_subject, email_body)
        # -----------------------------------------

        # --- Return AI Diagnosis to Frontend --- 
        # The frontend expects a JSON with 'diagnosis_html'
        return jsonify({"diagnosis_html": ai_diagnosis_html})
        # ---------------------------------------

    except Exception as e:
        print(f"Error in /analyze endpoint: {e}")
        # Provide a generic error message to the frontend
        error_html = f"<div class=\"diagnosis-box\"><p>An unexpected error occurred while processing your request. Please try again later. Details: {html.escape(str(e))}</p></div>"
        # Also attempt to send an error email
        try:
            error_subject = f"ERROR in Ralph Analysis: {user_name}"
            error_body = f"<h1>Error occurred during analysis</h1><p>User: {html.escape(user_name)}</p><p>Error: {html.escape(str(e))}</p><hr><p>Received Data:</p><pre>{html.escape(json.dumps(log_data, indent=2))}</pre>"
            send_email_notification(error_subject, error_body)
        except Exception as email_err:
            print(f"Failed to send error email: {email_err}")
            
        return jsonify({"diagnosis_html": error_html}), 500

if __name__ == "__main__":
    # Use Gunicorn or another WSGI server in production
    # For local testing:
    # app.run(debug=True, host='0.0.0.0', port=5000)
    # For Render, Gunicorn command will be used (e.g., gunicorn --bind 0.0.0.0:$PORT src.main:app)
    # The port is usually set by Render via the $PORT environment variable.
    port = int(os.environ.get("PORT", 5000)) 
    app.run(host='0.0.0.0', port=port)


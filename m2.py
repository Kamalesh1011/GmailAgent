import imaplib
import email
from email.header import decode_header
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template_string
import threading
import time
from datetime import datetime
from groq import Groq

# ==================================================================================
# CONFIG - EDIT THESE VALUES DIRECTLY
# ==================================================================================
EMAIL_USER = ""  # <-- PUT YOUR GMAIL HERE
EMAIL_PASS = ""      # <-- PUT YOUR GMAIL APP PASSWORD HERE
GROQ_API_KEY = ""  # <-- GET FREE KEY FROM https://console.groq.com

IMAP_SERVER = "imap.gmail.com"
SMTP_SERVER = "smtp.gmail.com"
CHECK_INTERVAL = 60 

client = Groq(api_key=GROQ_API_KEY)
MODEL_NAME = "llama-3.1-8b-instant"  # Fast and free Groq model

# ==================================================================================
# DATA STORAGE
# ==================================================================================
stored_logs = []
stats = {"total": 0, "today": 0, "success": 0, "failed": 0}

# ==================================================================================
# LLM FUNCTIONS
# ==================================================================================
def llm(message: str, system_prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[ERROR] {e}"

def summarize_email(body: str) -> str:
    system = "Summarize this email in 3-5 bullet points with key info and urgency."
    return llm(body, system)

def generate_reply(body: str, subject: str, segment: str) -> str:
    system = f"""You are an AI email assistant replying to a {segment} customer.
Be brief (4-6 sentences), professional, and helpful. Acknowledge their issue and provide next steps.
Subject: {subject}"""
    return llm(body, system)

def classify_segment(email_text: str, sender: str) -> str:
    t = email_text.lower()
    
    if any(d in sender.lower() for d in ["vipclient.com", "platinum.com", "premium.co"]):
        return "VIP"
    if any(k in t for k in ["invoice", "payment", "billing", "refund"]):
        return "Finance"
    if any(k in t for k in ["bug", "error", "crash", "technical", "not working"]):
        return "Technical"
    if any(k in t for k in ["complaint", "angry", "bad service", "unhappy"]):
        return "Complaint"
    if any(k in t for k in ["hr", "leave", "resign", "onboarding"]):
        return "HR"
    
    return "General"

# ==================================================================================
# GMAIL FUNCTIONS
# ==================================================================================
def fetch_unseen_emails(limit=10):
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")
        
        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            return []
        
        mails = []
        mail_ids = data[0].split()[-limit:]
        
        for num in mail_ids:
            status, msg_data = mail.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            
            for resp in msg_data:
                if isinstance(resp, tuple):
                    msg = email.message_from_bytes(resp[1])
                    
                    raw_subject, encoding = decode_header(msg.get("Subject", ""))[0]
                    if isinstance(raw_subject, bytes):
                        subject = raw_subject.decode(encoding or "utf-8", errors="ignore")
                    else:
                        subject = raw_subject or ""
                    
                    sender = msg.get("From", "")
                    
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body = part.get_payload(decode=True).decode(errors="ignore")
                                    break
                                except:
                                    pass
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode(errors="ignore")
                        except:
                            body = ""
                    
                    mails.append({
                        "subject": subject,
                        "sender": sender,
                        "body": body
                    })
        
        mail.logout()
        return mails
    except Exception as e:
        print(f"❌ Fetch error: {e}")
        return []

def send_reply(receiver: str, subject: str, message: str):
    msg = MIMEMultipart()
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = EMAIL_USER
    msg["To"] = receiver
    msg.attach(MIMEText(message, "plain"))
    
    with smtplib.SMTP_SSL(SMTP_SERVER, 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, [receiver], msg.as_string())

# ==================================================================================
# BACKGROUND WORKER
# ==================================================================================
def email_worker():
    global stored_logs, stats
    
    while True:
        print(f"\n🔍 [{datetime.now().strftime('%H:%M:%S')}] Checking inbox...")
        
        emails = fetch_unseen_emails()
        
        if not emails:
            print("📭 No new emails")
        else:
            for mail_data in emails:
                full_text = f"{mail_data['subject']}\n{mail_data['body']}"
                segment = classify_segment(full_text, mail_data['sender'])
                
                print(f"📨 Processing: {mail_data['subject'][:50]}... → {segment}")
                
                summary = summarize_email(mail_data['body'])
                reply = generate_reply(mail_data['body'], mail_data['subject'], segment)
                
                # Send reply
                try:
                    send_reply(mail_data['sender'], mail_data['subject'], reply)
                    print(f"✅ Sent to: {mail_data['sender']}")
                    stats["success"] += 1
                    reply_sent = True
                except Exception as e:
                    print(f"❌ Send failed: {e}")
                    stats["failed"] += 1
                    reply_sent = False
                
                stats["total"] += 1
                stats["today"] += 1
                
                # Store log
                stored_logs.insert(0, {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "sender": mail_data['sender'],
                    "subject": mail_data['subject'],
                    "segment": segment,
                    "summary": summary,
                    "reply": reply,
                    "sent": reply_sent
                })
                
                if len(stored_logs) > 50:
                    stored_logs.pop()
        
        print(f"⏰ Next check in {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)

# ==================================================================================
# FLASK APP WITH EMBEDDED UI
# ==================================================================================
app = Flask(__name__)

# --- UPDATED HTML TEMPLATE FOR BRIGHTER/MODERN UI ---
HTML_TEMPLATE = HTML_TEMPLATE = HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>AI Email Agent Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <!-- Tailwind CSS CDN -->
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Inter", sans-serif;
    }
    ::-webkit-scrollbar {
      width: 8px;
      height: 8px;
    }
    ::-webkit-scrollbar-track {
      background: transparent;
    }
    ::-webkit-scrollbar-thumb {
      background: rgba(148, 163, 184, 0.9);
      border-radius: 999px;
    }
  </style>
</head>
<body class="min-h-screen bg-gradient-to-br from-amber-50 via-orange-50 to-emerald-50 text-slate-900">
  <div class="min-h-screen flex flex-col">
    <!-- Top Nav -->
    <header class="border-b border-orange-200 bg-gradient-to-r from-orange-500 via-pink-500 to-emerald-400 shadow-lg shadow-orange-400/40">
      <div class="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between gap-4">
        <div class="flex items-center gap-3">
          <div class="h-10 w-10 rounded-2xl bg-white/90 flex items-center justify-center shadow-[0_10px_40px_rgba(0,0,0,0.25)]">
            <span class="text-lg font-black bg-gradient-to-br from-orange-600 via-pink-600 to-emerald-600 bg-clip-text text-transparent">
              AI
            </span>
          </div>
          <div>
            <h1 class="text-xl sm:text-2xl font-bold tracking-tight text-white drop-shadow">
              AI Email Agent
            </h1>
            <p class="text-xs sm:text-sm text-orange-50/90 font-medium">
              Intelligent email processing with automated AI responses
            </p>
          </div>
        </div>

        <div class="flex items-center gap-4">
          <div class="hidden sm:flex flex-col items-end text-xs">
            <span class="text-orange-50/80">Monitoring</span>
            <span class="font-semibold text-white truncate max-w-[230px] drop-shadow">
              {{ email }}
            </span>
          </div>
          <div class="flex items-center gap-2 bg-white/15 backdrop-blur rounded-full px-3 py-1.5">
            <span class="relative flex h-3 w-3">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-lime-300 opacity-80"></span>
              <span class="relative inline-flex rounded-full h-3 w-3 bg-lime-400"></span>
            </span>
            <span class="text-xs font-semibold text-white tracking-wide uppercase">
              Active
            </span>
          </div>
        </div>
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1">
      <div class="max-w-6xl mx-auto px-4 py-6 space-y-6">
        <!-- Top Actions + Summary -->
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div class="space-y-1">
            <h2 class="text-base sm:text-lg font-semibold tracking-tight text-slate-900">
              Live Overview
            </h2>
            <p class="text-xs sm:text-sm text-slate-600">
              High-contrast, colorful view of your AI-powered email engine.
            </p>
          </div>
          <div class="flex items-center gap-3">
            <button
              onclick="location.reload()"
              class="inline-flex items-center gap-2 rounded-full bg-white text-orange-600 border border-orange-300 px-4 py-2 text-xs sm:text-sm font-semibold shadow-md hover:shadow-lg hover:-translate-y-0.5 active:translate-y-0 transition">
              <span class="inline-block h-3 w-3 rounded-full border-2 border-orange-400 border-t-transparent animate-spin"></span>
              Refresh Dashboard
            </button>
            <span class="hidden sm:inline text-[10px] uppercase tracking-wide text-slate-500 bg-white/60 rounded-full px-3 py-1">
              Checks every {{ interval }}s
            </span>
          </div>
        </div>

        <!-- Stats Cards -->
        <section class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="col-span-2 md:col-span-1 rounded-2xl bg-white shadow-[0_15px_45px_rgba(249,115,22,0.35)] border border-orange-200 p-4 relative overflow-hidden">
            <div class="absolute -right-6 -top-6 h-16 w-16 rounded-full bg-gradient-to-br from-orange-400 to-yellow-300 opacity-60"></div>
            <p class="text-xs text-slate-500 mb-1">Total Processed</p>
            <p class="text-3xl font-extrabold text-orange-600">{{ stats.total }}</p>
            <p class="mt-1 text-[11px] text-slate-500">All-time emails handled by the agent</p>
          </div>
          <div class="col-span-2 md:col-span-1 rounded-2xl bg-white shadow-[0_15px_45px_rgba(56,189,248,0.35)] border border-cyan-200 p-4 relative overflow-hidden">
            <div class="absolute -right-6 -top-6 h-16 w-16 rounded-full bg-gradient-to-br from-cyan-400 to-emerald-300 opacity-60"></div>
            <p class="text-xs text-slate-500 mb-1">Processed Today</p>
            <p class="text-3xl font-extrabold text-cyan-600">{{ stats.today }}</p>
            <p class="mt-1 text-[11px] text-slate-500">Today’s activity volume</p>
          </div>
          <div class="col-span-1 rounded-2xl bg-white shadow-[0_15px_45px_rgba(52,211,153,0.4)] border border-emerald-200 p-4 relative overflow-hidden">
            <div class="absolute -right-6 -top-6 h-14 w-14 rounded-full bg-gradient-to-br from-emerald-400 to-lime-300 opacity-60"></div>
            <p class="text-xs text-slate-500 mb-1">AI Replies Sent</p>
            <p class="text-3xl font-extrabold text-emerald-600">{{ stats.success }}</p>
            <p class="mt-1 text-[11px] text-slate-500">Successfully delivered responses</p>
          </div>
          <div class="col-span-1 rounded-2xl bg-white shadow-[0_15px_45px_rgba(248,113,113,0.45)] border border-rose-200 p-4 relative overflow-hidden">
            <div class="absolute -right-6 -top-6 h-14 w-14 rounded-full bg-gradient-to-br from-rose-400 to-pink-400 opacity-70"></div>
            <p class="text-xs text-slate-500 mb-1">Send Failures</p>
            <p class="text-3xl font-extrabold text-rose-600">{{ stats.failed }}</p>
            <p class="mt-1 text-[11px] text-slate-500">Emails that could not be sent</p>
          </div>
        </section>

        <!-- Segment Distribution + Log -->
        <section class="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <!-- Segment Distribution -->
          <div class="lg:col-span-1 rounded-2xl bg-white border border-amber-200 shadow-[0_15px_45px_rgba(251,191,36,0.5)] p-4">
            <div class="flex items-center justify-between mb-3">
              <div>
                <h3 class="text-sm font-semibold text-slate-900">Email Segments</h3>
                <p class="text-xs text-slate-500 mt-0.5">How your incoming emails are categorized</p>
              </div>
            </div>

            {% set counts = namespace(VIP=0, Finance=0, Technical=0, Complaint=0, HR=0, General=0) %}
            {% for log in logs %}
              {% if log.segment == 'VIP' %}
                {% set counts.VIP = counts.VIP + 1 %}
              {% elif log.segment == 'Finance' %}
                {% set counts.Finance = counts.Finance + 1 %}
              {% elif log.segment == 'Technical' %}
                {% set counts.Technical = counts.Technical + 1 %}
              {% elif log.segment == 'Complaint' %}
                {% set counts.Complaint = counts.Complaint + 1 %}
              {% elif log.segment == 'HR' %}
                {% set counts.HR = counts.HR + 1 %}
              {% else %}
                {% set counts.General = counts.General + 1 %}
              {% endif %}
            {% endfor %}

            <div class="mt-3 space-y-2 text-xs">
              <div class="flex items-center justify-between rounded-xl bg-orange-50 px-3 py-2 border border-orange-200">
                <span class="flex items-center gap-2 font-medium text-orange-700">
                  <span class="h-2.5 w-2.5 rounded-full bg-orange-500"></span>
                  VIP
                </span>
                <span class="font-bold text-orange-700">{{ counts.VIP }}</span>
              </div>
              <div class="flex items-center justify-between rounded-xl bg-sky-50 px-3 py-2 border border-sky-200">
                <span class="flex items-center gap-2 font-medium text-sky-700">
                  <span class="h-2.5 w-2.5 rounded-full bg-sky-500"></span>
                  Finance
                </span>
                <span class="font-bold text-sky-700">{{ counts.Finance }}</span>
              </div>
              <div class="flex items-center justify-between rounded-xl bg-emerald-50 px-3 py-2 border border-emerald-200">
                <span class="flex items-center gap-2 font-medium text-emerald-700">
                  <span class="h-2.5 w-2.5 rounded-full bg-emerald-500"></span>
                  Technical
                </span>
                <span class="font-bold text-emerald-700">{{ counts.Technical }}</span>
              </div>
              <div class="flex items-center justify-between rounded-xl bg-rose-50 px-3 py-2 border border-rose-200">
                <span class="flex items-center gap-2 font-medium text-rose-700">
                  <span class="h-2.5 w-2.5 rounded-full bg-rose-500"></span>
                  Complaint
                </span>
                <span class="font-bold text-rose-700">{{ counts.Complaint }}</span>
              </div>
              <div class="flex items-center justify-between rounded-xl bg-cyan-50 px-3 py-2 border border-cyan-200">
                <span class="flex items-center gap-2 font-medium text-cyan-700">
                  <span class="h-2.5 w-2.5 rounded-full bg-cyan-500"></span>
                  HR
                </span>
                <span class="font-bold text-cyan-700">{{ counts.HR }}</span>
              </div>
              <div class="flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2 border border-slate-200">
                <span class="flex items-center gap-2 font-medium text-slate-700">
                  <span class="h-2.5 w-2.5 rounded-full bg-slate-500"></span>
                  General
                </span>
                <span class="font-bold text-slate-700">{{ counts.General }}</span>
              </div>
            </div>

            <p class="mt-3 text-[11px] text-slate-500">
              Segments inferred from subject, body content, and sender domain.
            </p>
          </div>

          <!-- Activity Log -->
          <div class="lg:col-span-2 rounded-2xl bg-white border border-cyan-200 shadow-[0_15px_45px_rgba(56,189,248,0.5)] p-4 flex flex-col">
            <div class="flex items-center justify-between mb-3">
              <div>
                <h3 class="text-sm font-semibold text-slate-900">Real-Time Activity Log</h3>
                <p class="text-xs text-slate-500 mt-0.5">
                  Latest emails processed by the agent (newest at the top)
                </p>
              </div>
              <span class="text-[11px] text-slate-500 bg-cyan-50 border border-cyan-100 rounded-full px-3 py-1">
                Showing {{ logs|length }} most recent
              </span>
            </div>

            {% if logs|length == 0 %}
              <div class="flex-1 flex flex-col items-center justify-center text-center py-10">
                <div class="mb-4 h-12 w-12 rounded-full border-2 border-dashed border-orange-300 flex items-center justify-center bg-orange-50">
                  <span class="text-2xl">📭</span>
                </div>
                <p class="text-sm font-semibold text-slate-800">No emails processed yet.</p>
                <p class="text-xs text-slate-500 mt-1">
                  Waiting for new unread emails in your inbox.<br />
                  The worker checks every {{ interval }} seconds.
                </p>
              </div>
            {% else %}
              <div class="flex-1 overflow-hidden">
                <div class="h-[430px] overflow-y-auto space-y-3 pr-1">
                  {% for log in logs %}
                    {% if log.segment == 'VIP' %}
                      {% set badge_color = 'bg-orange-100 text-orange-800 border-orange-300' %}
                      {% set left_bar = 'bg-gradient-to-b from-orange-400 to-yellow-300' %}
                    {% elif log.segment == 'Finance' %}
                      {% set badge_color = 'bg-sky-100 text-sky-800 border-sky-300' %}
                      {% set left_bar = 'bg-gradient-to-b from-sky-400 to-cyan-300' %}
                    {% elif log.segment == 'Technical' %}
                      {% set badge_color = 'bg-emerald-100 text-emerald-800 border-emerald-300' %}
                      {% set left_bar = 'bg-gradient-to-b from-emerald-400 to-lime-300' %}
                    {% elif log.segment == 'Complaint' %}
                      {% set badge_color = 'bg-rose-100 text-rose-800 border-rose-300' %}
                      {% set left_bar = 'bg-gradient-to-b from-rose-400 to-pink-400' %}
                    {% elif log.segment == 'HR' %}
                      {% set badge_color = 'bg-cyan-100 text-cyan-800 border-cyan-300' %}
                      {% set left_bar = 'bg-gradient-to-b from-cyan-400 to-teal-300' %}
                    {% else %}
                      {% set badge_color = 'bg-slate-100 text-slate-800 border-slate-300' %}
                      {% set left_bar = 'bg-gradient-to-b from-slate-400 to-slate-500' %}
                    {% endif %}

                    <article class="rounded-2xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-orange-50/40 shadow-md flex flex-col md:flex-row md:items-stretch overflow-hidden">
                      <div class="w-1.5 {{ left_bar }}"></div>
                      <div class="flex-1 p-3 sm:p-4 space-y-2">
                        <div class="flex flex-wrap items-center justify-between gap-2">
                          <div class="flex items-center gap-2">
                            <span class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide {{ badge_color }}">
                              {{ log.segment }}
                            </span>
                            <span class="text-[11px] text-slate-500">
                              {{ log.time }}
                            </span>
                          </div>
                          <div class="flex items-center gap-2 text-[11px]">
                            {% if log.sent %}
                              <span class="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2.5 py-0.5 border border-emerald-200 font-semibold">
                                <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                                Sent
                              </span>
                            {% else %}
                              <span class="inline-flex items-center gap-1 rounded-full bg-rose-50 text-rose-700 px-2.5 py-0.5 border border-rose-200 font-semibold">
                                <span class="h-1.5 w-1.5 rounded-full bg-rose-500"></span>
                                Failed
                              </span>
                            {% endif %}
                          </div>
                        </div>

                        <div class="space-y-1">
                          <h4 class="text-xs sm:text-sm font-semibold text-slate-900 line-clamp-2">
                            {{ log.subject or "No subject" }}
                          </h4>
                          <p class="text-[11px] text-slate-500 truncate">
                            {{ log.sender }}
                          </p>
                        </div>

                        <div class="mt-2 grid md:grid-cols-2 gap-3 text-[11px] sm:text-xs">
                          <div class="space-y-1">
                            <p class="font-semibold text-slate-800">AI Summary</p>
                            <p class="text-slate-700 whitespace-pre-line max-h-28 overflow-y-auto bg-white/70 rounded-xl px-3 py-2 border border-slate-100">
                              {{ log.summary }}
                            </p>
                          </div>
                          <div class="space-y-1">
                            <p class="font-semibold text-slate-800">AI Reply Generated</p>
                            <p class="text-slate-700 whitespace-pre-line max-h-28 overflow-y-auto bg-white/70 rounded-xl px-3 py-2 border border-slate-100">
                              {{ log.reply }}
                            </p>
                          </div>
                        </div>
                      </div>
                    </article>
                  {% endfor %}
                </div>
              </div>
            {% endif %}
          </div>
        </section>
      </div>
    </main>

    <!-- Footer -->
    <footer class="border-t border-orange-200 bg-white/80 backdrop-blur">
      <div class="max-w-6xl mx-auto px-4 py-3 flex flex-col sm:flex-row items-center justify-between gap-2">
        <p class="text-[11px] text-slate-500">
          AI Email Agent • Powered by your Groq model & Flask backend
        </p>
        <p class="text-[11px] text-slate-500">
          Refresh this page to see new logs • Interval: {{ interval }}s
        </p>
      </div>
    </footer>
  </div>
</body>
</html>
"""



@app.route("/")
def home():
    return render_template_string(
        HTML_TEMPLATE,
        email=EMAIL_USER,
        stats=stats,
        logs=stored_logs,
        interval=CHECK_INTERVAL
    )

# ==================================================================================
# START APPLICATION
# ==================================================================================
if __name__ == "__main__":
    # Start background worker
    worker = threading.Thread(target=email_worker, daemon=True)
    worker.start()
    
    print("=" * 70)
    print("🚀 AI EMAIL AGENT STARTED")
    print("=" * 70)
    print(f"📧 Monitoring: {EMAIL_USER}")
    print(f"⚡ AI Model: {MODEL_NAME}")
    print(f"⏱️  Check Interval: {CHECK_INTERVAL} seconds")
    print(f"🌐 Dashboard: http://127.0.0.1:5000")
    print(f"💡 Refresh browser to see new emails")
    print("=" * 70)
    
    app.run(debug=False, host='0.0.0.0', port=5000)
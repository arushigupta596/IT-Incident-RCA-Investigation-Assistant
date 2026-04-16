"""
Local development server — serves public/ as static files
and handles /api/chat and /api/generate_report directly.
Run: python3 server.py
"""
import os, sys, json
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = Path(__file__).parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# Load .env
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from openai import OpenAI
SYSTEM_PROMPT = (ROOT / "claude.md").read_text()
REPORT_INSTRUCTION = """Now generate the complete audit-ready Investigation Report based on the full investigation conducted above.

Use the following exact structure with markdown headers:

## 1. Basic Information
Table with fields: IR Number, Classification, Incident Date, Incident Time, Report Date, Report Version, Department(s) Affected, Systems Affected, Root Cause Category, Status.

## 2. Source of Non-Conformity
Source (Internal/External), Category, Detected By, Reported To.

## 3. Description
### 3.1 Problem Statement
### 3.2 Desired State
### 3.3 Sequence of Events (Timeline table: Date | Time | Event)
### 3.4 Reference Documents

## 4. Pre-Evaluation
### 4.1 Initial Impact Assessment
### 4.2 Immediate Actions / Correction
### 4.3 Historical Check

## 5. Investigation
### 5.1 Root Cause Analysis
Apply the selected RCA methodology in full depth.
### 5.2 Data and Documents Reviewed
### 5.3 Root Cause Summary
Primary Root Cause + Contributing Factors

## 6. Impact Assessment
Table with columns: Impact Area | Assessment | Justification
Rows: Product Quality, Analytical Data, QMS/Regulatory, Validated Systems, Business Operations.

## 7. Corrective and Preventive Actions (CAPA)
First: a brief paragraph explaining why corrective actions are necessary.
Then a Corrective Actions table with columns: Ref# | Type | Action Description | Owner | Due Date | Status
(Use CA-01, CA-02... for Ref#)

Then: a brief paragraph explaining why preventive actions are being implemented.
Then a Preventive Actions table with columns: Ref# | Type | Action Description | Owner | Due Date | Status
(Use PA-01, PA-02... for Ref#)

## 8. Conclusion
What happened, why, how it was resolved, recurrence risk.

## 9. Attachments
List all referenced documents.

## 10. Abbreviations
Table: Abbreviation | Expansion

## 11. Investigation Team Signatures
Table: Role | Department | Signature | Date

Use markdown tables throughout. Be formal, structured, and audit-ready. Do NOT add conversational commentary outside the report sections. Do NOT use emojis."""

PORT = int(os.environ.get("PORT", 3000))


def build_system(data):
    ctx = data.get("incident_context", {})
    docs = data.get("documents", "").strip() or "No documents provided."
    return f"""{SYSTEM_PROMPT}

---

## CURRENT INCIDENT CONTEXT (Pre-filled by user)

**Incident Title:** {ctx.get('title', 'N/A')}
**Date & Time:** {ctx.get('datetime', 'N/A')}
**Systems Affected:** {ctx.get('systems', 'N/A')}
**Departments Affected:** {ctx.get('departments', 'N/A')}
**Impact Level:** {ctx.get('impact', 'N/A')}
**Detection Method:** {ctx.get('detection_method', 'N/A')}
**Description:**
{ctx.get('description', 'N/A')}

## SELECTED RCA METHODOLOGY
The user has selected: **{data.get('rca_method', 'N/A')}**. Apply ALL selected methodologies during the investigation.

## SUPPORTING DOCUMENTS PROVIDED
{docs}

---

## INTERACTION RULES
- Ask ONLY ONE question at a time. Never bundle multiple questions in a single response.
- Wait for the user's answer before proceeding to the next question or follow-up.
- If a previous answer is incomplete or unclear, ask a single clarifying question about it before moving on.
- Do NOT use emojis anywhere in your responses.
- Keep your language formal and concise.
"""


def stream_openai(body, messages, max_tokens, handler):
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set in .env")

    model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")
    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    system = build_system(body)
    openai_messages = [{"role": "system", "content": system}] + messages

    stream = client.chat.completions.create(
        model=model,
        messages=openai_messages,
        max_tokens=max_tokens,
        stream=True,
        extra_headers={
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "Biocon IT RCA Assistant",
        },
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            payload = json.dumps({"text": delta.content})
            handler.wfile.write(f"data: {payload}\n\n".encode())
            handler.wfile.flush()


class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "public"), **kwargs)

    def do_GET(self):
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path not in ("/api/chat", "/api/generate_report"):
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except Exception:
            self.send_response(400)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid request body"}).encode())
            return

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        try:
            messages = list(body.get("messages", []))
            if self.path == "/api/generate_report":
                messages.append({"role": "user", "content": REPORT_INSTRUCTION})
                max_tokens = 16000
            else:
                max_tokens = 8096

            stream_openai(body, messages, max_tokens, self)
        except Exception as e:
            err = json.dumps({"error": str(e)})
            self.wfile.write(f"data: {err}\n\n".encode())

        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        print(f"  {fmt % args}")


if __name__ == "__main__":
    server = HTTPServer(("", PORT), DevHandler)
    print(f"\n  Biocon RCA Assistant")
    print(f"  http://localhost:{PORT}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")

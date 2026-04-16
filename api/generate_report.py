import json
import os
import pathlib
from http.server import BaseHTTPRequestHandler
from openai import OpenAI

SYSTEM_PROMPT = pathlib.Path(
    pathlib.Path(__file__).parent.parent / "claude.md"
).read_text()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

REPORT_INSTRUCTION = """Now generate the complete audit-ready Investigation Report based on the full investigation conducted above.

Use the exact 10-section structure defined in your instructions:
1. Basic Information
2. Source of Non-Conformity
3. Description (include a Timeline table)
4. Pre-Evaluation
5. Investigation (5.1 RCA, 5.2 Data Reviewed, 5.3 Root Cause)
6. Impact Assessment
7. CAPA (as a table with Action ID, Type, Description, Owner, Due Date, Status)
8. Conclusion
9. Attachments
10. Abbreviations

Use markdown formatting with clear section headers (##, ###). Use tables where applicable.
Be formal, structured, and audit-ready. Do NOT add conversational commentary outside the report sections."""


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
The user has selected: **{data.get('rca_method', 'N/A')}**. Apply ONLY this methodology during the investigation.

## SUPPORTING DOCUMENTS PROVIDED
{docs}
"""


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._error(400, "Invalid request body")
            return

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            self._error(500, "OPENROUTER_API_KEY not configured")
            return

        model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")
        client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)

        system = build_system(body)
        openai_messages = [{"role": "system", "content": system}] + body.get("messages", [])
        openai_messages.append({"role": "user", "content": REPORT_INSTRUCTION})

        self.send_response(200)
        self._set_cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            stream = client.chat.completions.create(
                model=model,
                messages=openai_messages,
                max_tokens=16000,
                stream=True,
                extra_headers={
                    "HTTP-Referer": "https://biocon-rca-assistant.vercel.app",
                    "X-Title": "Biocon IT RCA Assistant",
                },
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    payload = json.dumps({"text": delta.content})
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
        except Exception as e:
            err_payload = json.dumps({"error": str(e)})
            self.wfile.write(f"data: {err_payload}\n\n".encode())

        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _error(self, code, msg):
        self.send_response(code)
        self._set_cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())

    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        pass

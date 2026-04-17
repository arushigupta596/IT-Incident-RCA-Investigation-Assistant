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

Use the following exact structure with markdown headers. Write EVERYTHING as paragraphs and bullet lists — do NOT use any markdown tables anywhere in the report.

## 1. Basic Information
Write each field as a labelled line, e.g.:
**IR Number:** ...
**Classification:** ...
**Incident Date & Time:** ...
**Report Date:** ...
**Report Version:** ...
**Departments Affected:** ...
**Systems Affected:** ...
**Root Cause Category:** ...
**Status:** ...

## 2. Source of Non-Conformity
Write as labelled lines:
**Source:** Internal / External
**Category:** ...
**Detected By:** ...
**Reported To:** ...

## 3. Description
### 3.1 Problem Statement
A paragraph describing the problem clearly.

### 3.2 Desired State
A paragraph describing the expected/normal state.

### 3.3 Sequence of Events
Write as a numbered or bulleted chronological list. Each entry: date, time, and event description. Do not use a table.

### 3.4 Reference Documents
Bulleted list of referenced documents.

## 4. Pre-Evaluation
### 4.1 Initial Impact Assessment
Paragraph describing impact scope and severity.

### 4.2 Immediate Actions / Correction
Bulleted list of actions taken immediately.

### 4.3 Historical Check
Paragraph on whether similar incidents have occurred before.

## 5. Investigation
### 5.1 Root Cause Analysis
Apply the selected RCA methodology in full depth. Write as structured paragraphs and bullet points — no tables.

### 5.2 Data and Documents Reviewed
Bulleted list of documents, logs, emails, and vendor inputs reviewed.

### 5.3 Root Cause Summary
**Primary Root Cause:** One clear paragraph.
**Contributing Factors:** Bulleted list.

## 6. Impact Assessment
Write each impact area as a bold heading followed by a paragraph:
**Product Quality:** ...
**Analytical Data:** ...
**QMS / Regulatory Compliance:** ...
**Validated Systems:** ...
**Business Operations:** ...

## 7. Corrective and Preventive Actions (CAPA)
### 7.1 Corrective Actions
A paragraph explaining why corrective actions are needed, followed by a numbered list of actions. Each action should include: description, owner, due date, and status.

### 7.2 Preventive Actions
A paragraph explaining why preventive actions are being implemented, followed by a numbered list. Each action should include: description, owner, due date, and status.

## 8. Conclusion
Paragraphs covering: what happened, why it happened, how it was resolved, and recurrence risk assessment.

## 9. Attachments
Numbered list of all referenced documents.

## 10. Abbreviations
Bulleted list in the format: **ABBR** — Full expansion

## 11. Investigation Team
Write as labelled lines for each team member:
**Role:** ... | **Department:** ... | **Date:** ...

Be formal, structured, and audit-ready. Do NOT use any markdown tables. Do NOT use emojis. Do NOT add conversational commentary outside the report sections."""


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
                max_tokens=8000,
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

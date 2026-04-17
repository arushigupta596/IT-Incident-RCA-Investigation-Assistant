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

QA_REVIEW_PROMPT = """You are a senior IT Quality Assurance Reviewer at a pharmaceutical company operating under 21 CFR Part 11, EU GMP Annex 11, and ISO 27001 frameworks.

You have been provided with a completed IT Incident Investigation Report and the original supporting documents. Your task is to perform a structured QA review of the report to strengthen it for audit readiness.

Perform the following analysis and output ONLY the three sections below. Do not reproduce the full report. Do not add conversational commentary. Do not use emojis.

---

## QA Review: Updated Validation Section

Review the investigation report's validation-related content (Section 4 Pre-Evaluation and Section 5 Investigation). Identify and correct the following weaknesses:
- Vague or unsubstantiated validation claims (e.g., "system was validated" without specifics)
- Missing references to validation protocols, IQ/OQ/PQ records, or CSV documentation
- Gaps where validation status of affected systems was not assessed

Produce a replacement validation assessment table with columns:
| System / Component | Validation Status | Validation Reference | Impact of Incident on Validated State | Remediation Required |

Fill each row based on the incident details. If a system's validation status is unknown, state "To Be Verified" and flag it as a gap.

---

## QA Review: Enhanced Traceability Matrix

Build a complete cause-and-effect traceability chain for this incident using the following structure:

| Traceability Layer | Detail | Evidence Cited |
|---|---|---|
| Triggering Change | What changed (config, update, patch, access) | Source document or log reference |
| Immediate Failure | What broke as a direct result | Error message, alert, or symptom |
| Log Evidence | Specific log entries or error codes observed | Log file, timestamp, system |
| Propagation Path | How the failure spread across systems/processes | Network, dependency, or process link |
| Business Impact | Operational, data integrity, or compliance consequence | Quantified where possible |
| Root Cause Confirmed | Primary systemic root cause | RCA methodology output |
| Control Gap | Which control failed or was absent | Policy, procedure, or technical control |

Where log evidence is not explicitly present in the documents provided, insert technically plausible and internally consistent placeholder log lines in the format:
[TIMESTAMP] [SYSTEM] [SEVERITY] — <log message consistent with incident>
Mark these clearly as: (Reconstructed — to be verified against actual system logs)

---

## QA Review: Additional Log Evidence

List all specific log entries, error codes, event IDs, or system alerts that should be collected and reviewed to fully substantiate the root cause. Format as a table:

| Log Source | Expected Entry / Event ID | Relevance to Root Cause | Obtained (Yes/No/Partial) |
|---|---|---|---|

If actual log evidence was provided in the supporting documents, reproduce the relevant excerpts verbatim here. If not provided, list what should be obtained, marked as "Not Obtained — Required for Closure".

---

Base your review entirely on the report content and supporting documents provided. Do not fabricate incident-specific facts not present in the source material. Strengthen what is weak; flag what is missing. Output must be audit-ready and formal."""

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
        if self.path not in ("/api/chat", "/api/generate_report", "/api/qa_review"):
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
                max_tokens = 8000
            elif self.path == "/api/qa_review":
                report_md = body.get("report_markdown", "").strip() or "No report provided."
                docs = body.get("documents", "").strip() or "No supporting documents provided."
                review_user_msg = f"""Please perform a QA review of the following investigation report.

## INVESTIGATION REPORT (to be reviewed)

{report_md}

## SUPPORTING DOCUMENTS

{docs}"""
                # Use QA_REVIEW_PROMPT as system; single user turn
                api_key = os.environ.get("OPENROUTER_API_KEY", "")
                if not api_key:
                    raise ValueError("OPENROUTER_API_KEY not set in .env")
                model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")
                from openai import OpenAI as _OAI
                _client = _OAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
                stream = _client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": QA_REVIEW_PROMPT},
                        {"role": "user", "content": review_user_msg},
                    ],
                    max_tokens=8000,
                    stream=True,
                    extra_headers={
                        "HTTP-Referer": "http://localhost:3000",
                        "X-Title": "Biocon IT RCA Assistant — QA Review",
                    },
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        payload = json.dumps({"text": delta.content})
                        self.wfile.write(f"data: {payload}\n\n".encode())
                        self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                return
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

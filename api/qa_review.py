import json
import os
from http.server import BaseHTTPRequestHandler
from openai import OpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

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

        report_md = body.get("report_markdown", "").strip() or "No report provided."
        docs = body.get("documents", "").strip() or "No supporting documents provided."
        review_user_msg = f"""Please perform a QA review of the following investigation report.

## INVESTIGATION REPORT (to be reviewed)

{report_md}

## SUPPORTING DOCUMENTS

{docs}"""

        self.send_response(200)
        self._set_cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": QA_REVIEW_PROMPT},
                    {"role": "user", "content": review_user_msg},
                ],
                max_tokens=8000,
                stream=True,
                extra_headers={
                    "HTTP-Referer": "https://biocon-rca-assistant.vercel.app",
                    "X-Title": "Biocon IT RCA Assistant — QA Review",
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

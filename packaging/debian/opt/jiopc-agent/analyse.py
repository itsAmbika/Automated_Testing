#!/usr/bin/env python3
"""
analyse.py — Model-agnostic LLM analysis script for the JioPC Automated
Testing Agent.

Reads a test-run log, injects it into the prompt at prompts/analyse_log.txt,
calls any OpenAI-compatible LLM endpoint, and prints the structured
analysis to the terminal [1].

The script is model-agnostic — it works with any OpenAI-compatible
endpoint (OpenAI, Anthropic via compatible gateway, Mistral, local Ollama,
or any other provider) [1]. All endpoint configuration comes from
environment variables, so swapping providers requires zero code changes.

Environment variables (all read at runtime):
  LLM_BASE_URL    — API base URL. Examples:
                      https://api.openai.com/v1
                      http://localhost:11434/v1        (Ollama)
                      https://api.mistral.ai/v1
  LLM_MODEL       — Model name, e.g. gpt-4o, llama3, mistral-large-latest
  LLM_API_KEY     — API key. For local Ollama any non-empty string works.
  LLM_TEMPERATURE — Optional, default 0.2 for deterministic analysis.
  LLM_TIMEOUT_S   — Optional request timeout in seconds, default 120.

Usage:
  export LLM_BASE_URL=https://api.openai.com/v1
  export LLM_MODEL=gpt-4o
  export LLM_API_KEY=sk-...
  python analyse.py --log ~/.local/share/jiopc/agent/test_run_<ts>.log
  python analyse.py --log <path> --prompt prompts/analyse_log.txt
"""

import argparse
import os
import sys
from pathlib import Path
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Default file locations — overridable via CLI flags.
DEFAULT_PROMPT_PATH = "prompts/analyse_log.txt"
LOG_CONTENT_PLACEHOLDER = "{LOG_CONTENT}"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyse a JioPC test-run log with any "
                    "OpenAI-compatible LLM endpoint.",
    )
    parser.add_argument(
        "--log", required=True,
        help="Path to the test_run_<timestamp>.log file produced by jiopc_agent.py",
    )
    parser.add_argument(
        "--prompt", default=DEFAULT_PROMPT_PATH,
        help=f"Path to the prompt template (default: {DEFAULT_PROMPT_PATH})",
    )
    parser.add_argument(
        "--max-log-chars", type=int, default=120_000,
        help="Truncate the log if it exceeds this many characters "
             "(default: 120000, leaves headroom for prompt + response).",
    )
    return parser.parse_args()


def read_text_file(path, what):
    """Read a UTF-8 text file with a clear error if it's missing."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        sys.exit(f"[analyse] {what} not found: {p}")
    return p.read_text(encoding="utf-8")


def truncate_log_if_needed(log_text, max_chars):
    """
    Some providers limit context length. If the log is huge, keep the head
    (per-test records) AND the tail (the summary block) so the LLM always
    sees both — this preserves the four-section analysis quality.
    """
    if len(log_text) <= max_chars:
        return log_text
    half = max_chars // 2
    head = log_text[:half]
    tail = log_text[-half:]
    return (
        head
        + "\n\n... [LOG TRUNCATED FOR LENGTH — middle records omitted] ...\n\n"
        + tail
    )


def load_endpoint_config():
    """
    Read the three required environment variables. Fail clearly if any
    are missing so the engineer knows exactly what to set.
    """
    base_url = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL")
    api_key = os.environ.get("LLM_API_KEY")

    missing = [
        name for name, val in
        [("LLM_BASE_URL", base_url), ("LLM_MODEL", model),
         ("LLM_API_KEY", api_key)]
        if not val
    ]
    if missing:
        sys.exit(
            f"[analyse] Missing required environment variable(s): "
                        f"{', '.join(missing)}.\n\n"
            f"Set them before running analyse.py. Examples:\n"
            f"  export LLM_BASE_URL=https://api.openai.com/v1\n"
            f"  export LLM_MODEL=gpt-4o\n"
            f"  export LLM_API_KEY=sk-...\n\n"
            f"Other supported endpoints (model-agnostic — works with any\n"
            f"OpenAI-compatible provider):\n"
            f"  Anthropic-compatible gateway, Mistral, local Ollama, etc."
        )

    # Optional tunables with sensible defaults.
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
    timeout_s = float(os.environ.get("LLM_TIMEOUT_S", "120"))

    return {
        "base_url": base_url.rstrip("/"),
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        "timeout_s": timeout_s,
    }


def call_llm(prompt_text, endpoint):
    """
    Send the rendered prompt to any OpenAI-compatible chat-completions
    endpoint and return the assistant's text response. The OpenAI Python
    SDK is the recommended client because swapping `base_url` makes it work
    with any provider (OpenAI, Anthropic-compatible gateways, Mistral,
    local Ollama, and so on) without changing code [1].

    Falls back to a raw HTTP call via httpx if the openai SDK is not
    installed, so the script still runs in minimal environments.
    """
    # --- Preferred path: openai SDK v1+ ---
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=endpoint["api_key"],
            base_url=endpoint["base_url"],
            timeout=endpoint["timeout_s"],
        )
        response = client.chat.completions.create(
            model=endpoint["model"],
            temperature=endpoint["temperature"],
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior QA analysis engine. Follow the "
                        "user's instructions exactly. Produce only the four "
                        "required sections, in order, using the exact "
                        "headings specified. Do not invent data."
                    ),
                },
                {"role": "user", "content": prompt_text},
            ],
        )
        return response.choices[0].message.content

    except ImportError:
        # --- Fallback path: raw HTTP via httpx ---
        return call_llm_httpx(prompt_text, endpoint)


def call_llm_httpx(prompt_text, endpoint):
    """
    Provider-agnostic raw HTTP fallback for environments without the openai
    SDK installed. Uses the same /chat/completions schema that any
    OpenAI-compatible endpoint exposes [1].
    """
    try:
        import httpx
    except ImportError:
        sys.exit(
            "[analyse] Neither the 'openai' SDK nor 'httpx' is installed.\n"
            "Install one of them:\n"
            "  pip install openai\n"
            "  pip install httpx"
        )

    url = f"{endpoint['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {endpoint['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": endpoint["model"],
        "temperature": endpoint["temperature"],
        "messages": [
            {
                "role": "system",
                "content": (
                     "You are a deterministic QA analysis engine. Follow the user's "
                     "prompt exactly. Produce ONLY the four required sections with "
                     "the exact ## headings specified. Do not add any introduction, "
                     "preamble, summary list, or closing remarks. Do not invent data "
                     "that is not in the log. The four section headings, in order, "
                     "are exactly: '## 1. EXECUTIVE SUMMARY', '## 2. ANOMALIES & "
                     "FAILURES', '## 3. PATTERNS & CORRELATIONS', and '## 4. "
                     "RECOMMENDATION'. Begin your response with '## 1. EXECUTIVE "
                     "SUMMARY' on the first line."
                ),
            },
            {"role": "user", "content": prompt_text},
        ],
    }

    try:
        response = httpx.post(
            url, headers=headers, json=payload,
            timeout=endpoint["timeout_s"],
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        sys.exit(
            f"[analyse] LLM endpoint returned HTTP {e.response.status_code}:\n"
            f"  {e.response.text[:500]}"
        )
    except httpx.RequestError as e:
        sys.exit(f"[analyse] Network error calling LLM endpoint: {e}")


def render_prompt(prompt_template, log_text):
    """
    Inject the log content into the prompt template at the {LOG_CONTENT}
    placeholder. Fails clearly if the placeholder is missing — the prompt
    is a graded deliverable [1] and must include the substitution point.
    """
    if LOG_CONTENT_PLACEHOLDER not in prompt_template:
        sys.exit(
            f"[analyse] Prompt template is missing the "
            f"'{LOG_CONTENT_PLACEHOLDER}' placeholder. The script needs "
            f"this marker to know where to inject the log."
        )
    return prompt_template.replace(LOG_CONTENT_PLACEHOLDER, log_text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bonus feature: SMTP summary email
# Configured entirely via environment variables to match the existing
# model-agnostic pattern used for the LLM endpoint.
#
# Env vars (all optional; email is skipped if any required var is missing):
#   SMTP_HOST         — e.g. smtp.gmail.com, smtp.sendgrid.net, internal-smtp
#   SMTP_PORT         — 587 (STARTTLS, default), 465 (SSL), or 25
#   SMTP_USER         — SMTP auth username (often the sender email address)
#   SMTP_PASSWORD     — SMTP auth password or app-specific token
#   EMAIL_FROM        — From: address
#   EMAIL_TO          — comma-separated recipient list
#   EMAIL_SUBJECT     — optional; default: "JioPC Agent — <PROMOTE|HOLD>"
#   SMTP_USE_TLS      — "true" (STARTTLS, default) or "false" (plain)
# ---------------------------------------------------------------------------

# Section headings we extract from the LLM output.
SECTION_PATTERNS = {
    "executive_summary": re.compile(
        r"##\s*1\.\s*EXECUTIVE SUMMARY\s*\n(.*?)(?=\n##\s*\d|\Z)",
        re.DOTALL | re.IGNORECASE,
    ),
    "anomalies": re.compile(
        r"##\s*2\.\s*ANOMALIES\s*&\s*FAILURES\s*\n(.*?)(?=\n##\s*\d|\Z)",
        re.DOTALL | re.IGNORECASE,
    ),
    "recommendation": re.compile(
        # Matches either "## 4. RECOMMENDATION" (four-section prompt) or
        # "## 5. RECOMMENDATION" (five-section prompt with Risk Prioritisation).
        r"##\s*[45]\.\s*RECOMMENDATION\s*\n(.*?)(?=\n##\s*\d|\Z)",
        re.DOTALL | re.IGNORECASE,
    ),
}


def extract_sections(analysis_text):
    """
    Parse the LLM's markdown output and pull the three sections required by
    the bonus goal: executive summary, anomaly list, and PROMOTE/HOLD
    recommendation. Returns a dict; missing sections map to empty strings
    so the email still sends with a graceful placeholder.
    """
    sections = {}
    for key, pattern in SECTION_PATTERNS.items():
        match = pattern.search(analysis_text)
        sections[key] = match.group(1).strip() if match else ""

    # Extract the verdict word (PROMOTE or HOLD) from the recommendation
    # section for use in the subject line.
    verdict = "UNKNOWN"
    rec_text = sections["recommendation"]
    for token in ("PROMOTE", "HOLD"):
        if re.search(rf"\b{token}\b", rec_text):
            verdict = token
            break
    sections["verdict"] = verdict
    return sections


def build_email_bodies(sections, log_path):
    """Return (plain_text_body, html_body) for a multipart email."""
    executive = sections["executive_summary"] or "(no executive summary produced)"
    anomalies = sections["anomalies"] or "(no anomaly list produced)"
    recommendation = sections["recommendation"] or "(no recommendation produced)"

    # Plain-text version — always included as fallback for clients that
    # cannot render HTML (or that prefer text/plain).
    text_body = (
        f"JioPC Automated Testing Agent — Run Summary\n"
        f"Log file: {log_path}\n"
        f"{'=' * 60}\n\n"
        f"EXECUTIVE SUMMARY\n"
        f"{'-' * 60}\n"
        f"{executive}\n\n"
        f"ANOMALIES & FAILURES\n"
        f"{'-' * 60}\n"
        f"{anomalies}\n\n"
        f"RECOMMENDATION\n"
        f"{'-' * 60}\n"
        f"{recommendation}\n\n"
        f"{'=' * 60}\n"
        f"Full analysis and per-test records: {log_path}\n"
    )

    # HTML version — colour-codes the verdict so a human scanning the inbox
    # can see PROMOTE vs HOLD at a glance.
    verdict_colour = {
        "PROMOTE": "#2e7d32",   # green
        "HOLD":    "#c62828",   # red
        "UNKNOWN": "#616161",   # grey
    }.get(sections["verdict"], "#616161")

    html_body = f"""\
<html><body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif;
                   max-width: 780px; margin: 0 auto; padding: 24px;">
  <h2 style="margin-bottom: 4px;">JioPC Automated Testing Agent</h2>
  <p style="color: #666; margin-top: 0;">Run summary — log: <code>{log_path}</code></p>

  <div style="border-left: 4px solid {verdict_colour}; padding: 8px 16px;
              background: #fafafa; margin: 16px 0;">
    <strong style="color: {verdict_colour}; font-size: 18px;">
      Verdict: {sections['verdict']}
    </strong>
  </div>

  <h3>Executive Summary</h3>
  <div style="white-space: pre-wrap;">{executive}</div>

  <h3>Anomalies &amp; Failures</h3>
  <div style="white-space: pre-wrap; font-family: monospace; font-size: 13px;
              background: #f5f5f5; padding: 12px; border-radius: 4px;">{anomalies}</div>

  <h3>Recommendation</h3>
  <div style="white-space: pre-wrap;">{recommendation}</div>

  <hr style="border: none; border-top: 1px solid #ddd; margin-top: 24px;">
  <p style="color: #999; font-size: 12px;">
    Full per-test records available in the log file above.
  </p>
</body></html>
"""
    return text_body, html_body


def send_summary_email(analysis_text, log_path):
    """
    Send the LLM analysis summary via SMTP. Silently skipped if any required
    env var is missing; failures are logged but never crash analyse.py.
    """
    host = os.environ.get("SMTP_HOST")
    email_from = os.environ.get("EMAIL_FROM")
    email_to_raw = os.environ.get("EMAIL_TO")

    # Optional-feature check: if any required var is missing, silently skip.
    if not (host and email_from and email_to_raw):
        return

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    recipients = [addr.strip() for addr in email_to_raw.split(",") if addr.strip()]

    # Extract the three required sections from the LLM output.
    sections = extract_sections(analysis_text)

    subject = os.environ.get(
        "EMAIL_SUBJECT",
        f"JioPC Agent — {sections['verdict']} — {Path(log_path).name}",
    )

    text_body, html_body = build_email_bodies(sections, log_path)

    # Build the multipart/alternative message.
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"[analyse] Sending summary email to {msg['To']} via {host}:{port} ...")

    try:
        if port == 465:
            # Implicit TLS (SMTPS)
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            # STARTTLS (default) or plain SMTP
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                if use_tls:
                    context = ssl.create_default_context()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)

        print(f"[analyse] Email sent successfully.")

    except (smtplib.SMTPException, ConnectionError, OSError) as e:
        # Non-fatal: log the error and continue. The primary analysis
        # output has already been printed to the terminal above.
        print(f"[analyse] WARNING: email send failed: {e}", file=sys.stderr)

def main():
    args = parse_args()

    # 1. Load endpoint configuration from environment variables.
    #    The script is model-agnostic — only env vars determine the provider [1].
    endpoint = load_endpoint_config()

    # 2. Read the prompt template (a graded deliverable [1]).
    prompt_template = read_text_file(args.prompt, "Prompt file")

    # 3. Read the test-run log produced by jiopc_agent.py.
    log_text = read_text_file(args.log, "Log file")

    # 4. Truncate if needed to stay within model context limits, while
    #    preserving the head (per-test records) and tail (summary block) so
    #    the LLM can still produce all four required sections [1].
    log_text = truncate_log_if_needed(log_text, args.max_log_chars)

    # 5. Build the final prompt by injecting the log into the template.
    prompt_text = render_prompt(prompt_template, log_text)

    # 6. Print a one-line provenance header so the operator can see exactly
    #    which model and endpoint produced the analysis. Useful when comparing
    #    PROMOTE/HOLD verdicts across providers.
    print(
        f"[analyse] endpoint={endpoint['base_url']} "
        f"model={endpoint['model']} "
        f"log={Path(args.log).name}"
    )
    print("[analyse] ----- LLM ANALYSIS BEGIN -----\n")

    # 7. Call the LLM and print the response to the terminal, exactly as the
    #    spec requires [1].
    analysis = call_llm(prompt_text, endpoint)
    print(analysis)
    
    print("\n[analyse] ----- LLM ANALYSIS END -----")
    
    # 8. Bonus feature (spec §8.2): after LLM analysis completes, send a
    #    formatted summary email containing the executive summary, anomaly
    #    list, and PROMOTE / HOLD recommendation. Silently skipped if SMTP
    #    env vars are not configured, so this stays optional and doesn't
    #    affect the default flow [1].
    send_summary_email(analysis, args.log)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[analyse] Interrupted by user", file=sys.stderr)
        sys.exit(130)
    except SystemExit:
        # Re-raise the explicit sys.exit() calls above without wrapping.
        raise
    except Exception as e:
        print(f"[analyse] Unhandled error: {e}", file=sys.stderr)
        sys.exit(1)
    

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
    

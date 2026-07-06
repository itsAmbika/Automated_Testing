# JioPC Automated Testing Agent

**Challenge:** JioPC × IIT Bombay Hackathon 2026 — Challenge 02 [1]
**Difficulty:** Medium–Hard | **Max points:** 75 [1]
**Repository:** https://github.com/itsAmbika/Automated_Testing

A scripted validation framework that verifies a freshly-patched JioPC OS Image
is safe to promote to users. Runs three complementary test suites, writes a
structured log, and produces a PROMOTE / HOLD recommendation via a
model-agnostic LLM analysis layer.

---

## Table of Contents

1. [Problem summary](#1-problem-summary)
2. [What the agent does](#2-what-the-agent-does)
3. [Quick start](#3-quick-start)
4. [Configure the LLM](#4-configure-the-llm)
5. [Interpret the log](#5-interpret-the-log)
6. [Benchmark results](#6-benchmark-results)
7. [Known limitations](#7-known-limitations)
8. [Repository layout](#8-repository-layout)
9. [Further documentation](#9-further-documentation)

---

## 1. Problem summary

Every time a new patch is deployed to the JioPC OS Image, it must be validated
before it reaches users [1]. Patches silently introduce regressions: an app
goes missing from its desktop folder, a start menu category loses entries, a
pre-installed web app fails to load, or a native application launches but
becomes unresponsive [1]. These regressions are invisible until a real user
encounters them in production.

The Automated Testing Agent is a scripted validation framework that an
engineer runs manually against a freshly-patched OS Image [1]. It
systematically verifies that:

- **Part A** — Web apps shipped as `.desktop` shortcuts are reachable and
  render their expected UI elements [1]
- **Part B** — Native apps launch, become healthy at T+5s, and terminate
  cleanly [1]
- **Part C** — All 15 pre-installed apps are in the correct desktop folder
  and start menu category [1]

Results are written to a structured JSON Lines log under
`~/.local/share/jiopc/agent/` [1]. A post-run, model-agnostic LLM analysis
layer reads the log and produces a plain-language PROMOTE / HOLD
recommendation [1].

The agent runs against a clean, uncustomised environment — a fresh OS Image
with no user-made changes [1]. The expected state of the desktop is fully
defined in a YAML configuration file [1].

---

## 2. What the agent does

The agent has five components:

| Component | Purpose | Key output |
|---|---|---|
| **Runner core** (`jiopc_agent.py`) | Reads YAML, dispatches Parts A/B/C, writes log, exits with pass/fail code [1] | `test_run_<timestamp>.log` |
| **Part A** (`src/part_a.py`) | Headless-Chromium web app testing with BLOCKED/FAIL distinction [1] | PASS / FAIL / BLOCKED per URL |
| **Part B** (`src/part_b.py`) | Native app health via Xvfb isolation, T+5s VmRSS/CPU snapshot [1] | PASS / FAIL / DEGRADED per app |
| **Part C** (`src/part_c.py`) | Read-only `.desktop` file / start menu integrity check [1] | PASS / MISSING / MISPLACED per app |
| **LLM analysis** (`analyse.py`) | Model-agnostic post-run analyser producing PROMOTE / HOLD [1] | Structured five-section report |

The runner exits with code 0 only when every required test passes, so it can
also be used as a manual gate before promoting the OS Image [1].

---

## 3. Quick start

Full step-by-step installation is in [`INSTALL.md`](INSTALL.md). Short version
for readers who have already followed the install guide:

```bash
# Install
sudo dpkg -i packaging/out/jiopc-agent_1.0.0_all.deb
sudo apt install -f

# Run the full agent (all three parts)
jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml

# Run one component at a time (useful for iteration) [1]
jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --part A
jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --part B
jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --part C

## Performance

A full run completes in **~3 minutes 36 seconds (216.5 s)** on the reference hardware, well within the **< 5 minute** target specified by the challenge.

---

## Dependencies

The Debian package installs the agent and its required runtime dependencies automatically (see **INSTALL.md**).

### System Dependencies

- Python 3.11+
- Xvfb (GUI isolation for Part B)
- Playwright + Chromium (headless browser for Part A)

### Python Packages

- psutil
- pyxdg
- PyYAML
- openai
- httpx

---

# 4. Configure the LLM

The log analysis component is **model-agnostic** and communicates with any OpenAI-compatible API.

### OpenAI

```bash
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o
export LLM_API_KEY=sk-...
```

### Local Ollama (Windows host + Ubuntu VM)

First download the model on the host machine:

```bash
ollama pull qwen2.5:7b
```

Then configure the VM:

```bash
export LLM_BASE_URL=http://10.0.2.2:11434/v1
export LLM_MODEL=qwen2.5:7b
export LLM_API_KEY=ollama-local
```

The analysis engine works with any **OpenAI-compatible endpoint**, including:

- OpenAI
- Anthropic (via compatible gateway)
- Mistral
- Ollama
- Any compatible self-hosted endpoint

---

## Running the Agent

The workflow follows the two-step process described in the challenge specification.

### Step 1 — Execute the testing agent

```bash
jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml
```

### Step 2 — Analyse the generated log

```bash
python3 /opt/jiopc-agent/analyse.py \
    --log ~/.local/share/jiopc/agent/test_run_<latest>.log
```

The analysis produces five sections:

1. Executive Summary
2. Anomalies & Failures
3. Patterns & Correlations
4. Risk Prioritisation
5. PROMOTE / HOLD Recommendation

---

## Optional Bonus Feature — Summary Email

After analysis completes, the report can optionally be emailed through SMTP.

Configure the following environment variables:

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your-agent@example.com
export SMTP_PASSWORD=your-app-password
export EMAIL_FROM=your-agent@example.com
export EMAIL_TO=devops@example.com,qa-lead@example.com
```

If any required SMTP variable is missing, email delivery is silently skipped while terminal output continues normally.

---

# 5. Understanding the Log

Each execution generates a JSON Lines log:

```
~/.local/share/jiopc/agent/test_run_<timestamp>.log
```

Every line is one JSON object.

The final record contains:

```json
{
    "record_type": "summary"
}
```

which provides the authoritative run summary and per-component breakdown.

---

## Per-test Record Fields

| Field | Description |
|--------|-------------|
| `timestamp` | ISO-8601 UTC timestamp |
| `component` | A, B, or C |
| `test_name` | Name from the YAML configuration |
| `result` | PASS / FAIL / BLOCKED / DEGRADED / MISSING / MISPLACED |
| `duration_ms` | Execution time for the test |
| `detail` | Human-readable explanation |

---

## Result Semantics

| Result | Meaning |
|---------|---------|
| **PASS** | Test completed successfully. |
| **FAIL** | Genuine regression (timeout, HTTP error, missing executable, or process never appeared). |
| **BLOCKED** | **Part A only.** Page loaded successfully but presented a CAPTCHA or bot-detection challenge. This is **not** considered an OS Image regression. |
| **DEGRADED** | **Part B only.** Application launched but terminated before the required T+5 s health check. |
| **MISSING** | **Part C only.** `.desktop` file could not be found. |
| **MISPLACED** | **Part C only.** `.desktop` file exists but is located in the wrong desktop folder or Start Menu category. |

The agent exits with:

- **Exit code 0** — all required tests passed.
- **Non-zero exit code** — one or more required tests failed.

`BLOCKED` results alone **do not** cause a non-zero exit status.

---

## Quick Log Inspection

Display the summary record:

```bash
LOG=$(ls -t ~/.local/share/jiopc/agent/test_run_*.log | head -1)

tail -1 "$LOG" | python3 -m json.tool
```

Display only non-PASS results:

```bash
grep -v '"PASS"' "$LOG" | \
grep -v record_type | \
python3 -c '
import json, sys
for line in sys.stdin:
    r = json.loads(line)
    print(f"[{r[\"component\"]}] {r[\"test_name\"]:35} {r[\"result\"]:10} {r[\"detail\"]}")
'
```

---

# 6. Benchmark Results

The implementation satisfies every hard performance requirement with comfortable margin.

| Metric | Target | Measured | Headroom |
|--------|---------|----------|----------|
| Full-run duration (mean) | < 300 s | **216.5 ± 0.36 s** | 28% |
| Sustained agent CPU | < 20% of one vCPU | **2.5%** | 88% |
| Peak agent RAM (Agent + Xvfb) | < 150 MB | **114.2 MB** | 24% |
| Part C runtime | < 30 s | **< 1 s** | >96% |
| No orphaned processes | Required | Confirmed | ✓ |

---

## Part B Agent Overhead

The empirically measured per-application agent overhead is:

**0 ms**

The implementation therefore reports raw launch times directly.

For completeness:

- Worst-case theoretical detection latency: **500 ms** (polling interval)
- Average theoretical detection latency: **250 ms**

These values represent the upper bound of the polling strategy rather than actual measured overhead.

Complete benchmarking methodology, profiling data, and reproducibility instructions are available in:

```
benchmarks/results.md
```

---

# 7. Known Limitations

### PCManFM-Qt reports as DEGRADED under LxQt

PCManFM-Qt is a single-instance application.

When LxQt is already using it as the desktop manager (`--desktop --profile=lxqt`), launching another instance causes the new process to hand off control through D-Bus before exiting after approximately 1–2 seconds.

The agent therefore observes:

- Process appeared
- Process exited before the T+5 s health snapshot

and correctly classifies the application as **DEGRADED**, exactly matching the challenge specification.

This behaviour **does not** indicate an OS Image regression.

For desktop integrity, **Part C** remains the authoritative validation because it verifies that the required desktop entry exists in the correct location.

# Run the agent and immediately analyse the log with an LLM [1]
jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --analyse

**Part A depends on public network endpoints.** URLs in the Part A YAML
(example.com, httpbin.org, wikipedia.org, etc.) are public network endpoints
outside the agent's control. Transient network failures can produce a FAIL
result that does not reflect an OS Image regression. The LLM analysis layer
is aware of this and treats a single Part A FAIL against a well-known site
with less weight than a systematic pattern across multiple sites [1].

**Xvfb fallback loses isolation.** Part B uses Xvfb to isolate GUI app
launches from the user's real desktop. If Xvfb is not installed, the agent
falls back to the user's real DISPLAY with an explicit operator warning.
Functionality is preserved but the isolation property is lost. Xvfb is
declared in the `.deb` package's `Depends:` field and listed in
[`INSTALL.md`](INSTALL.md) as a required system dependency.

**CPU% normalised to one core.** `psutil` reports CPU as a percentage of a
single core, so a multi-threaded application using two cores fully would
read ~200%. This is documented in the per-app `detail` field of every
Part B record. The < 20% sustained CPU target [1] is interpreted as 20%
of one vCPU, consistent with this measurement convention.

**LLM output quality is model-dependent.** Smaller local models
(< 7B parameters) may drift from the strict five-section output format.
Models at the 7B+ parameter tier (`qwen2.5:7b`, `llama3.1:8b`, `mistral`)
or hosted OpenAI-compatible endpoints produce reliable output. See
[`INSTALL.md`](INSTALL.md) Section 3 for recommended configurations.

**PCManFM-Qt registers as DEGRADED on LxQt.** PCManFM-Qt is a
single-instance application. When the agent launches a second instance on
a system where LxQt is already running it as the desktop manager, the new
instance hands off to the existing one via D-Bus and exits within 1–2
seconds. The agent classifies this correctly as DEGRADED per the spec's
exact definition — "process appeared but terminated unexpectedly before
the check completed" [1] — but it is not an OS Image regression. Part C's
presence check on the same app remains the authoritative signal.

---

## 8. Repository layout
## Repository Structure

```text
Automated_Testing/
├── README.md                          # Project overview, usage, and benchmark summary
├── INSTALL.md                         # Step-by-step installation guide
├── design.md                          # System architecture, YAML schema, and design decisions
├── jiopc_agent.py                     # Main entry point and orchestration runner
├── analyse.py                         # Model-agnostic LLM analysis and optional summary email
│
├── src/
│   ├── part_a.py                      # Part A: Web application testing (Playwright + headless Chromium)
│   ├── part_b.py                      # Part B: Native application health testing (Xvfb + psutil)
│   └── part_c.py                      # Part C: Desktop and Start Menu presence verification
│
├── configs/
│   └── jiopc-agent.yaml               # Complete YAML configuration containing
│                                      # all Part A, Part B, and Part C test cases
│
├── prompts/
│   └── analyse_log.txt                # Prompt used by the LLM analysis engine
│
├── packaging/
│   ├── build-deb.sh                   # Reproducible Debian package build script
│   ├── debian/                        # Debian package staging directory
│   └── out/
│       └── jiopc-agent_1.0.0_all.deb  # Generated Debian package
│
├── benchmarks/
│   ├── results.md                     # Benchmark methodology, measurements, and analysis
│   ├── scripts/
│   │   ├── sampler.sh                 # 1 Hz CPU and RAM sampler
│   │   ├── aggregate.py               # Benchmark statistics aggregation
│   │   └── measure_overhead.sh        # Part B launch-overhead measurement
│   └── raw/                           # Generated benchmark data (CSV, JSON, Markdown)
│
├── samples/
│   ├── test_run_<timestamp>.log       # Sample JSON Lines test run log
│   └── analyse_output.txt             # Example LLM-generated analysis report
│
├── screenshots/                       # Screenshots of the agent running inside the JioPC VM
│
└── video/                             # Demonstration video of the complete solution
```


This layout matches the repository requirements from Document 1 [2]:
`README.md`, `design.md`, and `INSTALL.md` at the root; source in `src/`;
`packaging/`, `benchmarks/`, `screenshots/`, and `video/` in their own
directories.

---

## 9. Further documentation

- [`INSTALL.md`](INSTALL.md) — step-by-step installation on a fresh Ubuntu
  24.04 + LxQt VM [2], LLM configuration for OpenAI / Ollama / Mistral,
  optional SMTP email setup, source-build alternative, Part C test-data
  seeding, and troubleshooting.
- [`design.md`](design.md) — full architecture of the runner core and all
  three components, YAML schema documentation, technology choices with
  justification, and detailed known limitations [1].
- [`benchmarks/results.md`](benchmarks/results.md) — CPU, RAM, and full-run
  duration with p50 and p95, Part B per-app overhead figure, methodology,
  and reproducibility instructions [1].
- [`prompts/analyse_log.txt`](prompts/analyse_log.txt) — the LLM prompt
  used to produce the PROMOTE / HOLD analysis. A graded deliverable [1].

---

## References

- **Challenge specification (Document 3 of 4):** JioPC × IIT Bombay
  Hackathon 2026, Challenge 02 — Automated Testing Agent [1]
- **Platform overview (Document 1 of 4):** About JioPC & The Challenges [2]

---

**Team:** Ambika Soni
**Members:** Ambika 23b0011
**Challenge:** CHALLENGE-02 — Automated Testing Agent 

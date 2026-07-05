# JioPC Automated Testing Agent — Design Document

**Challenge:** JioPC × IIT Bombay Hackathon 2026 — Challenge 02 [1]
**Repository:** https://github.com/itsAmbika/Automated_Testing
**Target platform:** Ubuntu 24.04 LTS + LxQt, 4 vCPU @ 2.45 GHz, 8 GB RAM, no GPU [2]

---

## 1. Overview

The agent is a scripted validation framework an engineer runs manually against a
freshly-patched JioPC OS Image [1]. It systematically verifies three properties
of the desktop:

1. **Part A** — Web apps are reachable and render their expected UI elements [1].
2. **Part B** — Native apps are present, launchable, and healthy at T+5s [1].
3. **Part C** — All 15 pre-installed apps sit in their correct desktop folder
   and carry the correct start-menu category [1].

Results are written to a structured log at
`~/.local/share/jiopc/agent/test_run_<timestamp>.log` [1]. A post-run,
model-agnostic LLM analysis layer reads that log and produces a
PROMOTE / HOLD recommendation [1].

The agent is triggered manually via the terminal — no daemon, no scheduler,
no background service — and exits with code 0 only when every required test
passes, so it can double as a manual gate before promoting the OS Image [1].

---

## 2. Architecture

### 2.1 High-Level Structure

┌─────────────────────────────────────────┐
│ configs/jiopc-agent.yaml │
│ (agent config + all test cases) │
└────────────────────┬────────────────────┘
│ read once at startup
▼
┌────────────────────────────────────────────────────────────────┐
│ jiopc_agent.py (Runner Core) │
│ - loads YAML │
│ - opens ~/.local/share/jiopc/agent/test_run_<ts>.log │
│ - dispatches Parts A, B, C in configurable order │
│ - writes JSON Lines records + final summary block │
│ - exits 0 if all pass, non-zero otherwise │
└───┬───────────────────┬───────────────────┬────────────────────┘
│ │ │
│ web_apps │ native_apps │ desktop_presence
▼ ▼ ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│ Part A │ │ Part B │ │ Part C │
│ │ │ │ │ │
│ Play- │ │ Xvfb + │ │ dual │
│ wright │ │ psutil │ │ index │
│ headless│ │ + │ │ (menu / │
│ Chromium│ │ subproc │ │ desktop)│
└─────────┘ └─────────┘ └─────────┘
│ │ │
└─────────┬─────────┴─────────┬─────────┘
▼ ▼
┌──────────────────────────────────┐
│ test_run_<timestamp>.log (JSONL)│
│ + summary record at EOF │
└──────────────────┬───────────────┘
│ optional: --analyse
▼
┌──────────────────────────┐
│ analyse.py + prompt │
│ (model-agnostic LLM) │
│ → PROMOTE / HOLD │
└──────────────────────────┘


### 2.2 Runner Core (`jiopc_agent.py`)

The runner core is the single entry point [1]. Its six responsibilities map
directly to the spec's Section 2.4:

| Responsibility [1] | Implementation |
|---|---|
| Read YAML at startup | `load_config()` — PyYAML `safe_load`; expands `~` in log path |
| Execute Parts A, B, C in configurable order | `run_order` field in YAML; CLI `--part` flag overrides for single-component runs |
| Write log to `~/.local/share/jiopc/agent/test_run_<ts>.log` | `setup_log_file()` — creates directory tree in user space; line-buffered handle |
| Log each test as parseable record | `write_record()` — JSON Lines, one record per line |
| Machine-readable summary block at EOF | `write_summary_block()` — inside `finally`, so it survives partial runs |
| Exit 0 on all-pass, non-zero otherwise | Result classification: `PASSING = {PASS}`, `NEUTRAL = {BLOCKED}`, `FAILING = {FAIL, DEGRADED, MISSING, MISPLACED}` |

**Component dispatch pattern.** Each part is imported lazily via a
`dispatch_part_X` helper. If a component module is missing, the dispatch
logs a warning and continues — useful during incremental development, and
the shipped `.deb` contains all three so this is never triggered in
production.

**Result classification and exit code.** The neutral treatment of BLOCKED is
a deliberate design choice: the spec is explicit that BLOCKED (a page
loaded but shows a CAPTCHA) is not a regression in the OS Image and must
be treated differently from FAIL by the LLM layer [1]. The runner honours
that by counting BLOCKED in the summary but not flipping the exit code on it.

### 2.3 Part A — Website & Web App Testing (`src/part_a.py`)

Part A drives a single shared headless Chromium instance across every URL in
the YAML [1]. Each URL is processed through an eight-stage decision flow:

Stage 1: navigation with DOMContentLoaded timing
Stage 2: bot-detection check FIRST → BLOCKED short-circuit
Stage 3: HTTP status check → 4xx/5xx = FAIL
Stage 4: blank-page + soft-404 body scan → in-body error = FAIL
Stage 5: dismiss cookie/consent overlays (NOT a CAPTCHA bypass)
Stage 6: wait for each YAML element (3000ms budget per selector)
Stage 7: load-time threshold flagging (slow = flagged PASS, not FAIL)
Stage 8: Expected-vs-Unexpected BLOCKED reporting extras


**BLOCKED-vs-FAIL ordering is critical.** Stage 2 runs before element checks
because a CAPTCHA wall naturally hides `nav`, `search`, and other real
elements — checking them first would mislabel a BLOCKED page as FAIL. The
spec explicitly requires these two outcomes to be treated differently by
the LLM layer [1], and this ordering is what makes the distinction reliable.

**Soft-404 detection.** The spec's FAIL definition includes "returns a
4xx/5xx error, or crashes the browser" [1]. Real sites frequently return
HTTP 200 with an "Access Denied" or "Page Not Found" message in the body —
strictly the HTTP layer alone would miss these. `detect_soft_error` scans
the body text for a curated set of error phrases so these cases FAIL
correctly, honouring the spec's "no blank or error page" requirement [1].

**Consent-overlay dismissal.** Modern sites (BBC, most EU-hosted news) show
GDPR consent banners that hide the real nav until dismissed. Clicking
"Accept" is *not* a CAPTCHA bypass — consent overlays are ordinary
user-consent UI, unrelated to bot gating — but not dismissing them would
produce false FAILs on healthy sites. Stage 5 handles this best-effort with
short timeouts and full exception tolerance; genuinely missing elements are
still caught by Stage 6.

**JS-rendered elements.** `page.wait_for_selector(sel, timeout=3000)` is
used instead of raw `query_selector`, so elements that appear post-
`DOMContentLoaded` (Wikipedia's search box, single-page-app navs) are
correctly awaited. A missing element after 3000ms is a real FAIL.

**Expected vs Unexpected BLOCKED.** The YAML per-URL
`bot_detection_expected` flag lets us produce richer telemetry: an Expected
BLOCKED (Google, GitHub) is healthy and does not drive HOLD; an Unexpected
BLOCKED is an anomaly worth surfacing. The prompt file consumes this
directly to inform the PROMOTE/HOLD recommendation.

**Lightweight footprint.** One shared `browser` instance is reused across
all URLs, with a fresh `browser_context` per URL for cookie isolation.
Reusing the browser keeps total RAM in the < 150 MB envelope for the
agent's own processes [1] (browser workers are a separate footprint —
see Section 6 on the browser-inclusion clarification).

### 2.4 Part B — Native App Health Testing (`src/part_b.py`)

Part B has the most involved lifecycle. For each native app defined in the
YAML the agent must verify `.desktop` existence, verify the `Exec=` binary
is executable, launch the app, confirm a process appears within a timeout,
record VmRSS and CPU at T+5s, and terminate cleanly with no orphans [1].

The implementation choice for how the launch is isolated is left open by
the spec and explicitly evaluated under code quality and innovation [1]. We
made three notable architectural decisions.

**Decision 1 — Xvfb virtual-display isolation.** All 15 Part B apps launch
into a single Xvfb instance started once at the top of `run_part_b`. Every
app's environment gets `DISPLAY=:N` pointing at Xvfb, so windows render
into an in-memory framebuffer and never composite onto the user's real
desktop. This satisfies the spec's "must not cause observable delays to
any other application running on the machine" constraint absolutely [1].

We considered and rejected four alternatives:

- **Xephyr** — opens a *visible* nested X window; wrong tool for the goal.
- **xpra** — heavier daemon model (~30 MB, GStreamer + Python bindings);
  richer feature set wasted on launch-test-terminate workloads.
- **Linux namespaces / bubblewrap** — isolates the process tree but does
  not solve the display problem; you'd still need Xvfb inside.
- **Wayland headless compositors** — overkill for the X11-targeted apps
  the JioPC image ships.

Xvfb is a single ~10–15 MB user-space binary that integrates cleanly with
our existing `os.killpg()` cleanup pattern. If Xvfb is not installed the
agent falls back to the user's real display with an explicit operator
warning — the isolation property is lost but the agent still functions.

**Decision 2 — PID-anchored, tree-walking worker identification.** Rather
than diffing "PIDs matching name before vs after", we anchor on
`popen.pid` (the PID the kernel gave us — authoritative, no diff
guessing) and then use `identify_worker(launcher_pid, proc_name)` to walk
the process tree. 
handles four launcher scenarios that a naïve PID-diff approach breaks on:

1. **Direct exec** — the `.desktop` `Exec=` points straight at the target binary
   (e.g. `xterm`). `popen.pid` *is* the worker; no walk needed.
2. **Wrapper script** — `Exec=` points at a shell wrapper that eventually
   `exec`s the real binary (common for LibreOffice, Firefox, Chromium). The
   worker is a descendant of `popen.pid`, matched by `proc_name`.
3. **Forking launcher** — `Exec=` points at a launcher that spawns the real
   app and exits (GNOME apps under `gtk-launch`, some Flatpak wrappers). The
   worker is orphaned to PID 1 but is still discoverable by matching
   `proc_name` within a short scan window seeded from the launcher's original
   child list.
4. **Single-instance re-dispatch** — the launcher hands off to an existing
   D-Bus service (LibreOffice `soffice`, some Qt apps). We detect that
   `popen.pid` exited quickly with rc=0 and fall back to a `proc_name` scan
   scoped to the current user's session, with a short timeout to avoid
   false-positives from an already-running instance.

The tree walk uses `psutil.Process(launcher_pid).children(recursive=True)`
augmented with a name-based fallback filtered by `os.getuid()`, which keeps
Part B robust across all four cases without any per-app special-casing in the
YAML. `identify_worker` returns a single canonical `psutil.Process` handle
that all downstream stages (VmRSS sampling, CPU sampling, termination) use.

**Decision 3 — Process-group termination with escalation.** Every app is
launched with `preexec_fn=os.setsid`, which places it in its own process
group. Cleanup uses `os.killpg(pgid, SIGTERM)` first, waits up to a
configurable grace period (default 3 seconds), then escalates to
`SIGKILL` if any process in the group survives. This is what guarantees
the spec's "no orphaned processes" acceptance criterion [1] even for apps
that fork detached children (browsers, Electron apps, LibreOffice's
`soffice.bin`). The final orphan sweep after all Part B apps have been
tested does a name-based scan against the union of every `proc_name` in
the YAML and force-kills any stragglers — belt and braces, but the sweep
almost never has anything to do in practice.

**Health-check timing.** The T+5s sample is taken relative to the moment
`identify_worker` first returned a live handle, not relative to
`popen.pid` creation. This isolates the app's own warm-up cost from
launcher overhead and is the value the benchmark report treats as
"app launch time" after subtracting the documented agent overhead [1].
VmRSS is read via `psutil.Process.memory_info().rss`; CPU is sampled with
`cpu_percent(interval=1.0)` so the reading is a real 1-second average
rather than an instantaneous zero.

**Result classification.**

- `PASS` — `.desktop` found, `Exec=` executable, worker identified within
  `launch_timeout_s`, worker still alive at T+5s, terminated cleanly.
- `FAIL` — worker never appeared within the timeout, or `.desktop` /
  `Exec=` verification failed. Matches the spec's FAIL definition [1].
- `DEGRADED` — worker appeared but was gone before T+5s. Matches the
  spec's DEGRADED definition ("process appeared but terminated unexpectedly
  before the check completed") [1].

**Cool-down.** A configurable inter-app delay (default 2 seconds, as the
spec suggests [1]) sits between consecutive Part B cases to prevent
resource contention from producing false DEGRADED results on the next app.

### 2.5 Part C — Start Menu & Desktop App Presence (`src/part_c.py`)

Part C is a pure read-only structural check — no processes launched, no
elevated privileges, no writes anywhere on the filesystem [1]. It uses a
dual-index strategy to make the MISSING vs MISPLACED distinction cheap
and unambiguous.

**Index 1 — the start-menu index.** At the start of `run_part_c`, the
agent walks `/usr/share/applications/` and
`~/.local/share/applications/` (the two directories the spec names [1])
and builds a dictionary keyed by the `.desktop` file's stem (or by
`Name=` for a secondary lookup), with values containing the parsed
`Categories=` list and the file's absolute path. PyXDG's
`xdg.DesktopEntry` handles the parsing per the Freedesktop spec so
edge cases like localised `Name[xx]=` fields and multi-value
`Categories=` entries are handled correctly.

**Index 2 — the desktop-folder index.** The agent walks the user's
desktop root (resolved from `xdg-user-dir DESKTOP` with a fallback to
`~/Desktop`) one directory deep, collecting each subdirectory (Games,
Education, Productivity) and the `.desktop` files inside it. The result
is a `{app_name: folder_name}` map.

**Per-app resolution.** For each YAML entry the agent asks two
independent questions:

1. Is this app's `.desktop` file present *anywhere* the system would
   look for it — the start-menu index, or inside any desktop folder?
   If not → `MISSING`. This is the definition the spec gives [1].
2. If present, does it sit in the right place? Two sub-checks:
   - Desktop folder matches `desktop_folder` in the YAML.
   - `Categories=` from the start-menu index contains
     `start_menu_category` from the YAML.
   If either sub-check fails → `MISPLACED`, with the detail message
   naming which sub-check tripped. Both passing → `PASS`.

This ordering — existence first, placement second — is what makes the
MISSING vs MISPLACED distinction the spec requires [1] reliable and
exclusive: an app is never simultaneously both.

**Performance.** Building both indexes once, up front, means each of
the 15 per-app checks is an O(1) dictionary lookup. Part C completes
in well under the spec's 30-second target [1] on the reference
hardware, typically in single-digit hundreds of milliseconds.

---

## 3. YAML Schema

The full schema shipped in `configs/jiopc-agent.yaml` is a superset of
the spec's non-normative example [1], with additional fields the
implementation uses. Every field is documented inline in the YAML with
comments, and every field is optional unless marked required below.

**`agent:` block.**

- `log_dir` (required) — directory for `test_run_<ts>.log`, `~` expanded.
- `llm_prompt_file` (required) — path to `prompts/analyse_log.txt`.
- `run_order` — list containing some subset of `[A, B, C]`; the runner
  dispatches components in this order. Default `[A, B, C]`, matching
  the spec's "sequence (configurable order)" requirement [1].
- `cooldown_between_native_apps_s` — Part B inter-app delay. Default 2.
- `xvfb_display_number` — the `:N` Xvfb attaches to. Default `:99`.

**`web_apps:` list (Part A).** Per the spec's minimum schema [1] plus
implementation extras:

- `name` (required)
- `url` (required)
- `load_timeout_ms` (required) — the threshold for the "flag slow pages"
  requirement [1].
- `bot_detection_expected` (required) — drives the Expected vs
  Unexpected BLOCKED distinction described in Section 2.3.
- `elements` (required, at least one) — list of `{selector, description}`
  entries. The spec requires at least one element check per web app [1].

**`native_apps:` list (Part B).** Per the spec's minimum schema [1]:

- `name` (required)
- `desktop_file` (required) — absolute path, must resolve under
  `/usr/share/applications/` or `~/.local/share/applications/` per
  the spec [1].
- `process_name` (required) — the string `identify_worker` matches on
  when a tree walk is needed.
- `launch_timeout_s` (required) — default 10 in absence, per the spec [1].

**`desktop_presence:` list (Part C).** Per the spec's minimum schema [1]:

- `name` (required)
- `desktop_folder` (required) — one of Games, Education, Productivity per
  the shipped OS Image [1].
- `start_menu_category` (required) — must match a value the app's
  `Categories=` field would legitimately contain.

The YAML shipped in the repo populates all 15 pre-installed apps for
Part C, all web apps for Part A, and all native apps for Part B — the
spec is explicit that the contestant must ship a complete populated
config, not just a schema [1].

---

## 4. Log Format

The log at `~/.local/share/jiopc/agent/test_run_<timestamp>.log` [1] is
JSON Lines, one record per line. This satisfies the spec's requirement
for "a discrete, parseable record" with the minimum fields — timestamp,
component, test name, result, duration_ms, and detail — plus the
freedom to add component-specific fields without breaking the format [1].

**Per-test record shape.**

```json
{"ts":"2026-05-14T02:00:03.412Z","component":"A","test":"JioSaavn",
 "result":"PASS","duration_ms":1842,"detail":"nav + search box present",
 "extra":{"http_status":200,"load_time_ms":1420,"blocked_expected":false}}
{"record_type":"summary","total":40,"pass":37,"fail":1,"blocked":1,
 "degraded":0,"missing":0,"misplaced":1,
 "by_component":{"A":{"total":10,"pass":9,"blocked":1,"fail":0},
                  "B":{"total":15,"pass":14,"fail":1,"degraded":0},
                  "C":{"total":15,"pass":14,"misplaced":1,"missing":0}},
 "exit_code":1,"run_duration_ms":214300}
 
 ```
## 5. LLM Analysis Layer

The analysis layer is intentionally decoupled from the agent itself —
the spec is explicit that "testing logic must work independently; the
LLM is a post-run analysis layer"

`analyse.py`. A thin script that:

Reads `--log <path>` (or the most recent log in `log_dir` if omitted).
Loads `prompts/analyse_log.txt`.
Substitutes `{{LOG_CONTENT}}` in the prompt with the file contents.
Calls the configured LLM endpoint via the `openai` Python SDK, with 
   `base_url` set from `LLM_BASE_URL`, `model` from `LLM_MODEL`, and API key
   from `LLM_API_KEY`. This satisfies the spec's requirement that the script
   be model-agnostic and configured via environment variables, working with
   any OpenAI-compatible endpoint (OpenAI, Anthropic, Mistral, local
   Ollama, or any other provider) [1].
5. Prints the LLM's response to the terminal.
6. Optionally sends a summary email via SMTP if the bonus feature's
   environment variables are configured (see Section 5.3).

**`prompts/analyse_log.txt`.** A plain-text prompt that instructs any
instruction-following LLM to produce five sections, in this order and with
exactly these headings:

1. `## 1. EXECUTIVE SUMMARY` — one paragraph: how many tests ran, how many
   passed, and whether the OS Image patch is safe to promote [1].
2. `## 2. ANOMALIES & FAILURES` — findings grouped under `### Part A`,
   `### Part B`, `### Part C`, one line per non-PASS result [1].
3. `## 3. PATTERNS & CORRELATIONS` — cross-test patterns supported by two
   or more records [1].
4. `## 4. RISK PRIORITISATION` — severity ordering (FAIL > DEGRADED >
   MISSING > MISPLACED > BLOCKED) applied to this run.
5. `## 5. RECOMMENDATION` — a single PROMOTE or HOLD on its own line,
   followed by a one-sentence rationale [1].

The prompt is itself a graded deliverable [1], so it carries anti-
hallucination rules explicitly: use the summary record for counts, use
individual records only for anomaly descriptions, report patterns only
when supported by two or more records, and do not fabricate expectedness
of a BLOCKED result unless the log's `detail` field carries it.

### 5.1 Model-Agnostic Configuration

Endpoint configuration is read entirely from environment variables — the
same pattern used across the tool ecosystem. Swapping providers requires
zero code changes:

```bash
# OpenAI
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o
export LLM_API_KEY=sk-...

# Local Ollama (Windows host from Ubuntu guest)
export LLM_BASE_URL=http://10.0.2.2:11434/v1
export LLM_MODEL=qwen2.5:7b
export LLM_API_KEY=ollama-local

# Mistral cloud
export LLM_BASE_URL=https://api.mistral.ai/v1
export LLM_MODEL=mistral-large-latest
export LLM_API_KEY=<mistral-key>
```

## 5.2 Prompt Design Choices

Three prompt-design decisions significantly improve the consistency, accuracy, and reproducibility of the LLM-generated release analysis.

### Summary Record as the Single Source of Truth

The prompt instructs the LLM to treat the final JSON log entry (`record_type: "summary"`) as the **authoritative source** for all numerical statistics, including total tests, passed tests, blocked tests, and failure counts. Individual test records are used **only** for anomaly descriptions and pattern detection.

This design prevents a common failure mode of smaller language models, where they recount individual log entries and produce totals that differ from the summary record.

---

### Conservative Pattern Detection

The **Patterns & Correlations** section requires that any reported pattern be supported by **at least two independent log records**.

If no such evidence exists, the model must output the exact fallback statement:

> **No systemic patterns detected; failures appear isolated.**

This conservative rule prevents the LLM from inventing root causes or making unsupported correlations from isolated failures.

---

### Deterministic PROMOTE / HOLD Decision

The recommendation section follows a fully deterministic decision rule.

The OS Image is classified as **PROMOTE** only when the summary record contains:

- Zero **FAIL**
- Zero **DEGRADED**
- Zero **MISSING**
- Zero **MISPLACED**

Otherwise, the recommendation is **HOLD**, with the rationale identifying the highest-severity anomaly class observed.

`BLOCKED` results never prevent **PROMOTE**, since they indicate a website presented a CAPTCHA or bot-detection challenge rather than an OS Image regression.

This deterministic rule makes recommendations reproducible across repeated executions and across different LLMs.

---

## 5.3 Bonus Feature: Summary Email

After the LLM completes its analysis, `analyse.py` can optionally generate and send a formatted summary email.

The email contains:

- Executive Summary
- Anomalies & Failures
- Final **PROMOTE / HOLD** recommendation

These correspond to the bonus reporting objective described in the challenge specification.

Email delivery is configured entirely through environment variables:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `EMAIL_FROM`
- `EMAIL_TO`

This configuration follows the same environment-variable approach used for selecting the LLM endpoint.

If any required SMTP variable is missing, the email feature is skipped automatically so that the core analysis workflow continues normally.

Emails are sent as `multipart/alternative` messages containing both:

- Plain-text version
- HTML version

The HTML version highlights the recommendation using colour coding:

-  Green — **PROMOTE**
-  Red — **HOLD**

SMTP failures are treated as warnings only and never cause `analyse.py` to terminate.

---

## 5.4 Model Choice Trade-Off

Several locally hosted Ollama models were evaluated during development.

Smaller models (approximately 3B parameters) occasionally deviated from the required five-section response format or generated inconsistent anomaly summaries.

Models in the **7B+ parameter range**, including:

- Qwen2.5:7B
- Llama 3.1:8B
- Mistral

produced significantly more reliable and specification-compliant outputs.

Hosted API models such as GPT-4o and Claude-compatible endpoints also produced consistently accurate analyses.

Although the analysis pipeline is model-agnostic, a **7B+ model or a hosted API** is recommended for final production runs where maximum report consistency is desired.

The model configuration process is documented in **README.md**.

---

# 6. Constraint Compliance

The implementation has been designed to satisfy all mandatory constraints defined in the challenge specification.

| Challenge Constraint | Design Implementation |
|----------------------|----------------------|
| **No root privileges at runtime** | All operations execute entirely in user space. No `sudo` or privileged system calls are required. |
| **No modification of the operating system** | The agent performs only read operations and writes logs under `~/.local/share/jiopc/agent/`. No system files are modified. |
| **User-space output only** | All generated logs and reports are stored inside the configured user-space log directory. |
| **Fresh environment assumption** | Every execution rebuilds indexes and rescans the filesystem without relying on cached state from previous runs. |
| **Runtime within specification** | Benchmark measurements show a mean runtime of approximately **216.5 seconds**, comfortably within the required limit. |
| **Headless browser execution** | Playwright is always launched with `headless=True`, ensuring no browser window is displayed. |
| **No CAPTCHA solving** | CAPTCHA and bot-detection pages are classified as `BLOCKED`; the agent never attempts any bypass mechanism. |
| **Guaranteed process cleanup** | Native applications are terminated using a process-group cleanup strategy (`SIGTERM` → grace period → `SIGKILL`) with a final orphan cleanup pass. |
| **Lightweight resource usage** | Agent resource consumption remains within the required CPU and RAM limits according to benchmark measurements. |
| **Configuration-driven behaviour** | All test definitions (URLs, applications, desktop folders, categories, selectors, timeouts) are defined in YAML rather than hardcoded into the source code. |

---

# 7. Known Limitations

### Single-Instance Applications

Some Linux applications support only a single running instance using D-Bus registration or lock files.

When Part B launches such an application while another instance is already running, the newly launched process transfers control to the existing instance and exits shortly afterwards.

The agent therefore correctly classifies the result as **DEGRADED**, although this behaviour does not necessarily indicate an OS Image regression.

---

### Xvfb Availability

Part B isolates GUI applications using **Xvfb**.

If Xvfb is unavailable, the agent falls back to the user's active display after issuing a warning.

Testing remains functional, although graphical isolation is no longer guaranteed.

---

### External Network Dependencies

Part A validates publicly accessible websites.

Temporary network outages, DNS failures, or remote server issues may produce `FAIL` results that are unrelated to the JioPC OS Image itself.

The LLM analysis layer therefore places greater emphasis on repeated patterns across multiple websites than on isolated web failures.

---

### Small Benchmark Sample Size

Benchmark runtime measurements were collected using three Hyperfine runs following one warm-up execution.

Consequently, the reported p95 value is approximated from the maximum observed runtime rather than computed from a statistically large sample.

The reported mean and standard deviation provide the primary performance indicators.

---

### CPU Measurement Convention

CPU utilisation is collected using **psutil**, which reports utilisation as a percentage of a single CPU core.

As a result, multi-threaded applications may legitimately report CPU values greater than **100%**.

This behaviour is documented in both the benchmark report and the Part B health records.

---

### LLM Output Depends on Model Capability

The analysis pipeline is designed to work with any OpenAI-compatible language model.

However, smaller local models (typically below **7B parameters**) may occasionally deviate from the required report structure or produce less consistent summaries.

For production-quality reports, larger local models or hosted APIs provide more reliable results.

# Repository Layout

```text
Automated_Testing/
├── jiopc_agent.py                  # Runner core and entry point
├── analyse.py                      # LLM-based log analysis and optional email reporting
│
├── src/
│   ├── part_a.py                   # Web application testing (Playwright)
│   ├── part_b.py                   # Native application health testing (Xvfb + psutil)
│   └── part_c.py                   # Desktop and Start Menu integrity verification
│
├── configs/
│   └── jiopc-agent.yaml            # YAML configuration containing all test cases
│
├── prompts/
│   └── analyse_log.txt             # Prompt template used by the LLM analysis engine
│
├── benchmarks/
│   ├── results.md                  # Benchmark methodology and performance results
│   ├── scripts/
│   │   ├── sampler.sh              # CPU/RAM sampler (1 Hz)
│   │   ├── measure_overhead.sh     # Part B launch-overhead measurement
│   │   └── aggregate.py            # Aggregates benchmark statistics
│   └── raw/                        # Generated benchmark data (CSV, JSON, Markdown)
│
├── packaging/                      # Debian packaging (.deb) files
│
├── samples/                        # Sample logs and LLM analysis outputs
│
├── screenshots/                    # Screenshots for documentation
│
├── video/                          # Demonstration video
│
├── README.md                       # Project overview and usage instructions
├── INSTALL.md                      # Installation and setup guide
├── design.md                       # System architecture and implementation details
└── .gitignore                      # Git ignore rules
```

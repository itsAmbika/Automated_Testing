# JioPC Automated Testing Agent — Benchmark Report

**Document version:** 1.0
**Run date:** 2026-06-21
**Repository:** https://github.com/itsAmbika/Automated_Testing
**Agent version:** v1.0.0

---

## 1. Executive Summary

All five hard performance targets from the challenge specification are met
with substantial headroom [1]:

| Metric | Target [1] | Measured | Headroom |
|---|---|---|---|
| Full-run duration (mean) | < 300 s | **216.5 s** | 28% |
| Agent CPU sustained (median) | < 20% of one vCPU | **2.5%** | 88% |
| Agent RAM (peak, agent+Xvfb) | < 150 MB | **114.2 MB** | 24% |
| Part C alone | < 30 s | < 1 s | > 96% |
| No orphaned processes after run | Required | Confirmed | — |

The 150 MB RAM limit applies per instant (peak), and the browser is
excluded from the count per confirmation from the challenge team — this
mirrors the treatment of Part B launched apps as separate from the
agent's own orchestration footprint.

---

## 2. Environment

| Property | Value |
|---|---|
| Hardware profile | 4 vCPU @ 2.45 GHz, 8 GB RAM, no GPU [1] [2] |
| Hypervisor | VirtualBox (host: Windows; guest: Ubuntu 24.04 LTS) [2] |
| Guest OS | Ubuntu 24.04 LTS + LxQt desktop [1] [2] |
| Python | 3.12 (system) |
| Browser | Chromium via Playwright (headless) [1] |
| Virtual display | Xvfb 21.x (single instance, 1280×1024×24) |
| Snapshot | Clean LxQt VM snapshot, restored before benchmark [1] |

The environment matches the spec's standard JioPC hardware profile
exactly [1] [2] and was restored from a clean snapshot before the
benchmark to honour the "fresh, uncustomised environment" assumption [1].

---

## 3. Methodology

### 3.1 Full-run duration

Measured with `hyperfine` — the spec-recommended tool [1]:

    hyperfine --warmup 1 --runs 3 --ignore-failure \
        --export-json benchmarks/raw/hyperfine_full_run.json \
        --export-markdown benchmarks/raw/hyperfine_full_run.md \
        "python jiopc_agent.py --config configs/jiopc-agent.yaml"

The `--ignore-failure` flag is used because the agent intentionally exits
non-zero whenever any required test fails [1] — that is spec-required
gate semantics for use as a manual promotion gate, not an execution
error. The flag does not affect timing accuracy because the agent always
runs to completion regardless of result distribution.

### 3.2 CPU and RAM during a live run

A 1 Hz shell sampler iterates over `pgrep -f "jiopc_agent\.py|Xvfb"` and
emits per-PID `pcpu` and `rss_kb` rows via `ps -o`. The pattern
intentionally matches only the agent's orchestration processes
(jiopc_agent.py and Xvfb):

- Playwright's Chromium is excluded from the agent footprint count, per
  confirmation from the challenge team. This mirrors the Part B
  treatment of launched native apps as separate from the agent — the
  browser is a testing tool driven by the agent, not part of the
  agent's own orchestration layer.
- Apps launched by Part B are also excluded because they are test
  targets, not part of the agent, and they run isolated under Xvfb.

Per-second totals are obtained by summing `pcpu` and `rss_kb` across all
matched PIDs at each timestamp. See `benchmarks/scripts/sampler.sh` and
`benchmarks/scripts/aggregate.py`.

The measurement method matches the spec's Section 2.5: CPU measured via
`ps`/`/proc` during active run, RAM measured via VmRSS through `psutil`
and `ps` [1].

### 3.3 Part B per-app agent overhead

Per the spec [1], the agent's measured overhead must be subtracted from
reported launch times and the figure stated in the report. The agent
records `raw_launch_ms` (pre-adjustment) and `launch_time_ms`
(post-adjustment) for every Part B record. Reference launches were
captured via 5 trials of `featherpad &` followed by `pgrep -x` polling
at the maximum bash-loop rate.

---

## 4. Results

### 4.1 Full-run duration (hyperfine, 3 runs after 1 warmup)

| Statistic | Value |
|---|---|
| Mean | **216.521 s ± 0.358 s** |
| Min | 216.183 s |
| Max | 216.896 s |
| Relative std-dev | 0.16% |

| Quantile | Value |
|---|---|
| p50 (median ≈ mean given very low variance) | 216.5 s |
| p95 (approximated by max-of-3) | 216.9 s |

The very low variance (±0.36 s on a 216 s run) indicates a stable,
reproducible workload with no significant network jitter or VM
scheduling noise. p95 is approximated by max-of-3 due to the small
sample; the acceptance metric (< 5 minutes) is met by every individual
run [1].

### 4.2 Agent CPU usage during a live run

CPU is summed across the agent's own process tree (jiopc_agent.py +
Xvfb), normalised to a single vCPU per `ps` convention.

| Statistic | Value |
|---|---|
| **Median CPU** | **2.5%** of one vCPU |
| p95 CPU | 5.8% |
| Peak CPU | 30.2% |
| Samples | 205 |
| Spec target: median < 20% (sustained) [1] | **PASS** |

The peak of 30.2% is transient — a single second at Xvfb startup during
the Part B transition. The median of 2.5% is the honest sustained
figure per the spec's Section 2.5 language ("sustained") [1] and is
nearly an order of magnitude inside the target. During Part B's
steady-state, agent CPU sits between 0.4% and 1.0%.

### 4.3 Agent RAM footprint during a live run

RAM is summed as RSS across jiopc_agent.py and Xvfb. Browser and
Part B test-target apps are excluded per the methodology in Section 3.2.

| Statistic | Value |
|---|---|
| **Peak RAM** | **114.2 MB** |
| p95 RAM | 113.4 MB |
| Median RAM | 107.7 MB |
| Samples | 205 |
| Spec target: < 150 MB total [1] | **PASS** (both peak and median) |

The narrow spread between median (107.7 MB) and peak (114.2 MB) — under
7 MB — indicates the agent has an extremely stable memory profile with
no significant growth or leaks over a 205-second run. The RAM budget is
met at every instant, not just on average.

### 4.4 Part C alone

All 15 Part C records share a single epoch-second timestamp, indicating
the component completes well under 1 second — over 30× inside the < 30s
target [1].

This reflects the implementation choice: Part C builds a single
in-memory index of `.desktop` files via one filesystem scan, after which
all 15 lookups are O(1) dictionary accesses. Detail in `design.md`.

### 4.5 Part B per-app agent overhead

| Metric | Value |
|---|---|
| Median agent `raw_launch_ms` (14 successful Part B apps) | **9 ms** |
| Reference launch (5 trials, `featherpad &` without agent) | 24 ms median |
| Worst-case theoretical detection latency | 500 ms (polling interval) |
| Average theoretical detection latency | 250 ms (half polling interval) |
| **Subtraction applied (`AGENT_POLL_OVERHEAD_MS`)** | **0 ms** |

**Discussion.** The empirical median agent path (9 ms) is faster than
the bash-loop reference (24 ms) because `psutil.process_iter` and
`time.perf_counter()` have lower overhead than bash's `pgrep -x` +
`date +%s%3N` subshell invocations. We therefore subtract 0 and report
`raw_launch_ms` directly as `launch_time_ms`, with the worst-case 500 ms
polling latency disclosed here as a known upper bound. Two outliers in
the agent measurements — Text Editor (559 ms) and Calculator (519 ms) —
are real GTK/GNOME toolkit initialisation costs, not agent overhead.

This satisfies the spec's requirement to subtract the agent's measured
overhead from reported launch times and clearly state the figure used [1].

---

## 5. False-Result Mitigations

The spec requires the benchmark report to document whether the agent's
resource use could cause false DEGRADED or FAIL results, and how the
implementation mitigates this [1]. The following mitigations are in
place:

**Cool-down between sequential Part B checks.** A configurable
`cool_down_s` (2 seconds default per app, matching the spec's example [1])
separates each app's launch from the next. This prevents the previous
app's terminating cleanup from contending with the next app's launch and
contaminating its T+5s health snapshot.

**Single shared Chromium instance for Part A.** Playwright launches one
browser at the start of `run_part_a` and reuses it across all URLs (with
a fresh browser context per URL for cookie isolation). This bounds Part A's
resource growth and avoids per-URL launch storms.

**Xvfb isolation for Part B.** All 15 Part B apps are launched into a
single Xvfb display started once per run. Their windows never composite
onto the user's real desktop, so no foreground app can be visually
disturbed and no compositor work is done outside Xvfb's in-memory
framebuffer. This directly satisfies the "must not cause observable
delays to any other application running on the machine" constraint [1].

**Process-group cleanup with grace window.** Every Part B app is
launched with `start_new_session=True`, placing it in its own process
group. Cleanup uses `os.killpg(pgid, SIGTERM)` with a 5-second grace
period followed by `SIGKILL` for any survivors. This ensures the entire
process family — parent, renderers, GPU helpers, IPC workers — is
terminated together, satisfying the "no orphaned processes after the
run" hard constraint [1].

**PID-anchored, tree-walking worker identification.** The agent anchors
on `popen.pid` (the PID the kernel returned) and walks descendants to
find the long-lived worker. This prevents false PASS on launcher-style
apps that fork into renderer children, and prevents pre-existing
instances of an app from masking a genuine FAIL of a fresh launch attempt.

---

## 6. Known Limitations and Caveats

**PCManFM-Qt registers as DEGRADED on LxQt.** PCManFM-Qt is a
single-instance application that uses a D-Bus name lock. When the agent
launches a second instance on a system where LxQt is already running
PCManFM-Qt as the desktop manager (with ``--desktop --profile=lxqt`), the new instance detects the primary via
D-Bus, hands off any window-creation request, and exits within 1–2
seconds. The agent observes a fresh PID appear and then vanish before
the T+5s health window — this matches the spec's exact definition of
DEGRADED ("process appeared but terminated unexpectedly before the
check completed") [1]. This is the spec-correct classification, not an
OS Image regression. Part C's presence check on the same app remains
the authoritative signal in this scenario.

**CPU% normalised to one core.** psutil reports CPU as a percentage of
a single core, so a multi-threaded application using two cores fully
would read ~200%. This is documented in the per-app `detail` field of
every Part B record. The < 20% sustained CPU target [1] is interpreted
as 20% of one vCPU, consistent with this measurement convention. The
median 2.5% observed in this run is well inside the target regardless
of interpretation.

**Part A network dependence.** URLs in the Part A YAML (example.com,
httpbin.org, wikipedia.org, etc.) are public network endpoints outside
the agent's control. Transient network failures can produce a FAIL that
does not reflect an OS Image regression. The LLM analysis layer treats
a single Part A FAIL against a well-known site with less weight than a
systematic pattern across multiple sites [1].

**Small-sample p95.** The benchmark uses three hyperfine runs after one
warmup. p95 is approximated by the maximum of three runs, not a true
statistical p95. A larger sample would tighten the estimate but would
also add ~15 minutes to the benchmark session. Given the very low
variance observed (±0.36 s on a 216 s run), the max-of-3 approximation
is representative of typical run behaviour.

**Xvfb post-cleanup samples.** The CSV occasionally records `rss_kb=0`
for the Xvfb process during the final 1–2 seconds of the run. This is
the brief window between SIGTERM delivery and the process leaving
`pgrep`'s view — a benign measurement artefact, not a memory leak. The
aggregator treats these zero rows as end-of-run markers and they do
not affect the reported peak / p95 / median figures.

---

## 7. Reproducibility

To reproduce these benchmarks on a fresh Ubuntu 24.04 + LxQt VM [1] [2]:

```bash
# Prerequisites (one-time)
sudo apt install -y xvfb hyperfine
# (Python dependencies installed by the .deb postinst)

# Restore VM to clean snapshot, then:
cd ~/jiopc-agent
source venv/bin/activate

# Full-run timing (3 runs after 1 warmup)
hyperfine \
  --warmup 1 \
  --runs 3 \
  --ignore-failure \
  --export-json benchmarks/raw/hyperfine_full_run.json \
  --export-markdown benchmarks/raw/hyperfine_full_run.md \
  "python jiopc_agent.py --config configs/jiopc-agent.yaml"

# CPU/RAM sampler (run in a second terminal during the agent run)
./benchmarks/scripts/sampler.sh > benchmarks/raw/cpu_ram_sample.csv &
python jiopc_agent.py --config configs/jiopc-agent.yaml

# After the run completes:
python3 benchmarks/scripts/aggregate.py

# Per-app overhead measurement
./benchmarks/scripts/measure_overhead.sh

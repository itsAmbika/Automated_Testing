#!/usr/bin/env python3
"""
jiopc_agent.py — Runner Core for the JioPC Automated Testing Agent.

Responsibilities (per spec Section 2.4):
  1. Read the YAML configuration and test case definitions at startup.
  2. Execute Part A, Part B, and Part C in sequence (configurable order).
  3. Write all results to a single structured log file at
     ~/.local/share/jiopc/agent/test_run_<timestamp>.log.
  4. Log each test case as a discrete, parseable record containing at minimum:
     timestamp, component (A/B/C), test name, result, duration_ms, detail.
  5. Write a machine-readable summary block at the end of the log:
     total tests, pass count, fail count, per-component breakdown.
  6. Exit 0 if all required tests pass, non-zero otherwise — so the agent
     can be used as a manual gate before promoting the OS Image patch.

Log format: JSON Lines (one JSON object per line). Chosen because it is
trivially parseable by any LLM, appendable/streamable, and accommodates
nested fields without escape rules. Documented in design.md.

Usage:
  python jiopc_agent.py --config configs/jiopc-agent.yaml
  python jiopc_agent.py --config configs/jiopc-agent.yaml --part A
  python jiopc_agent.py --config configs/jiopc-agent.yaml --analyse
"""

import argparse
import json
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Make src/ importable so we can pull in part_a, part_b, part_c.
SRC_DIR = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC_DIR))


# ---------------------------------------------------------------------------
# Result classifications — drives exit code and summary breakdown.
# ---------------------------------------------------------------------------
# The seven result values defined by the spec fall into three buckets:
#
#   PASSING — counts as success for the exit gate.
#   NEUTRAL — logged but does NOT flip the exit code; the LLM analysis layer
#             reasons about these separately. The spec is explicit that
#             BLOCKED and FAIL must be treated differently — a CAPTCHA wall
#             is not a regression, so we don't fail the gate on it.
#   FAILING — any of these flips exit code to non-zero, satisfying the spec's
#             "exit 0 if all required tests pass, non-zero otherwise" rule.
PASSING_RESULTS = {"PASS"}
NEUTRAL_RESULTS = {"BLOCKED"}
FAILING_RESULTS = {"FAIL", "DEGRADED", "MISSING", "MISPLACED"}


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

def load_config(config_path):
    """Read the YAML config and expand ~ on agent-level paths."""
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r") as f:
        config = yaml.safe_load(f)

    # Expand ~ so log_dir and prompt paths work regardless of CWD.
    agent = config.get("agent", {})
    if "log_dir" in agent:
        agent["log_dir"] = str(Path(agent["log_dir"]).expanduser())
    if "llm_prompt_file" in agent:
        agent["llm_prompt_file"] = str(
            Path(agent["llm_prompt_file"]).expanduser()
        )
    config["agent"] = agent
    return config


# ---------------------------------------------------------------------------
# Log file management
# ---------------------------------------------------------------------------

def setup_log_file(log_dir):
    """
    Create the log directory under ~/.local/share/jiopc/agent/ and return an
    open file handle plus the log path. The directory is user-space only,
    honouring the spec's "all output in user space" hard constraint —
    nothing is ever written to /tmp or system paths.
    """
    log_dir_path = Path(log_dir).expanduser()
    log_dir_path.mkdir(parents=True, exist_ok=True)

    # Filename matches the spec's pattern: test_run_<timestamp>.log
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    log_path = log_dir_path / f"test_run_{timestamp}.log"

    # Line-buffered so the file is readable mid-run via `tail -f`.
    log_file = open(log_path, "w", buffering=1)
    return log_file, log_path


def write_record(log_file, record):
    """
    Append one JSON-Lines record to the log. The minimum fields required by
    the spec — timestamp, component, test_name, result, duration_ms, detail —
    must be present in every record produced by Parts A/B/C; this writer
    simply serialises whatever the part emits.
    """
    log_file.write(json.dumps(record, default=str) + "\n")


def write_summary_block(log_file, all_results, run_started_at, run_ended_at):
    """
    Append the spec-required summary block at the end of the log: total
    tests, pass count, fail count, and per-component breakdown. The
    record_type='summary' field lets the LLM layer find this block easily
    among the per-test records.
    """
    total = len(all_results)
    passed = sum(1 for r in all_results if r["result"] in PASSING_RESULTS)
    blocked = sum(1 for r in all_results if r["result"] in NEUTRAL_RESULTS)
    failed = sum(1 for r in all_results if r["result"] in FAILING_RESULTS)

    # Per-component breakdown: { "A": {"PASS": 3, "FAIL": 1}, "B": {...}, ...}
    by_component = {}
    for r in all_results:
        comp = r.get("component", "?")
        bucket = by_component.setdefault(comp, {})
        bucket[r["result"]] = bucket.get(r["result"], 0) + 1

    summary = {
        "record_type": "summary",
        "run_started_at": run_started_at,
        "run_ended_at": run_ended_at,
        "total_tests": total,
        "passed": passed,
        "blocked": blocked,
        "failed": failed,
        "by_component": by_component,
        "exit_code": 0 if failed == 0 else 1,
    }
    log_file.write(json.dumps(summary, default=str) + "\n")
    return summary


# ---------------------------------------------------------------------------
# Component dispatch — one function per part, all stub-safe
# ---------------------------------------------------------------------------

def dispatch_part_a(config, log_file):
    """Import and run Part A. Each result is logged via the callback."""
    web_apps = config.get("web_apps", [])
    if not web_apps:
        return []
    try:
        from part_a import run_part_a
    except ImportError as e:
        print(f"[runner] Could not import part_a: {e}", file=sys.stderr)
        return []
    return run_part_a(
        web_apps,
        log_result=lambda r: write_record(log_file, r),
    )


def dispatch_part_b(config, log_file):
    """Import and run Part B. Stub-safe: skips silently if part_b is missing."""
    native_apps = config.get("native_apps", [])
    if not native_apps:
        return []
    try:
        from part_b import run_part_b
    except ImportError as e:
    
        print(f"[runner] Skipping Part B (not yet wired): {e}", file=sys.stderr)
        return []
    return run_part_b(
        native_apps,
        log_result=lambda r: write_record(log_file, r),
    )


def dispatch_part_c(config, log_file):
    """Import and run Part C. Stub-safe: skips silently if part_c is missing."""
    desktop_apps = config.get("desktop_presence", [])
    if not desktop_apps:
        return []
    try:
        from part_c import run_part_c
    except ImportError as e:
        print(f"[runner] Skipping Part C (not yet wired): {e}", file=sys.stderr)
        return []
    return run_part_c(
        desktop_apps,
        log_result=lambda r: write_record(log_file, r),
    )


# ---------------------------------------------------------------------------
# Optional LLM analysis (post-run)
# ---------------------------------------------------------------------------

def run_analyse(log_path, prompt_file):
    """
    Optionally invoke analyse.py against the freshly-written log. The agent
    itself does not embed an LLM at runtime — analyse.py is a separate,
    model-agnostic script that reads from environment variables [1]. This
    keeps the agent lightweight and the LLM layer swappable across providers.
    """
    analyse_script = Path(__file__).resolve().parent / "analyse.py"
    if not analyse_script.exists():
        print(f"[runner] analyse.py not found at {analyse_script}; skipping",
              file=sys.stderr)
        return
    print(f"\n[runner] Invoking LLM analysis on {log_path} ...")
    subprocess.run(
        [sys.executable, str(analyse_script),
         "--log", str(log_path),
         "--prompt", str(prompt_file)],
        check=False,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="JioPC Automated Testing Agent — runner core",
    )
    parser.add_argument(
        "--config", required=True,
        help="Path to the YAML configuration (e.g. configs/jiopc-agent.yaml)",
    )
    parser.add_argument(
        "--part", choices=["A", "B", "C"], default=None,
        help="Run only one component (A, B, or C). Default: run all.",
    )
    parser.add_argument(
        "--analyse", action="store_true",
        help="After the run, invoke analyse.py against the log file.",
    )
    args = parser.parse_args()

    # --- Load config ---
    config = load_config(args.config)
    log_dir = config["agent"]["log_dir"]
    prompt_file = config["agent"].get("llm_prompt_file", "")

    # --- Open log file under ~/.local/share/jiopc/agent/ ---
    log_file, log_path = setup_log_file(log_dir)
    print(f"[runner] Writing log to {log_path}")

    # --- Determine run order (configurable per spec) ---
    # The spec requires Parts A/B/C to run in sequence with configurable
    # order [1]. Default is A, B, C; YAML can override via agent.run_order;
    # CLI --part runs just one component for fast iteration.
    run_order = config["agent"].get("run_order", ["A", "B", "C"])
    if args.part:
        run_order = [args.part]

    run_started_at = datetime.now(timezone.utc).isoformat()
    all_results = []

    try:
        for part in run_order:
            print(f"[runner] === Running Part {part} ===")
            if part == "A":
                all_results.extend(dispatch_part_a(config, log_file))
            elif part == "B":
                all_results.extend(dispatch_part_b(config, log_file))
            elif part == "C":
                all_results.extend(dispatch_part_c(config, log_file))
            else:
                print(f"[runner] Unknown part: {part}", file=sys.stderr)

    finally:
        # Always write the summary block, even on partial / interrupted runs,
        # so the LLM analysis layer always has something parseable to read [1].
        run_ended_at = datetime.now(timezone.utc).isoformat()
        summary = write_summary_block(
            log_file, all_results, run_started_at, run_ended_at,
        )
        log_file.close()

    # --- Print a concise terminal summary for the human operator ---
    print("\n[runner] ===== Run Summary =====")
    print(f"  Total tests:  {summary['total_tests']}")
    print(f"  Passed:       {summary['passed']}")
    print(f"  Blocked:      {summary['blocked']}")
    print(f"  Failed:       {summary['failed']}")
    print(f"  By component: {summary['by_component']}")
    print(f"  Log file:     {log_path}")
    print(f"  Exit code:    {summary['exit_code']}")
    print("[runner] =========================\n")

    # --- Optional LLM analysis ---
    if args.analyse:
        run_analyse(log_path, prompt_file)

    # --- Exit with the spec-mandated status code ---
    # Spec: "Exit with code 0 if all required tests pass, non-zero otherwise" [1].
    # This is what lets the agent be used as a manual gate before promoting
    # the OS Image patch [1].
    sys.exit(summary["exit_code"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl-C during a run — exit non-zero so a CI gate treats it as failure.
        print("\n[runner] Interrupted by user", file=sys.stderr)
        sys.exit(130)
    except FileNotFoundError as e:
        # Misconfigured config path — distinct exit code from a test failure.
        print(f"[runner] {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        # Defensive: a runner crash is itself a failure signal for the gate.
        print(f"[runner] Unhandled error: {e}", file=sys.stderr)
        sys.exit(1)

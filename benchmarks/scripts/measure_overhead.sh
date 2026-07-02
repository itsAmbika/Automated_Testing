#!/usr/bin/env bash
#
# measure_overhead.sh — Empirical per-app agent overhead measurement.
#
# The spec requires the agent's measured overhead to be subtracted from
# reported launch times in Part B, and the figure to be clearly stated in
# the benchmark report. [1]
#
# This script produces two data points:
#   1. Reference launch time WITHOUT the agent — 5 trials of `featherpad &`
#      polled at max bash-loop rate via pgrep -x. Median is reported.
#   2. Agent-reported raw_launch_ms across all successful Part B apps —
#      read from the most recent test_run_<timestamp>.log.
#
# The real per-app overhead is: median(agent raw_launch_ms) - median(reference).
# In the current implementation, the agent's psutil-based detection is
# faster than the bash-loop reference, so the effective subtraction is 0.
#
# Usage:
#   ./benchmarks/scripts/measure_overhead.sh
#
# Prerequisites:
#   - featherpad installed (sudo apt install featherpad)
#   - Part B has been run at least once (test_run_<ts>.log exists)

set -euo pipefail

REFERENCE_TRIALS=5
LOG_DIR="$HOME/.local/share/jiopc/agent"
REFERENCE_APP="featherpad"

echo "========================================================"
echo "  JioPC Agent — Per-App Overhead Measurement"
echo "========================================================"
echo

# --- Step 1: reference launches without the agent ---
echo "Step 1: Reference launches of ${REFERENCE_APP} (no agent)"
echo "--------------------------------------------------------"

if ! command -v "$REFERENCE_APP" > /dev/null; then
  echo "ERROR: ${REFERENCE_APP} not installed. Run: sudo apt install ${REFERENCE_APP}"
  exit 1
fi

# Ensure no pre-existing instance
pkill -x "$REFERENCE_APP" 2>/dev/null || true
sleep 1

reference_times=()
for i in $(seq 1 $REFERENCE_TRIALS); do
  # Millisecond-precision timestamps
  start_ms=$(date +%s%3N)
  "$REFERENCE_APP" > /dev/null 2>&1 &
  fp_pid=$!

  # Poll until the process appears in the process table
  while ! pgrep -x "$REFERENCE_APP" > /dev/null; do :; done
  end_ms=$(date +%s%3N)

  elapsed=$(( end_ms - start_ms ))
  reference_times+=($elapsed)
  echo "  Trial $i: ${elapsed} ms"

  # Clean up before next trial
  kill "$fp_pid" 2>/dev/null || true
  pkill -x "$REFERENCE_APP" 2>/dev/null || true
  sleep 2
done

# Compute reference median (sorted middle value)
reference_median=$(printf '%s\n' "${reference_times[@]}" | sort -n | \
  awk 'BEGIN{c=0} {a[c++]=$1} END{print a[int(c/2)]}')

echo
echo "  Reference median: ${reference_median} ms"
echo

# --- Step 2: read agent raw_launch_ms from most recent log ---
echo "Step 2: Agent-reported raw_launch_ms from most recent Part B run"
echo "--------------------------------------------------------"

latest_log=$(ls -t "${LOG_DIR}"/test_run_*.log 2>/dev/null | head -1 || true)
if [ -z "$latest_log" ]; then
  echo "ERROR: no test_run log found in ${LOG_DIR}"
  echo "Run Part B first: python jiopc_agent.py --config configs/jiopc-agent.yaml --part B"
  exit 1
fi

echo "  Log file: ${latest_log}"
echo

python3 - "$latest_log" "$reference_median" << 'PYEOF'
import json, sys, statistics

log_path = sys.argv[1]
reference_median = int(sys.argv[2])

raws = []
with open(log_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("component") == "B" and r.get("result") == "PASS":
            raw = r.get("raw_launch_ms")
            if raw is not None:
                raws.append((r["test_name"], raw))

if not raws:
    print("  No Part B PASS records with raw_launch_ms found.")
    print("  Ensure src/part_b.py records entry['raw_launch_ms'] = raw_ms.")
    sys.exit(1)

print(f"  {'app':30s}  {'raw_launch_ms':>14s}")
for name, raw in raws:
    print(f"  {name:30s}  {raw:>14d}")

values = [r for _, r in raws]
agent_median = statistics.median(values)
print()
print(f"  Agent median raw_launch_ms: {agent_median:.0f} ms")
print(f"  Reference median:           {reference_median} ms")
print()

overhead = agent_median - reference_median
if overhead <= 0:
    print(f"  Computed overhead: {overhead:.0f} ms  (agent path is faster than reference)")
    print(f"  Recommendation: set AGENT_POLL_OVERHEAD_MS = 0 in src/part_b.py")
    print(f"                  and report worst-case polling latency (500 ms) as an upper bound.")
else:
    print(f"  Computed overhead: {overhead:.0f} ms")
    print(f"  Recommendation: set AGENT_POLL_OVERHEAD_MS = {overhead:.0f} in src/part_b.py")

print()
print("  This figure must be stated clearly in benchmarks/results.md per spec §2.5.")
PYEOF

echo
echo "========================================================"

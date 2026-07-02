#!/usr/bin/env bash
#
# sampler.sh — 1 Hz CPU and RAM sampler for the JioPC Automated Testing Agent.
#
# Waits for the agent to appear (up to 60s), then samples every 1 second while
# any agent process is alive. Writes CSV to stdout (redirect to a file when
# invoking). Exits ~3 seconds after the last agent process disappears.
#
# The pgrep pattern deliberately matches ONLY the agent's own process tree —
# jiopc_agent.py, Playwright's Chromium, and Xvfb. Apps launched by Part B
# are excluded because they are test targets, not part of the agent
# footprint, and they run isolated under Xvfb.
#
# Usage:
#   # In terminal 1:
#   ./benchmarks/scripts/sampler.sh > benchmarks/raw/cpu_ram_sample.csv
#   # In terminal 2 (within 60 seconds):
#   python jiopc_agent.py --config configs/jiopc-agent.yaml
#
# CSV columns: epoch_s,pid,pcpu,rss_kb,cmd
#
# References the spec's Section 2.5 measurement methodology (ps or /proc
# during active run for CPU; VmRSS via /proc or psutil for RAM). [1]

set -euo pipefail

WAIT_FOR_AGENT_S=60           # how long to wait for the agent to appear
IDLE_TICKS_BEFORE_EXIT=3      # consecutive empty samples before we stop
SAMPLE_INTERVAL_S=1           # 1 Hz sampling
AGENT_PATTERN="jiopc_agent\.py|Xvfb"

# --- CSV header ---
echo "epoch_s,pid,pcpu,rss_kb,cmd"

# --- Phase 1: wait for the agent to appear ---
deadline=$(( $(date +%s) + WAIT_FOR_AGENT_S ))
until pgrep -f "$AGENT_PATTERN" > /dev/null; do
  if [ $(date +%s) -ge $deadline ]; then
    echo "sampler.sh: agent did not start within ${WAIT_FOR_AGENT_S}s; exiting" >&2
    exit 1
  fi
  sleep 0.5
done

# --- Phase 2: sample at 1 Hz while agent is running ---
missing_count=0
while true; do
  PIDS=$(pgrep -f "$AGENT_PATTERN" | tr '\n' ',' | sed 's/,$//')

  if [ -n "$PIDS" ]; then
    missing_count=0
    ts=$(date +%s)
    # ps -o with trailing '=' suppresses the header on every call
    ps -p "$PIDS" -o pid=,pcpu=,rss=,comm= 2>/dev/null | \
      awk -v ts="$ts" '{
        # Fields: pid pcpu rss comm...
        # Rebuild comm in case it contained spaces
        cmd = $4
        for (i = 5; i <= NF; i++) cmd = cmd " " $i
        printf "%s,%s,%s,%s,%s\n", ts, $1, $2, $3, cmd
      }'
  else
    missing_count=$(( missing_count + 1 ))
    if [ $missing_count -ge $IDLE_TICKS_BEFORE_EXIT ]; then
      break
    fi
  fi

  sleep $SAMPLE_INTERVAL_S
done

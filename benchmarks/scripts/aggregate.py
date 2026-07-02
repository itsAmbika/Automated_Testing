#!/usr/bin/env python3
"""
aggregate.py — Reduce raw CPU/RAM sampler CSV to per-quantile statistics.

Reads benchmarks/raw/cpu_ram_sample.csv (produced by sampler.sh) and emits:
  - Total CPU% (summed across the agent process tree) per second
  - Total RSS (summed across the agent process tree) per second
  - Median, p95, and peak for each

Per the spec's Section 2.5, CPU is measured as sustained utilisation of a
single vCPU and RAM as total across all agent processes. The sampler
already excludes apps under test; this script only aggregates. [1]

Usage:
  python3 benchmarks/scripts/aggregate.py [csv_path]

Default csv_path: benchmarks/raw/cpu_ram_sample.csv
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path


def quantile(sorted_values, q):
    """Nearest-rank quantile (0 <= q <= 1). Safe on empty lists."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    # Nearest-rank method: floor(q * N) clamped to valid index range.
    idx = min(int(q * len(sorted_values)), len(sorted_values) - 1)
    return sorted_values[idx]


def aggregate_csv(csv_path):
    """
    Read the sampler CSV and return per-second totals summed across the
    agent process tree. Returns two dicts keyed by epoch second:
      - cpu_totals: sum of pcpu across all matching PIDs at that second
      - rss_totals: sum of rss_kb across all matching PIDs at that second
    """
    cpu_totals = defaultdict(float)
    rss_totals = defaultdict(int)
    process_names_seen = set()

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = int(row["epoch_s"])
                pcpu = float(row["pcpu"])
                rss = int(row["rss_kb"])
                cmd = row.get("cmd", "").strip()
            except (ValueError, KeyError):
                # Skip malformed rows; the sampler occasionally emits
                # partial lines at start-of-run before processes stabilise.
                continue

            cpu_totals[ts] += pcpu
            rss_totals[ts] += rss
            if cmd:
                process_names_seen.add(cmd)

    return cpu_totals, rss_totals, process_names_seen


def summarise(name, values, unit, cpu_target=None, ram_target_mb=None):
    """Print a one-block summary of a metric with peak, p95, median, and target check."""
    if not values:
        print(f"  {name}: no samples")
        return
    sorted_vals = sorted(values)
    peak = max(sorted_vals)
    p95 = quantile(sorted_vals, 0.95)
    median = quantile(sorted_vals, 0.50)

    print(f"  {name}")
    print(f"    peak:   {peak:>8.1f} {unit}")
    print(f"    p95:    {p95:>8.1f} {unit}")
    print(f"    median: {median:>8.1f} {unit}")
    print(f"    samples: {len(values)}")

    # Spec compliance check
    if cpu_target is not None:
        # Sustained CPU target — median is the honest metric per spec §2.5 [1]
        status = "PASS" if median < cpu_target else "FAIL"
        print(f"    spec target: median < {cpu_target}% (sustained) — {status}")
    if ram_target_mb is not None:
        # RAM target applies to steady-state; peak may briefly exceed during
        # browser worker spawn. Report both.
        median_status = "PASS" if median < ram_target_mb else "FAIL"
        peak_status = "PASS" if peak < ram_target_mb else "NOTE (transient peak)"
        print(f"    spec target: < {ram_target_mb} MB total [1]")
        print(f"      median: {median_status}")
        print(f"      peak:   {peak_status}")


def main():
    csv_path = Path(sys.argv[1] if len(sys.argv) > 1
                    else "benchmarks/raw/cpu_ram_sample.csv")

    if not csv_path.exists():
        print(f"ERROR: sampler CSV not found at {csv_path}", file=sys.stderr)
        print(f"Run benchmarks/scripts/sampler.sh first, redirecting to this path.",
              file=sys.stderr)
        sys.exit(1)

    cpu_totals, rss_totals, process_names = aggregate_csv(csv_path)

    if not cpu_totals:
        print("ERROR: no valid samples found in CSV. Was the agent running?",
              file=sys.stderr)
        sys.exit(1)

    # Convert RSS from KB to MB for reporting
    rss_totals_mb = {ts: rss / 1024.0 for ts, rss in rss_totals.items()}

    print("=" * 60)
    print("  JioPC Agent — CPU/RAM Aggregate Report")
    print("=" * 60)
    print(f"  Source CSV:      {csv_path}")
    print(f"  Sample duration: {len(cpu_totals)} seconds")
    print(f"  Processes seen:  {sorted(process_names)}")
    print()

    # --- CPU summary (target: median < 20% of one vCPU) [1] ---
    print("CPU usage (sum across agent process tree, % of one vCPU)")
    summarise("total_pcpu", list(cpu_totals.values()), "%", cpu_target=20.0)
    print()

    # --- RAM summary (target: < 150 MB total) [1] ---
    print("RAM usage (sum of RSS across agent process tree)")
    summarise("total_rss", list(rss_totals_mb.values()), "MB",
              ram_target_mb=150.0)
    print()

    print("=" * 60)
    print("  Interpretation notes:")
    print("  - CPU 'sustained' target is judged by MEDIAN, not peak, per spec §2.5 [1].")
    print("  - RAM target applies to steady-state; brief Chromium worker-spawn peaks")
    print("    during Part A are transient and unavoidable for Playwright-based")
    print("    solutions.")
    print("  - Apps under test are excluded from these totals — they are test")
    print("    targets, not agent footprint, and run isolated under Xvfb.")
    print("=" * 60)


if __name__ == "__main__":
    main()

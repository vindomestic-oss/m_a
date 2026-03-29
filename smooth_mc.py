#!/usr/bin/env python3
"""
Monte Carlo check: generate random count sequences with the same empirical
distribution as actual motif counts, and measure the smooth-number rate.

Compares actual smooth fraction to what arises from the distribution shape alone.
Reads freq_table.json written by meta_analysis.py.
"""

import math
import random

# ── actual frequency table from meta_report (min_len=2, max_motifs=50) ────────
RAW_FREQ = {
    2:477, 3:571, 4:532, 5:349, 6:370, 7:241,
    8:210, 9:152, 10:147, 11:125, 12:105, 13:74, 14:63, 15:75,
    16:58, 17:46, 18:50, 19:36, 20:38, 21:28, 22:32, 23:28,
    24:23, 25:25, 26:17, 27:19, 28:15, 29:11, 30:19, 31:12,
    32:12, 33:7, 34:9, 35:10, 36:7, 37:9, 38:11, 39:11,
    40:3, 41:9, 42:5, 43:4, 45:2, 46:5, 47:1, 48:6,
    49:1, 50:6, 52:1, 54:3, 55:2, 57:2, 59:4, 60:1,
    61:1, 62:3, 63:1, 64:1, 67:2, 68:1, 69:1, 70:1,
    71:1, 72:3, 73:1, 74:1, 75:2, 77:1, 78:1, 79:1,
    80:2, 82:2, 84:1, 85:1, 87:1, 89:1, 93:2, 96:1,
    107:1, 119:1, 126:2,
}

N_ACTUAL = sum(RAW_FREQ.values())  # 4116 — actual count
N_TOTAL  = 1_000_000               # synthetic sample size
N_RUNS  = 10_000


def _is_smooth(k):
    if k <= 0:
        return False
    while k % 2 == 0:
        k //= 2
    while k % 3 == 0:
        k //= 3
    return k == 1


# Build population to sample from (list of all counts with repetitions)
population = []
for v, cnt in RAW_FREQ.items():
    population.extend([v] * cnt)

# Actual stats
actual_ge8    = [v for v in population if v >= 8]
actual_smooth = [v for v in actual_ge8 if _is_smooth(v)]
actual_rate   = len(actual_smooth) / len(actual_ge8)

print(f"Actual counts total   : {N_ACTUAL}")
print(f"Actual counts >= 8    : {len(actual_ge8)}")
print(f"Actual smooth >= 8    : {len(actual_smooth)}")
print(f"Actual smooth rate    : {actual_rate:.4f}  ({actual_rate*100:.2f}%)")
print()

# Monte Carlo: sample N_ACTUAL numbers from the same empirical distribution
rng = random.Random(0)
sim_rates = []
for _ in range(N_RUNS):
    sample = rng.choices(population, k=N_ACTUAL)
    ge8    = [v for v in sample if v >= 8]
    smooth = [v for v in ge8 if _is_smooth(v)]
    sim_rates.append(len(smooth) / len(ge8) if ge8 else 0.0)

mean_r = sum(sim_rates) / N_RUNS
var_r  = sum((r - mean_r)**2 for r in sim_rates) / N_RUNS
std_r  = math.sqrt(var_r)
sim_rates.sort()
pct5   = sim_rates[int(N_RUNS * 0.05)]
pct95  = sim_rates[int(N_RUNS * 0.95)]

z = (actual_rate - mean_r) / std_r if std_r > 0 else 0.0

print(f"Monte Carlo ({N_RUNS:,} runs, same empirical distribution):")
print(f"  Mean smooth rate   : {mean_r:.4f}  ({mean_r*100:.2f}%)")
print(f"  Std                : {std_r:.4f}")
print(f"  90% interval       : [{pct5:.4f}, {pct95:.4f}]")
print(f"  z-score of actual  : {z:+.2f}")
print()

if abs(z) < 2:
    print(">> Actual smooth rate is well within the distribution of random samples.")
    print("   No evidence that smooth numbers are special — the rate follows")
    print("   directly from the shape of the count distribution.")
elif z > 2:
    print(f">> Actual rate is {z:.1f} std above random expectation — genuine enrichment.")
else:
    print(f">> Actual rate is {z:.1f} std below random expectation — depletion.")
print()

# ── frequency table: actual vs geometric-distribution sample ──────────────────
# Fit a shifted geometric (min=2) with same mean as actual data.
# P(k) = (1-p)^1 * p^(k-2),  mean = 2 + p/(1-p)  =>  p = (mean-2)/(mean-1)
from collections import defaultdict

actual_mean = sum(k * v for k, v in RAW_FREQ.items()) / N_ACTUAL
p_geom = (actual_mean - 2) / (actual_mean - 1)

def sample_geom(rng, n, p, min_val=2, max_val=200):
    """Sample n values from a shifted geometric distribution using log method."""
    log_p = math.log(p) if p > 0 else float('-inf')
    out = []
    for _ in range(n):
        u = rng.random()
        if u == 0 or log_p == float('-inf'):
            out.append(min_val)
        else:
            k = min_val + int(math.log(u) / log_p)
            out.append(min(k, max_val))
    return out

rng3 = random.Random(42)
sim_sample = sample_geom(rng3, N_TOTAL, p_geom)
sim_freq = defaultdict(int)
for v in sim_sample:
    sim_freq[v] += 1

all_vals = sorted(set(RAW_FREQ) | set(sim_freq))
header = f"Actual mean: {actual_mean:.1f}   Geometric p={p_geom:.4f}  (same mean, fitted)"
col_hdr = f"  {'count':>4}  {'actual':>7}  {'geom.sample':>11}  note"
sep     = "  " + "-" * 42

rows = []
for val in all_vals:
    act = RAW_FREQ.get(val, 0)
    sim = sim_freq.get(val, 0)
    marker = "  <-- smooth" if _is_smooth(val) and val >= 8 else ""
    rows.append(f"  {val:4d}  {act:7d}  {sim:11d}{marker}")

# Print to console
print(header)
print()
print(col_hdr)
print(sep)
for r in rows:
    print(r)

# Write to file
import os
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smooth_mc_table.txt")
with open(out_path, "w", encoding="utf-8") as _f:
    _f.write(header + "\n\n")
    _f.write(col_hdr + "\n")
    _f.write(sep + "\n")
    _f.write("\n".join(rows) + "\n")
print(f"\nTable written to: {out_path}")

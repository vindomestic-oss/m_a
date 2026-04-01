#!/usr/bin/env python3
"""
Meta-analysis of motif occurrence counts across all kern files.
Runs motif analysis (MEI only, no SVG rendering) on every file,
collects occurrence counts, and tests whether smooth numbers (2^a·3^b, >=8)
appear more often than chance.

Usage:  python meta_analysis.py
Output: meta_report.txt
"""

import json
import math
import multiprocessing
import os
import sys
from collections import defaultdict
from datetime import datetime

# ── import shared functions from kern_reader ──────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
import kern_reader as kr   # initialises verovio _vtk at import


# ── subprocess worker (isolated from verovio segfaults) ──────────────────────

def _worker_func(path, q):
    """Runs in a separate process; puts list of motif dicts (or None) into q."""
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        import kern_reader as _kr
        _kr.check_file(path)
        ext = path.rsplit('.', 1)[-1].lower()
        if ext == 'mxl':
            import zipfile as _zf
            with _zf.ZipFile(path) as z:
                xml_name = next(n for n in z.namelist()
                                if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n)
                raw = z.read(xml_name)
                if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                    content = raw.decode('utf-16')
                elif raw[:3] == b'\xef\xbb\xbf':
                    content = raw.decode('utf-8-sig')
                else:
                    content = raw.decode('utf-8', errors='replace')
        else:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        if ext == 'krn':
            content = _kr.prepare_grand_staff(content)
            content = _kr.add_beam_markers(content)
        _kr._vtk.setOptions({
            'pageWidth':        2200,
            'adjustPageHeight': True,
            'scale':            35,
            'font':             'Leipzig',
        })
        ok = _kr._vtk.loadData(content)
        if not ok:
            q.put(None)
            return
        mei_str = _kr._vtk.getMEI()
        motifs = _kr.analyze_motifs(_kr._vtk, mei_str=mei_str)
        q.put([{'count': m['count'], 'length': m['length']} for m in motifs])
    except Exception:
        q.put(None)


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_smooth(k):
    """True if k = 2^a * 3^b  (a,b >= 0)."""
    if k <= 0:
        return False
    while k % 2 == 0:
        k //= 2
    while k % 3 == 0:
        k //= 3
    return k == 1


def smooth_numbers_in_range(lo, hi):
    """Return sorted list of smooth numbers in [lo, hi]."""
    result = []
    a = 0
    while True:
        p2 = 2 ** a
        if p2 > hi:
            break
        b = 0
        while True:
            v = p2 * (3 ** b)
            if v > hi:
                break
            if v >= lo:
                result.append(v)
            b += 1
        a += 1
    return sorted(result)


_TIMEOUT = 90  # seconds per file

def analyze_file(ctx, path):
    """
    Run motif analysis in a fresh subprocess with timeout.
    Handles segfaults (process crash) and hangs (timeout).
    Returns list of {'count': int, 'length': int} dicts, or None.
    """
    q = ctx.Queue()
    p = ctx.Process(target=_worker_func, args=(path, q))
    p.start()
    try:
        result = q.get(timeout=_TIMEOUT)
    except Exception:
        result = None
    p.join(timeout=5)
    if p.is_alive():
        p.terminate()
        p.join()
    return result


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--filter', default=None,
                        help='Only analyse files whose rel path contains this substring '
                             '(comma-separated → OR logic, e.g. "wtc,inventions")')
    parser.add_argument('--output', default=None,
                        help='Output report file path (default: meta_report.txt)')
    parser.add_argument('--lo', type=int, default=8,
                        help='Lower bound for smooth-count analysis (default: 8)')
    args = parser.parse_args()

    _base = os.path.dirname(os.path.abspath(__file__))
    _xml_dir = os.path.join(_base, 'lilypond', 'musicxml')
    _xml_files = []
    if os.path.isdir(_xml_dir):
        for _name in sorted(os.listdir(_xml_dir)):
            if _name.lower().endswith('.xml'):
                _xml_files.append((
                    os.path.join('lilypond', 'musicxml', _name),
                    os.path.join(_xml_dir, _name),
                ))

    all_files = kr.find_kern_files(kr.KERN_DIR) + kr.find_music21_files() + _xml_files
    if args.filter:
        terms = [t.strip().lower() for t in args.filter.split(',')]
        files = [(r, f) for r, f in all_files
                 if any(t in r.lower() for t in terms)]
    else:
        files = [(r, f) for r, f in all_files if not r.startswith('music21/')]
    report_path_override = args.output
    lo = args.lo

    total = len(files)
    print(f"Found {total} kern files{f' matching {args.filter!r}' if args.filter else ''}. Starting analysis…")

    results = {}          # path → list of motif dicts (or None)
    n_ok = 0
    n_err = 0

    ctx = multiprocessing.get_context('spawn')
    for idx, (rel, full) in enumerate(files):
        if (idx + 1) % 10 == 0 or idx == 0:
            print(f"  {idx+1}/{total}  {rel}", flush=True)
        motifs = analyze_file(ctx, full)
        if motifs is None:
            n_err += 1
        else:
            n_ok += 1
            results[rel] = motifs

    print(f"Done. OK={n_ok}, errors/empty={n_err}")

    # ── collect all occurrence counts ─────────────────────────────────────────
    all_counts = []          # every single motif count from every file
    file_counts = {}         # rel_path → [counts]
    for rel, motifs in results.items():
        counts = [m['count'] for m in motifs]
        file_counts[rel] = counts
        all_counts.extend(counts)

    if not all_counts:
        print("No counts collected. Exiting.")
        return

    all_counts_sorted = sorted(all_counts)
    counts_ge8 = [c for c in all_counts if c >= lo]
    smooth_ge8  = [c for c in counts_ge8 if _is_smooth(c)]

    # frequency table of all counts
    freq = defaultdict(int)
    for c in all_counts:
        freq[c] += 1

    # ── statistical test ──────────────────────────────────────────────────────
    # Question: among all observed occurrence counts >= 8, are smooth numbers
    # over-represented compared to what we'd expect if counts were drawn
    # uniformly at random from integers in [8, max_count]?
    #
    # Expected density of smooth numbers in [8, M]:
    #   density(M) = |{k : 8 <= k <= M, k smooth}| / (M - 7)
    #
    # Because larger smooth numbers are rarer, we also compute a
    # "log-uniform" expected count: weight each integer k by 1/k (Benford-like),
    # then the expected smooth fraction among integers in [8, M] under 1/k weighting
    # is  sum(1/k for k smooth in [8,M]) / sum(1/k for k in [8,M]).

    max_c = max(counts_ge8) if counts_ge8 else lo

    smooth_in_range = smooth_numbers_in_range(lo, max_c)
    n_integers_in_range = max_c - lo + 1
    n_smooth_in_range   = len(smooth_in_range)

    # Uniform density
    density_uniform = n_smooth_in_range / n_integers_in_range if n_integers_in_range > 0 else 0

    # Log-uniform density  (accounts for "larger numbers are rarer" prior)
    sum_inv_all    = sum(1.0 / k for k in range(lo, max_c + 1))
    sum_inv_smooth = sum(1.0 / k for k in smooth_in_range)
    density_log    = (sum_inv_smooth / sum_inv_all) if sum_inv_all > 0 else 0

    n_obs_ge8     = len(counts_ge8)
    n_obs_smooth  = len(smooth_ge8)
    freq_smooth   = defaultdict(int)
    for c in smooth_ge8:
        freq_smooth[c] += 1

    expected_uniform = n_obs_ge8 * density_uniform
    expected_log     = n_obs_ge8 * density_log
    ratio_uniform    = n_obs_smooth / expected_uniform if expected_uniform > 0 else float('inf')
    ratio_log        = n_obs_smooth / expected_log     if expected_log     > 0 else float('inf')

    # ── per-file smooth hits ──────────────────────────────────────────────────
    files_with_smooth = {rel: [c for c in counts if c >= lo and _is_smooth(c)]
                         for rel, counts in file_counts.items()
                         if any(c >= lo and _is_smooth(c) for c in counts)}

    # ── write report ──────────────────────────────────────────────────────────
    report_path = report_path_override or os.path.join(os.path.dirname(__file__), "meta_report.txt")
    lines = []
    W = 72

    def rule(ch='='):
        lines.append(ch * W)

    def h(title):
        rule()
        lines.append(title.upper())
        rule()

    rule('=')
    lines.append("KERN FILE MOTIF META-ANALYSIS")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    rule('=')
    lines.append("")

    h("1. files processed")
    lines.append(f"Total files found      : {total}")
    lines.append(f"Successfully analysed  : {n_ok}")
    lines.append(f"Errors / empty         : {n_err}")
    lines.append(f"Files with motifs      : {len(results)}")
    lines.append("")

    h("2. occurrence count overview")
    lines.append(f"Total motif-occurrences collected : {len(all_counts)}")
    lines.append(f"Min / Max count                   : {min(all_counts)} / {max(all_counts)}")
    mean_c = sum(all_counts) / len(all_counts)
    med_c  = sorted(all_counts)[len(all_counts) // 2]
    lines.append(f"Mean / Median                     : {mean_c:.1f} / {med_c}")
    lines.append(f"Counts >= {lo}                       : {n_obs_ge8}")
    lines.append("")

    lines.append("Frequency table of ALL occurrence counts (count : frequency):")
    for val in sorted(freq):
        marker = "  <-- smooth (2^a·3^b)" if _is_smooth(val) and val >= 8 else ""
        lines.append(f"  {val:4d} : {freq[val]}{marker}")
    lines.append("")

    h("3. smooth numbers (2^a·3^b) observed as occurrence counts")
    lines.append(f"Range analysed        : [{lo}, {max_c}]")
    lines.append(f"Smooth numbers in range: {n_smooth_in_range}  "
                 f"(out of {n_integers_in_range} integers)")
    lines.append(f"  {smooth_in_range}")
    lines.append("")
    lines.append(f"Observed smooth counts (>= 8): {n_obs_smooth}")
    if freq_smooth:
        for val in sorted(freq_smooth):
            lines.append(f"  {val} × {freq_smooth[val]}")
    else:
        lines.append("  (none)")
    lines.append("")

    h("4. statistical test – are smooth counts over-represented?")
    lines.append("Two null models compared:")
    lines.append("")
    lines.append("  A) UNIFORM prior: every integer in [8, max] equally likely")
    lines.append(f"     Smooth density        : {n_smooth_in_range} / {n_integers_in_range}"
                 f" = {density_uniform:.4f}  ({density_uniform*100:.2f}%)")
    lines.append(f"     Expected smooth counts: {expected_uniform:.1f}")
    lines.append(f"     Observed smooth counts: {n_obs_smooth}")
    lines.append(f"     Enrichment ratio       : {ratio_uniform:.2f}x")
    lines.append("")
    lines.append("  B) LOG-UNIFORM prior: larger numbers are intrinsically rarer")
    lines.append("     (weight 1/k, reflects that high occurrence counts are less")
    lines.append("      common in musical analysis regardless of smoothness)")
    lines.append(f"     Smooth log-density     : {density_log:.4f}  ({density_log*100:.2f}%)")
    lines.append(f"     Expected smooth counts : {expected_log:.1f}")
    lines.append(f"     Observed smooth counts : {n_obs_smooth}")
    lines.append(f"     Enrichment ratio       : {ratio_log:.2f}x")
    lines.append("")
    if ratio_log > 2:
        lines.append("  >> Smooth counts appear MORE than 2x as often as random expectation.")
        lines.append("     This suggests a non-trivial alignment between motif repetition")
        lines.append("     structure and binary/ternary metric organisation.")
    elif ratio_log > 1.2:
        lines.append("  >> Modest enrichment. Smooth counts slightly over-represented.")
    else:
        lines.append("  >> No notable enrichment. Smooth counts close to random expectation.")
    lines.append("")

    # ── shift test ────────────────────────────────────────────────────────────
    # Verify enrichment by comparing smooth density of real counts vs shifted
    # counts (+1 and -1).  If smooth numbers are genuinely over-represented,
    # shifting the distribution should reduce their density.
    # Start from lo_shift=14 to avoid boundary effects near smooth numbers 9,12.
    lo_shift = max(lo, 14)
    counts_shift = [c for c in all_counts if c >= lo_shift]
    n_shift = len(counts_shift)
    def _smooth_density(values):
        return sum(1 for v in values if _is_smooth(v)) / len(values) if values else 0
    dens_real   = _smooth_density(counts_shift)
    dens_plus1  = _smooth_density([c + 1 for c in counts_shift])
    dens_minus1 = _smooth_density([c - 1 for c in counts_shift])
    n_real   = sum(1 for c in counts_shift if _is_smooth(c))
    n_plus1  = sum(1 for c in counts_shift if _is_smooth(c + 1))
    n_minus1 = sum(1 for c in counts_shift if _is_smooth(c - 1))

    h(f"5. shift test – smooth density vs ±1 shifted counts (threshold {lo_shift})")
    lines.append(f"Counts >= {lo_shift}: {n_shift} observations")
    lines.append("")
    lines.append(f"  {'':20s}  {'n_smooth':>8s}  {'density':>8s}  {'ratio vs real':>13s}")
    lines.append(f"  {'-'*20}  {'-'*8}  {'-'*8}  {'-'*13}")
    lines.append(f"  {'Real counts':20s}  {n_real:8d}  {dens_real:8.4f}  {'(baseline)':>13s}")
    r_p1 = dens_real / dens_plus1 if dens_plus1 > 0 else float('inf')
    r_m1 = dens_real / dens_minus1 if dens_minus1 > 0 else float('inf')
    lines.append(f"  {'Shifted +1 (c+1)':20s}  {n_plus1:8d}  {dens_plus1:8.4f}  {r_p1:>12.2f}x")
    lines.append(f"  {'Shifted -1 (c-1)':20s}  {n_minus1:8d}  {dens_minus1:8.4f}  {r_m1:>12.2f}x")
    lines.append("")

    # Also show for larger thresholds
    lines.append("  Breakdown by threshold (real density / +1 density / -1 density):")
    for thr in [14, 16, 18, 24, 32, 36, 48, 64, 96]:
        cc = [c for c in all_counts if c >= thr]
        if len(cc) < 5:
            break
        dr  = _smooth_density(cc)
        dp  = _smooth_density([c + 1 for c in cc])
        dm  = _smooth_density([c - 1 for c in cc])
        rp  = dr / dp  if dp  > 0 else float('inf')
        rm  = dr / dm  if dm  > 0 else float('inf')
        lines.append(f"  >= {thr:3d}  n={len(cc):5d}  real={dr:.4f}  +1={dp:.4f}({rp:.2f}x)  -1={dm:.4f}({rm:.2f}x)")
    lines.append("")

    # Verdict: also check larger thresholds for robustness
    higher_thrs = [t for t in [16, 24, 32, 48] if len([c for c in all_counts if c >= t]) >= 5]
    wins_p1 = sum(1 for t in higher_thrs
                  for cc in [[c for c in all_counts if c >= t]]
                  if _smooth_density(cc) > _smooth_density([c+1 for c in cc]))
    wins_m1 = sum(1 for t in higher_thrs
                  for cc in [[c for c in all_counts if c >= t]]
                  if _smooth_density(cc) > _smooth_density([c-1 for c in cc]))
    if dens_real > dens_plus1 and dens_real > dens_minus1:
        lines.append(f"  >> Real counts have HIGHER smooth density than both shifted versions.")
        lines.append(f"     Confirmed at {wins_p1}/{len(higher_thrs)} higher thresholds vs +1, "
                     f"{wins_m1}/{len(higher_thrs)} vs -1.")
        lines.append("     This supports genuine over-representation of smooth numbers.")
    elif wins_p1 >= len(higher_thrs) * 0.75:
        lines.append(f"  >> Real > shifted+1 at {wins_p1}/{len(higher_thrs)} higher thresholds.")
        lines.append("     Effect vs +1 shift is consistent at larger counts.")
    else:
        lines.append("  >> No clear enrichment vs shifted counts.")
    lines.append("")

    h(f"6. per-file breakdown (files where any motif count is smooth >= {lo})")
    if files_with_smooth:
        for rel in sorted(files_with_smooth):
            vals = sorted(files_with_smooth[rel])
            lines.append(f"  {rel}")
            lines.append(f"    smooth counts: {vals}")
    else:
        lines.append("  (none found)")
    lines.append("")

    h("7. reference: all smooth numbers 2^a·3^b in [1, 256]")
    ref = smooth_numbers_in_range(1, 256)
    # format in rows of 12
    for i in range(0, len(ref), 12):
        lines.append("  " + "  ".join(f"{v:4d}" for v in ref[i:i+12]))
    lines.append("")

    rule('=')
    lines.append("END OF REPORT")
    rule('=')

    text = "\n".join(lines) + "\n"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(text)

    # Export frequency table for use by smooth_mc.py
    freq_path = os.path.join(os.path.dirname(__file__), "freq_table.json")
    with open(freq_path, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in freq.items()}, f, sort_keys=True)

    print(f"\nReport written to: {report_path}")
    print(f"Frequency table written to: {freq_path}")
    print(f"Smooth enrichment (log-uniform model): {ratio_log:.2f}x")


if __name__ == "__main__":
    main()

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
        q.put([{
            'count':        m.get('display_count', m['count']),
            'count_direct': m['n_direct_only'] + m['n_both'],
            'length':       m['length'],
        } for m in motifs])
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
    parser.add_argument('--composer', default=None,
                        help='Only analyse files whose composer matches (e.g. "Bach", '
                             '"Telemann"; uses _composer_from_rel)')
    parser.add_argument('--output', default=None,
                        help='Output report file path (default: meta_report.txt)')
    parser.add_argument('--lo', type=int, default=8,
                        help='Lower bound for smooth-count analysis (default: 8)')
    parser.add_argument('--rank', type=int, default=30,
                        help='Top-N per-file enrichment ranking appended to union report '
                             '(0 = skip, default: 30)')
    parser.add_argument('--cache', default=None,
                        help='Path to JSON cache file for saving/loading per-file results. '
                             'On a normal run: results are saved here after analysis. '
                             'With --append: existing cache is loaded and merged.')
    parser.add_argument('--append', action='store_true',
                        help='Load --cache, analyse only files NOT already in the cache '
                             '(or matched by --filter/--composer), merge, regenerate report.')
    args = parser.parse_args()

    _xml_files = kr.find_lilypond_files()

    all_files = kr.find_kern_files(kr.KERN_DIR) + kr.find_music21_files() + _xml_files
    if args.composer:
        target = args.composer.strip()
        files = [(r, f) for r, f in all_files
                 if kr._composer_from_rel(r) == target]
    elif args.filter:
        terms = [t.strip().lower() for t in args.filter.split(',')]
        files = [(r, f) for r, f in all_files
                 if any(t in r.lower() or t in os.path.basename(f).lower()
                        for t in terms)]
    else:
        files = [(r, f) for r, f in all_files if not r.startswith('music21/')]
    report_path_override = args.output
    lo = args.lo

    # ── load cache (for --append mode) ───────────────────────────────────────
    cached_results = {}
    if args.cache and os.path.isfile(args.cache):
        with open(args.cache, encoding='utf-8') as _f:
            cached_results = json.load(_f)
        print(f"Loaded cache: {len(cached_results)} files from {args.cache}")

    if args.append:
        # Only analyse files not already in cache
        files_to_run = [(r, f) for r, f in files if r not in cached_results]
        print(f"Append mode: {len(cached_results)} cached + "
              f"{len(files_to_run)} new → total {len(files)} files")
    else:
        files_to_run = files

    total = len(files)
    label = f' for composer {args.composer!r}' if args.composer else \
            f' matching {args.filter!r}' if args.filter else ''
    print(f"Found {total} files{label}. Analysing {len(files_to_run)}…")

    results = dict(cached_results)   # start from cache; new results will be merged in
    n_ok = 0
    n_err = 0

    ctx = multiprocessing.get_context('spawn')
    for idx, (rel, full) in enumerate(files_to_run):
        if (idx + 1) % 10 == 0 or idx == 0:
            print(f"  {idx+1}/{len(files_to_run)}  {rel}", flush=True)
        motifs = analyze_file(ctx, full)
        if motifs is None:
            n_err += 1
        else:
            n_ok += 1
            results[rel] = motifs

    print(f"Done. OK={n_ok}, errors/empty={n_err}")

    # ── save cache ────────────────────────────────────────────────────────────
    if args.cache:
        with open(args.cache, 'w', encoding='utf-8') as _f:
            json.dump(results, _f)
        print(f"Cache saved: {len(results)} files → {args.cache}")

    # Recount totals from merged results for the report header
    total    = len(files)          # all files in scope (filter/composer)
    n_ok     = len(results)        # successfully analysed (cached + new)
    n_err    = total - n_ok        # remainder treated as errors/empty

    # ── collect counts — both with-inversion and direct-only ──────────────────
    all_counts        = []   # with inversion (current default)
    all_counts_direct = []   # direct occurrences only
    file_counts        = {}
    file_counts_direct = {}
    for rel, motifs in results.items():
        counts        = [m['count']        for m in motifs]
        counts_direct = [m['count_direct'] for m in motifs]
        file_counts[rel]        = counts
        file_counts_direct[rel] = counts_direct
        all_counts.extend(counts)
        all_counts_direct.extend(counts_direct)

    if not all_counts:
        print("No counts collected. Exiting.")
        return

    def _local_baseline(k, freq_full, ks_nonzero, W=2.0):
        """Local log-linear regression baseline for count k.
        Uses all neighbours in multiplicative window [k/W, k*W] except k itself.
        Returns predicted freq(k) under the local trend, or None if < 3 neighbours."""
        lo_w, hi_w = k / W, k * W
        xs = [x for x in ks_nonzero if lo_w <= x <= hi_w and x != k]
        if len(xs) < 3:
            return None
        lx = [math.log(x) for x in xs]
        ly = [math.log(freq_full[x]) for x in xs]
        n  = len(xs)
        mlx = sum(lx) / n
        mly = sum(ly) / n
        cov = sum((lx[i] - mlx) * (ly[i] - mly) for i in range(n))
        var = sum((lx[i] - mlx) ** 2               for i in range(n))
        if var < 1e-9:
            return math.exp(mly)
        a = cov / var
        b = mly - a * mlx
        return math.exp(a * math.log(k) + b)

    def _write_report(counts_list, fcount_dict, report_path, title_suffix,
                      total, n_ok, n_err, n_results, lo):
        """Write one meta-analysis report for the given counts_list."""
        import random as _rnd
        counts_ge_lo = [c for c in counts_list if c >= lo]

        freq = defaultdict(int)
        for c in counts_list:
            freq[c] += 1

        max_c = max(counts_ge_lo) if counts_ge_lo else lo
        smooth_in_range = smooth_numbers_in_range(lo, max_c)

        files_with_smooth = {rel: [c for c in counts if c >= lo and _is_smooth(c)]
                             for rel, counts in fcount_dict.items()
                             if any(c >= lo and _is_smooth(c) for c in counts)}

        # ── local-baseline z-scores ───────────────────────────────────────────
        ks_all      = sorted(k for k in range(lo, max_c + 1) if freq.get(k, 0) > 0)
        freq_full   = {k: freq.get(k, 0) for k in range(lo, max_c + 1)}
        z_scores    = {}
        for k in ks_all:
            bl = _local_baseline(k, freq_full, ks_all)
            if bl is not None and bl > 0:
                z_scores[k] = (freq_full[k] - bl) / math.sqrt(bl)

        valid_ks     = sorted(z_scores)
        zs_smooth    = [z_scores[k] for k in valid_ks if _is_smooth(k)]
        zs_nonsmooth = [z_scores[k] for k in valid_ks if not _is_smooth(k)]
        mean_zs      = sum(zs_smooth)    / len(zs_smooth)    if zs_smooth    else 0.0
        mean_zns     = sum(zs_nonsmooth) / len(zs_nonsmooth) if zs_nonsmooth else 0.0

        # permutation test: is mean z(smooth) >= observed by chance?
        _rnd.seed(42)
        all_z  = zs_smooth + zs_nonsmooth
        n_s    = len(zs_smooth)
        N_PERM = 20000
        count_ge = sum(
            1 for _ in range(N_PERM)
            if (lambda samp: sum(samp) / len(samp))(_rnd.sample(all_z, n_s)) >= mean_zs
        )
        p_val = count_ge / N_PERM

        lines = []
        W_rule = 72

        def rule(ch='='):
            lines.append(ch * W_rule)

        def h(title):
            rule()
            lines.append(title.upper())
            rule()

        rule('=')
        lines.append(f"KERN FILE MOTIF META-ANALYSIS  [{title_suffix}]")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        rule('=')
        lines.append("")

        h("1. files processed")
        lines.append(f"Total files found      : {total}")
        lines.append(f"Successfully analysed  : {n_ok}")
        lines.append(f"Errors / empty         : {n_err}")
        lines.append(f"Files with motifs      : {n_results}")
        lines.append("")

        h("2. occurrence count overview")
        lines.append(f"Total motif-occurrences collected : {len(counts_list)}")
        lines.append(f"Min / Max count                   : {min(counts_list)} / {max(counts_list)}")
        mean_c = sum(counts_list) / len(counts_list)
        med_c  = sorted(counts_list)[len(counts_list) // 2]
        lines.append(f"Mean / Median                     : {mean_c:.1f} / {med_c}")
        lines.append(f"Counts >= {lo}                       : {len(counts_ge_lo)}")
        lines.append("")
        lines.append("Frequency table of ALL occurrence counts (count : frequency):")
        for val in sorted(freq):
            marker = "  <-- smooth (2^a·3^b)" if _is_smooth(val) and val >= lo else ""
            lines.append(f"  {val:4d} : {freq[val]}{marker}")
        lines.append("")

        h("3. local-baseline enrichment test")
        lines.append("Method: for each distinct count k, fit a log-linear regression")
        lines.append("  log(freq) ~ a·log(x) + b  on all neighbouring counts in the")
        lines.append("  multiplicative window [k/2, 2k] (excluding k itself, ≥3 points).")
        lines.append("  z(k) = (freq(k) − baseline(k)) / sqrt(baseline(k)).")
        lines.append("  Tests whether smooth numbers sit systematically above their local")
        lines.append("  trend, independent of the overall shape of the distribution.")
        lines.append("")
        lines.append(f"  Counts in analysis : k ∈ [{lo}, {max_c}],  {len(valid_ks)} distinct values with z-score")
        lines.append(f"  Smooth numbers     : {len(zs_smooth)}  pts  mean z = {mean_zs:+.3f}")
        lines.append(f"  Non-smooth numbers : {len(zs_nonsmooth)}  pts  mean z = {mean_zns:+.3f}")
        lines.append("")
        lines.append(f"  Permutation test ({N_PERM} permutations): p = {p_val:.4f}  "
                     f"{'*SIGNIFICANT (p<0.05)*' if p_val < 0.05 else '(not significant)'}")
        lines.append("")
        if p_val < 0.05:
            lines.append("  >> Smooth numbers sit significantly above local trend (p<0.05).")
            lines.append("     Genuine over-representation above the local decay curve.")
        elif p_val < 0.15:
            lines.append("  >> Marginal trend (p<0.15): smooth numbers slightly above local trend,")
            lines.append("     but not significant at conventional threshold.")
        else:
            lines.append("  >> No significant enrichment above local trend.")
            lines.append("     Earlier log-uniform enrichment was likely an artefact of the")
            lines.append("     null model underestimating density at small counts.")
        lines.append("")

        lines.append("  Z-scores at smooth numbers:")
        lines.append(f"  {'k':>5}  {'freq':>6}  {'baseline':>9}  {'z':>7}")
        lines.append(f"  {'─'*5}  {'─'*6}  {'─'*9}  {'─'*7}")
        for k in sorted(k for k in valid_ks if _is_smooth(k)):
            bl = _local_baseline(k, freq_full, ks_all)
            z  = z_scores[k]
            bar = ('+' if z >= 0 else '-') * min(15, int(abs(z)))
            lines.append(f"  {k:5d}  {freq_full[k]:6d}  {bl:9.1f}  {z:+7.2f}  {bar}")
        lines.append("")

        lines.append("  Z-scores at smooth+1 and smooth−1 (excluding smooth):")
        sp1 = {n + 1 for n in smooth_numbers_in_range(lo - 1, max_c - 1)} - set(smooth_numbers_in_range(lo, max_c))
        sm1 = {n - 1 for n in smooth_numbers_in_range(lo + 1, max_c + 1)} - set(smooth_numbers_in_range(lo, max_c))
        for label, S in [("smooth+1", sp1), ("smooth−1", sm1)]:
            zs = [z_scores[k] for k in S if k in z_scores]
            mz = sum(zs) / len(zs) if zs else float('nan')
            lines.append(f"  {label}: {len(zs)} pts  mean z = {mz:+.3f}")
        lines.append("")

        # ── top-K smooth fraction test ────────────────────────────────────────
        import random as _rnd2
        _rnd2 = _rnd2.Random(43)
        _K_vals = [1, 2, 3, 4, 6, 8]
        _topk_results = []
        for _K in _K_vals:
            _obs_sm = 0; _obs_tot = 0
            _piece_topk = []   # (counts_ge_lo, K_actual, n_smooth_in_topK) per piece
            for _rel, _counts in fcount_dict.items():
                _cge = sorted([_c for _c in _counts if _c >= lo], reverse=True)
                if not _cge:
                    continue
                _top = _cge[:_K]
                _k_a = len(_top)
                _s   = sum(1 for _c in _top if _is_smooth(_c))
                _obs_sm  += _s
                _obs_tot += _k_a
                _piece_topk.append((_cge, _k_a, _s))
            _obs_rate = _obs_sm / _obs_tot if _obs_tot else 0.0
            # null: per piece, shuffle counts≥lo, take top-K, count smooth
            N_PERM_K = 20000
            _cnt_ge_k = 0
            for _ in range(N_PERM_K):
                _sim = 0
                for (_cge, _k_a, _s) in _piece_topk:
                    _sh = list(_cge)
                    _rnd2.shuffle(_sh)
                    _sim += sum(1 for _c in _sh[:_k_a] if _is_smooth(_c))
                if _sim >= _obs_sm:
                    _cnt_ge_k += 1
            _p_k = _cnt_ge_k / N_PERM_K
            # baseline: smooth fraction among ALL counts ≥ lo
            _all_c = [_c for _cge, _, _ in _piece_topk for _c in _cge]
            _base_rate = sum(1 for _c in _all_c if _is_smooth(_c)) / len(_all_c) if _all_c else 0.0
            _topk_results.append((_K, _obs_sm, _obs_tot, _obs_rate, _base_rate, _p_k))

        h("4. top-K smooth fraction test")
        lines.append("Method: for each piece take the K largest motif counts; count how")
        lines.append("  many are smooth (2^a·3^b).  Compare to baseline smooth fraction")
        lines.append("  across all counts in the corpus.  Permutation null: within each")
        lines.append("  piece, shuffle all counts and take top-K  (preserves per-piece")
        lines.append("  count distribution; only randomises which counts land in top-K).")
        lines.append("")
        lines.append(f"  {'K':>3}  {'sm_in_top':>10}  {'top_total':>9}  "
                     f"{'rate_top':>9}  {'rate_all':>9}  {'lift':>6}  {'p':>7}")
        lines.append("  " + "-" * 62)
        for _K, _sm, _tot, _rt, _rb, _p in _topk_results:
            _lift = _rt / _rb if _rb > 0 else float('nan')
            _sig  = ' *' if _p < 0.05 else ('~' if _p < 0.15 else '')
            lines.append(f"  {_K:>3}  {_sm:>10}  {_tot:>9}  "
                         f"  {_rt:>7.3f}    {_rb:>7.3f}  {_lift:>6.2f}  {_p:>7.4f}{_sig}")
        lines.append("")
        lines.append("  lift = rate_top / rate_all  (>1 means smooth over-represented in top-K)")
        lines.append("  * p<0.05   ~ p<0.15   (permutation, one-sided)")
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
        for i in range(0, len(ref), 12):
            lines.append("  " + "  ".join(f"{v:4d}" for v in ref[i:i+12]))
        lines.append("")

        rule('=')
        lines.append("END OF REPORT")
        rule('=')

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        print(f"  [{title_suffix}] written to: {report_path}  "
              f"(local-baseline: mean_z_smooth={mean_zs:+.3f}, p={p_val:.4f})")
        return freq, p_val, z_scores, files_with_smooth

    # ── write two reports ─────────────────────────────────────────────────────
    base      = os.path.dirname(os.path.abspath(__file__))
    path_all  = report_path_override or os.path.join(base, "meta_report_bach_full.txt")
    path_dir  = os.path.join(os.path.dirname(path_all),
                             os.path.basename(path_all).replace('.txt', '_direct.txt'))

    print("\nWriting reports…")
    freq_all, _p_all, z_union, files_union = _write_report(
        all_counts, file_counts,
        path_all, "with inversions",
        total, n_ok, n_err, len(results), lo,
    )
    _freq_dir, _p_dir, z_direct, files_direct = _write_report(
        all_counts_direct, file_counts_direct,
        path_dir, "direct only",
        total, n_ok, n_err, len(results), lo,
    )

    # Export frequency table (with-inversions) for use by smooth_mc.py
    freq_path = os.path.join(base, "freq_table.json")
    with open(freq_path, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in freq_all.items()}, f, sort_keys=True)
    print(f"Frequency table written to: {freq_path}")

    # ── per-file enrichment ranking (union only) ─────────────────────────────
    if args.rank > 0:
        rows = []
        for rel, sc_u in files_union.items():
            sz_u  = sum(z_union.get(c, 0.0) for c in sc_u)
            max_c = max(sc_u)
            rows.append((sz_u, max_c, len(sc_u), rel))
        rows.sort(reverse=True)

        rank_lines = ["", "=" * 72,
                      f"6. PER-FILE ENRICHMENT RANKING  (ALL {len(rows)} FILES, BY Z-SCORE)",
                      "=" * 72,
                      "  z_sum = Σ z(c) over all smooth counts c≥8 (union/inversion report).",
                      "  z(c)  = local-baseline z-score for count c (same as §3).",
                      "  max_c = largest smooth count in the file.",
                      "  n_sm  = number of smooth motifs ≥8.",
                      "",
                      f"  {'Rk':>4}  {'z_sum':>8}  {'max_c':>6}  {'n_sm':>5}  file"]
        rank_lines.append("  " + "-" * 65)
        for i, (zu, mc, ns, rel) in enumerate(rows, 1):
            rank_lines.append(f"  {i:4d}  {zu:+8.2f}  {mc:6d}  {ns:5d}  {rel}")
        rank_lines += ["", "=" * 72, "END OF REPORT", "=" * 72]

        # Append ranking to the union report (replace its END OF REPORT footer)
        with open(path_all, "r", encoding="utf-8") as f:
            text = f.read()
        # Remove existing end-of-report footer (last 3 lines)
        lines_existing = text.rstrip("\n").split("\n")
        # Strip trailing separator + END OF REPORT + separator
        while lines_existing and lines_existing[-1].startswith("="):
            lines_existing.pop()
        while lines_existing and lines_existing[-1].strip() in ("END OF REPORT", ""):
            lines_existing.pop()
        while lines_existing and lines_existing[-1].startswith("="):
            lines_existing.pop()
        with open(path_all, "w", encoding="utf-8") as f:
            f.write("\n".join(lines_existing) + "\n" + "\n".join(rank_lines) + "\n")
        print(f"  Ranking (top {args.rank}) appended to: {path_all}")


if __name__ == "__main__":
    main()

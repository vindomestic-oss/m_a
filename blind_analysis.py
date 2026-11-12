#!/usr/bin/env python3
"""
Analysis of blind-test responses (responses/*.json written by blind_test.py).

Question: do raters give higher relevance (0-4) to motifs whose occurrence count is a "good"
(2^a*3^b >= 8) number than to matched motifs with a non-smooth count?

Tests (unit = rater / piece, NOT the individual rating; no distributional assumptions):
  1. per-rater AUC  P(rating_smooth > rating_nonsmooth) (+0.5 ties), within-piece comparisons only
       -> mean AUC, one-sample t / Wilcoxon vs 0.5 over raters, two-way cluster-bootstrap CI
  2. within-piece permutation test (smooth labels shuffled inside each rater x piece)
  3. count-adjusted effect: rater-standardised rating ~ smooth + log2(count) + length (OLS),
       cluster-bootstrap CI for the smooth coefficient
  4. matched pairs (same motif, smooth vs non-smooth counting variant): paired Wilcoxon
  5. anchor check, inter-rater reliability on shared pieces (Krippendorff alpha, ordinal)

Usage: python blind_analysis.py [--responses responses] [--out blind_report.txt] [--boot 2000]
"""
import argparse
import glob
import json
import math
import os
import numpy as np
import pandas as pd
from scipy import stats


# ── data ──────────────────────────────────────────────────────────────────────

def load_ratings(files):
    rows = []
    for fp in files:
        with open(fp, encoding='utf-8') as f:
            r = json.load(f)
        for p in r['pieces']:
            for it in p.get('items', []):
                if it.get('rating') is None or it.get('missing'):
                    continue
                rows.append({'rater': r['rater'], 'tag': r.get('tag', ''), 'scale': r.get('scale', 'ordinal'), 'seed': r['session_seed'], 'piece_idx': p['piece_idx'],
                             'piece': p['piece'], 'shared': p.get('shared', False), 'item': it['id'],
                             'kind': it['kind'], 'smooth': bool(it['smooth']), 'count': it['count'],
                             'length': it['length'], 'variant': it['variant'], 'pair_id': it['pair_id'],
                             'query': it['query'], 'rating': it['rating'],
                             'views': it.get('views', 0), 't_rate_ms': it.get('t_rate_ms')})
    df = pd.DataFrame(rows)
    if len(df):
        df['log2c'] = np.log2(df['count'])
        df['unit'] = df['rater'] + '|' + df['tag'] + '|' + df['seed'].astype(str) + '|' + df['piece_idx'].astype(str)
    return df


def main_items(df):
    return df[df['kind'].isin(('target', 'decoy'))]


# ── statistics ────────────────────────────────────────────────────────────────

def auc(pos, neg):
    """P(pos > neg) + 0.5 P(tie)."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    g = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return g / (len(pos) * len(neg))


def unit_auc(sub):
    """AUC pooled from within-piece comparisons only (weights = number of pairs per piece)."""
    num = den = 0.0
    for _, g in sub.groupby('unit'):
        p, n = g[g.smooth]['rating'].values, g[~g.smooth]['rating'].values
        if len(p) and len(n):
            num += auc(p, n) * len(p) * len(n)
            den += len(p) * len(n)
    return num / den if den else np.nan


def rater_aucs(df):
    return {r: unit_auc(g) for r, g in main_items(df).groupby('rater')}


def boot_ci(df, stat, B, rng):
    """Two-way cluster bootstrap: resample raters, then pieces (units) within rater."""
    m = main_items(df)
    raters = m['rater'].unique()
    by = {r: [g for _, g in m[m.rater == r].groupby('unit')] for r in raters}
    out = []
    for _ in range(B):
        parts = []
        for r in rng.choice(raters, len(raters)):
            units = by[r]
            idx = rng.integers(0, len(units), len(units))
            parts.extend(units[i] for i in idx)
        if parts:
            d = pd.concat(parts)
            d['unit'] = np.repeat(np.arange(len(parts)), [len(p) for p in parts])
            v = stat(d)
            if v == v:
                out.append(v)
    return (np.percentile(out, [2.5, 97.5]) if len(out) > 20 else (np.nan, np.nan))


def mean_auc_stat(d):
    a = [unit_auc(g) for _, g in d.groupby('rater')]
    a = [x for x in a if x == x]
    return float(np.mean(a)) if a else np.nan


def perm_test(df, P, rng):
    m = main_items(df).copy()
    obs = mean_auc_stat(m)
    units = [g for _, g in m.groupby('unit')]
    cnt = 0
    for _ in range(P):
        parts = []
        for g in units:
            g = g.copy()
            g['smooth'] = rng.permutation(g['smooth'].values)
            parts.append(g)
        if mean_auc_stat(pd.concat(parts)) >= obs - 1e-12:
            cnt += 1
    return obs, (cnt + 1) / (P + 1)


def zscore_by_rater(df):
    df = df.copy()
    g = df.groupby('rater')['rating']
    sd = g.transform('std').replace(0, np.nan)
    df['z'] = ((df['rating'] - g.transform('mean')) / sd).fillna(0.0)
    return df


def ols_smooth(d):
    d = zscore_by_rater(main_items(d))
    if len(d) < 8 or d['smooth'].nunique() < 2:
        return np.nan
    X = np.column_stack([np.ones(len(d)), d['smooth'].astype(float), d['log2c'] - d['log2c'].mean(),
                         d['length'] - d['length'].mean()])
    try:
        beta = np.linalg.lstsq(X, d['z'].values, rcond=None)[0]
    except Exception:
        return np.nan
    return float(beta[1])


def krippendorff_alpha_ordinal(mat):
    """mat: units x raters with NaN for missing. Ordinal metric."""
    vals = np.unique(mat[~np.isnan(mat)])
    if len(vals) < 2:
        return np.nan
    k = len(vals)
    idx = {v: i for i, v in enumerate(vals)}
    o = np.zeros((k, k))
    for row in mat:
        v = [idx[x] for x in row if not np.isnan(x)]
        m = len(v)
        if m < 2:
            continue
        for a in range(m):
            for b in range(m):
                if a != b:
                    o[v[a], v[b]] += 1.0 / (m - 1)
    n_c = o.sum(axis=1)
    n = n_c.sum()
    if n <= 1:
        return np.nan
    cum = np.cumsum(n_c)
    delta = np.zeros((k, k))
    for c in range(k):
        for d_ in range(k):
            if c != d_:
                lo, hi = min(c, d_), max(c, d_)
                delta[c, d_] = (n_c[lo:hi + 1].sum() - (n_c[lo] + n_c[hi]) / 2.0) ** 2
    Do = (o * delta).sum() / n
    De = (np.outer(n_c, n_c) * delta).sum() / (n * (n - 1))
    return 1.0 - Do / De if De > 0 else np.nan


# ── report ────────────────────────────────────────────────────────────────────

def analyze(df, B=2000, P=2000, seed=1):
    rng = np.random.default_rng(seed)
    L = []
    w = L.append
    m = main_items(df)
    anc = df[df.kind == 'anchor']
    w(f"Raters: {df.rater.nunique()}   rating records: {len(df)}   "
      f"(target/decoy {len(m)}, anchors {len(anc)})")
    w(f"Pieces rated (rater x piece units): {m.unit.nunique()}")
    w("")
    w("Mean rating (0-4):")
    for lab, g in (('smooth count (target)', m[m.smooth]), ('non-smooth count (decoy)', m[~m.smooth])):
        w(f"  {lab:28s} n={len(g):4d}  mean={g.rating.mean():.2f}  sd={g.rating.std():.2f}")
    if len(anc):
        w(f"  {'anchor (count<=3)':28s} n={len(anc):4d}  mean={anc.rating.mean():.2f}   "
          f"(manipulation check: expected clearly lowest)")
    w("")

    ra = rater_aucs(df)
    a = np.array([v for v in ra.values() if v == v])
    w("1) Per-rater AUC (0.5 = no preference for smooth counts)")
    if len(a) >= 2:
        t, pt = stats.ttest_1samp(a, 0.5)
        try:
            pw = stats.wilcoxon(a - 0.5).pvalue
        except ValueError:
            pw = float('nan')
        lo, hi = boot_ci(df, mean_auc_stat, B, rng)
        w(f"   mean AUC = {a.mean():.3f}   rater-level: t({len(a)-1}) = {t:.2f}, p = {pt:.4f};  "
          f"Wilcoxon p = {pw:.4f}")
        w(f"   95% cluster-bootstrap CI: [{lo:.3f}, {hi:.3f}]   per-rater range {a.min():.2f}-{a.max():.2f}")
    elif len(a) == 1:
        w(f"   one rater only: AUC = {a[0]:.3f} (no rater-level inference possible)")
    w("")

    obs, p = perm_test(df, P, rng)
    w("2) Within-piece permutation test (labels shuffled inside every rater x piece)")
    w(f"   observed mean AUC = {obs:.3f}   one-sided p = {p:.4f}")
    w("")

    beta = ols_smooth(df)
    lo, hi = boot_ci(df, ols_smooth, B, rng)
    w("3) Count-adjusted effect (rater-standardised rating ~ smooth + log2 count + length)")
    w(f"   beta(smooth) = {beta:+.3f} SD of rating   95% cluster-bootstrap CI [{lo:+.3f}, {hi:+.3f}]")
    w("")

    pr = m[m.pair_id.notna()]
    w("4) Matched pairs (same motif, smooth vs non-smooth counting variant)")
    diffs = []
    for (_, pid), g in pr.groupby(['unit', 'pair_id']):
        s, n = g[g.smooth], g[~g.smooth]
        if len(s) and len(n):
            diffs.append(s.rating.iloc[0] - n.rating.iloc[0])
    if len(diffs) >= 6:
        d = np.array(diffs, float)
        try:
            pw = stats.wilcoxon(d).pvalue
        except ValueError:
            pw = float('nan')
        w(f"   pairs = {len(d)}   mean(smooth - nonsmooth) = {d.mean():+.2f}   Wilcoxon p = {pw:.4f}   "
          f"ties = {(d == 0).mean():.0%}")
    else:
        w(f"   too few pairs ({len(diffs)})")
    w("")

    w("5) Reliability on shared pieces")
    sh = df[df.shared]
    if sh.rater.nunique() >= 2:
        piv = sh.pivot_table(index=['piece', 'query', 'variant'], columns='rater', values='rating')
        w(f"   Krippendorff alpha (ordinal) = {krippendorff_alpha_ordinal(piv.values):.3f} "
          f"on {len(piv)} items x {piv.shape[1]} raters")
        if piv.shape[1] >= 2:
            rs = [stats.spearmanr(piv.iloc[:, i], piv.iloc[:, j], nan_policy='omit')[0]
                  for i in range(piv.shape[1]) for j in range(i + 1, piv.shape[1])]
            w(f"   mean pairwise Spearman = {np.nanmean(rs):.3f}")
    else:
        w("   needs >= 2 raters on the shared pieces")
    return "\n".join(L)


# ── binary (tick-box) version ─────────────────────────────────────────────────

def mantel_haenszel(d):
    """Stratified 2x2 analysis; strata = rater x piece. Returns (OR_MH, CI_low, CI_high, chi2_CMH, p, n_strata)."""
    S1 = S2 = 0.0               # sum(ad/n), sum(bc/n)
    P_ = Q_ = R_ = S_ = 0.0     # Robins-Breslow-Greenland terms
    sa = sE = sV = 0.0
    k = 0
    for _, g in main_items(d).groupby('unit'):
        a = int(((g.smooth) & (g.rating == 1)).sum()); b = int(((g.smooth) & (g.rating == 0)).sum())
        c = int(((~g.smooth) & (g.rating == 1)).sum()); dd = int(((~g.smooth) & (g.rating == 0)).sum())
        n = a + b + c + dd
        if n < 2 or (a + b) == 0 or (c + dd) == 0:
            continue
        k += 1
        r_, s_ = a * dd / n, b * c / n
        S1 += r_; S2 += s_
        P_ += (a + dd) * r_ / n; Q_ += (a + dd) * s_ / n + (b + c) * r_ / n; S_ += (b + c) * s_ / n
        sa += a; sE += (a + b) * (a + c) / n
        sV += (a + b) * (c + dd) * (a + c) * (b + dd) / (n * n * (n - 1))
    if k == 0 or S1 == 0 or S2 == 0 or sV == 0:
        return np.nan, np.nan, np.nan, np.nan, np.nan, k
    OR = S1 / S2
    se = math.sqrt(P_ / (2 * S1 ** 2) + Q_ / (2 * S1 * S2) + S_ / (2 * S2 ** 2))
    chi2 = (abs(sa - sE) - 0.5) ** 2 / sV
    return OR, OR * math.exp(-1.96 * se), OR * math.exp(1.96 * se), chi2, float(stats.chi2.sf(chi2, 1)), k


def logit_smooth(d, ridge=1e-3):
    """log-odds ratio of 'smooth' from logistic regression: relevant ~ smooth + log2 count + length + rater."""
    m = main_items(d)
    if len(m) < 20 or m.smooth.nunique() < 2 or m.rating.nunique() < 2:
        return np.nan
    cols = [np.ones(len(m)), m.smooth.astype(float).values,
            (m.log2c - m.log2c.mean()).values, (m.length - m.length.mean()).values]
    for r in sorted(m.rater.unique())[1:]:
        cols.append((m.rater == r).astype(float).values)
    X = np.column_stack(cols)
    y = m.rating.values.astype(float)
    beta = np.zeros(X.shape[1])
    pen = np.eye(X.shape[1]) * ridge
    pen[0, 0] = 0.0
    for _ in range(50):
        eta = np.clip(X @ beta, -30, 30)
        mu = 1 / (1 + np.exp(-eta))
        W = mu * (1 - mu) + 1e-9
        H = X.T @ (X * W[:, None]) + pen
        step = np.linalg.solve(H, X.T @ (y - mu) - pen @ beta)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return float(beta[1])


def analyze_binary(df, B=2000, P=2000, seed=1):
    rng = np.random.default_rng(seed)
    L = []
    w = L.append
    m = main_items(df)
    w(f"Raters: {df.rater.nunique()}   judgements: {len(m)}   pieces (rater x piece units): {m.unit.nunique()}")
    w(f"Share of motifs ticked 'relevant': overall {m.rating.mean():.0%}")
    for lab, g in (('smooth count', m[m.smooth]), ('non-smooth count', m[~m.smooth])):
        w(f"  {lab:18s} n={len(g):4d}  ticked = {g.rating.mean():.0%}")
    w("")

    ra = rater_aucs(df)
    a = np.array([v for v in ra.values() if v == v])
    w("1) Per-rater within-piece AUC = P(smooth ticked & non-smooth not) + 0.5*ties  (0.5 = no preference)")
    if len(a) >= 2:
        t, pt = stats.ttest_1samp(a, 0.5)
        try:
            pw = stats.wilcoxon(a - 0.5).pvalue
        except ValueError:
            pw = float('nan')
        lo, hi = boot_ci(df, mean_auc_stat, B, rng)
        w(f"   mean AUC = {a.mean():.3f}   over raters: t({len(a)-1}) = {t:.2f}, p = {pt:.4f};  Wilcoxon p = {pw:.4f}")
        w(f"   95% cluster-bootstrap CI [{lo:.3f}, {hi:.3f}]   per-rater range {a.min():.2f}-{a.max():.2f}")
    elif len(a) == 1:
        w(f"   one rater only: AUC = {a[0]:.3f} (no rater-level inference possible)")
    w("")

    OR, lo, hi, chi2, p, k = mantel_haenszel(df)
    w("2) Mantel-Haenszel odds ratio, stratified by rater x piece (controls for piece and rater)")
    w(f"   OR = {OR:.2f}  (95% CI {lo:.2f}-{hi:.2f})   CMH chi2 = {chi2:.2f}, p = {p:.4f}   informative strata: {k}")
    w("   (OR > 1: a smooth-count motif is more likely to be ticked than a non-smooth one in the same piece)")
    w("")

    obs, pp = perm_test(df, P, rng)
    w("3) Within-piece permutation test of the AUC (labels shuffled inside every rater x piece)")
    w(f"   observed mean AUC = {obs:.3f}   one-sided p = {pp:.4f}")
    w("")

    b = logit_smooth(df)
    lo, hi = boot_ci(df, logit_smooth, B, rng)
    w("4) Count-adjusted logistic regression: ticked ~ smooth + log2(count) + length + rater")
    w(f"   OR(smooth) = {math.exp(b):.2f}   95% cluster-bootstrap CI [{math.exp(lo):.2f}, {math.exp(hi):.2f}]")
    w("")

    w("5) Reliability on shared pieces (binary Krippendorff alpha, 0 = chance agreement)")
    sh = df[df.shared]
    if sh.rater.nunique() >= 2:
        piv = sh.pivot_table(index=['piece', 'query', 'variant'], columns='rater', values='rating')
        w(f"   alpha = {krippendorff_alpha_ordinal(piv.values):.3f} on {len(piv)} items x {piv.shape[1]} raters")
        both = piv.dropna(thresh=2)
        pa = [(both.iloc[:, i] == both.iloc[:, j]).mean() for i in range(both.shape[1]) for j in range(i + 1, both.shape[1])]
        w(f"   mean pairwise raw agreement = {np.mean(pa):.0%}")
    else:
        w("   needs >= 2 raters on the shared pieces")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--responses', default='responses')
    ap.add_argument('--out', default='blind_report.txt')
    ap.add_argument('--boot', type=int, default=2000)
    ap.add_argument('--perm', type=int, default=2000)
    ap.add_argument('--unsuitable', default='blind_unsuitable.json', help='JSON {piece: reason}; these pieces are dropped from the analysis')
    ap.add_argument('--keep-unsuitable', action='store_true', help='do not drop unsuitable pieces')
    ap.add_argument('--export', default=None, help='also write all ratings of all raters to this CSV file')
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.responses, '*.json')))
    df = load_ratings(files)
    if not len(df):
        raise SystemExit('no ratings found')
    bad = {}
    if os.path.isfile(a.unsuitable):
        with open(a.unsuitable, encoding='utf-8') as f:
            bad = json.load(f)
    df['unsuitable'] = df['piece'].isin(bad)
    n_bad = int(df['unsuitable'].sum())
    if n_bad and not a.keep_unsuitable:
        print(f"Dropped {n_bad} judgements from {df.loc[df.unsuitable, 'piece'].nunique()} unsuitable piece(s): "
              + ", ".join(sorted(df.loc[df.unsuitable, 'piece'].unique())))
    if a.export:
        df.drop(columns=['unit']).to_csv(a.export, index=False, encoding='utf-8')
        print(f'exported {len(df)} ratings of {df.rater.nunique()} raters to {a.export}')
    if not a.keep_unsuitable:
        df = df[~df['unsuitable']]
    reps = []
    for tag, d in df.groupby('tag'):          # experiments are never pooled
        fn = analyze_binary if (d['scale'] == 'binary').all() else analyze
        reps.append(f"=== experiment '{tag or 'default (count>=8)'}' "
                    f"({'tick-box' if fn is analyze_binary else '0-4 scale'}) ===\n" + fn(d, a.boot, a.perm))
    rep = "\n\n".join(reps)
    print(rep)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(rep + '\n')


if __name__ == '__main__':
    main()

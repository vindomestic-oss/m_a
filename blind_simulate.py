#!/usr/bin/env python3
"""
Simulate blind-test responses to validate blind_analysis.py and to estimate power.

Latent relevance = rater bias + effect*smooth + count_slope*(log2 count - 4) + item quality (shared by
raters) + noise; cut into 0..4. Anchors get a strongly negative latent value.

  python blind_simulate.py --sessions sessions --raters 8 --effect 0.5 --out sim_resp      # write files
  python blind_simulate.py --sessions sessions --power --raters 6 --effect 0.4 --reps 100   # power
"""
import argparse
import glob
import json
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blind_analysis as ba

CUTS = np.array([-1.0, -0.2, 0.6, 1.4])
BIN_THR = 0.9          # binary scale: ticked if latent relevance > BIN_THR (~25-30% ticked)


def sim_rater(sess, name, rng, effect, count_slope, item_q, bias_sd=0.6, noise_sd=1.0):
    bias = rng.normal(0, bias_sd)
    pieces = []
    for pi, p in enumerate(sess['pieces']):
        items = []
        for k, it in enumerate(p['items']):
            key = (p['piece'], it['query'], it['variant'])
            q = item_q.setdefault(key, rng.normal(0, 0.8))
            lat = (bias + effect * it['smooth'] + count_slope * (np.log2(it['count']) - 4) + q
                   + rng.normal(0, noise_sd))
            if it['kind'] == 'anchor':
                lat -= 2.5
            rating = int(lat > BIN_THR) if sess.get('scale') == 'binary' else int(np.searchsorted(CUTS, lat))
            items.append({'id': f'p{pi}_i{k}', 'kind': it['kind'], 'smooth': it['smooth'],
                          'count': it['count'], 'variant': it['variant'], 'pair_id': it['pair_id'],
                          'query': it['query'], 'length': it['length'], 'rating': rating, 'missing': False,
                          'shown_count': it['count'], 'views': 1, 't_rate_ms': 1000})
        pieces.append({'piece_idx': pi, 'piece': p['piece'], 'shared': p['shared'],
                       'elapsed_ms': 1000, 'items': items})
    return {'session_seed': sess['seed'], 'tag': sess.get('tag', ''), 'scale': sess.get('scale', 'ordinal'),
            'rater': name, 'pieces': pieces}


def load_sessions(d):
    out = []
    for fp in sorted(glob.glob(os.path.join(d, 'session_*.json'))):
        with open(fp, encoding='utf-8') as f:
            s = json.load(f)
        for pi, p in enumerate(s['pieces']):
            for k, it in enumerate(p['items']):
                it['id'] = f'p{pi}_i{k}'
        out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sessions', default='sessions')
    ap.add_argument('--raters', type=int, default=8)
    ap.add_argument('--effect', type=float, default=0.5)
    ap.add_argument('--count-slope', type=float, default=0.3)
    ap.add_argument('--out', default='sim_resp')
    ap.add_argument('--power', action='store_true')
    ap.add_argument('--reps', type=int, default=100)
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    sessions = load_sessions(a.sessions)
    if len(sessions) < a.raters:
        raise SystemExit(f'need >= {a.raters} session files in {a.sessions}')
    rng = np.random.default_rng(a.seed)

    if not a.power:
        os.makedirs(a.out, exist_ok=True)
        item_q = {}
        for i in range(a.raters):
            r = sim_rater(sessions[i], f'sim{i+1}', rng, a.effect, a.count_slope, item_q)
            with open(os.path.join(a.out, f'sim{i+1}_{r["session_seed"]}.json'), 'w', encoding='utf-8') as f:
                json.dump(r, f)
        print(f'wrote {a.raters} simulated raters to {a.out}')
        return

    from scipy import stats
    hits_t = hits_w = hits_mh = 0
    for _ in range(a.reps):
        item_q = {}
        resp = [sim_rater(sessions[i], f'sim{i+1}', rng, a.effect, a.count_slope, item_q) for i in range(a.raters)]
        tmp = os.path.join(os.environ.get('TEMP', '.'), '_sim_pw')
        os.makedirs(tmp, exist_ok=True)
        for fp in glob.glob(os.path.join(tmp, '*.json')):
            os.remove(fp)
        for r in resp:
            with open(os.path.join(tmp, f'{r["rater"]}.json'), 'w', encoding='utf-8') as f:
                json.dump(r, f)
        df = ba.load_ratings(sorted(glob.glob(os.path.join(tmp, '*.json'))))
        aucs = np.array(list(ba.rater_aucs(df).values()))
        hits_t += stats.ttest_1samp(aucs, 0.5).pvalue < 0.05 and aucs.mean() > 0.5
        _o, _lo, _hi, _c, _p, _k = ba.mantel_haenszel(df) if sessions[0].get('scale') == 'binary' else (0,)*6
        hits_mh += (_p == _p) and _p < 0.05 and _o > 1
        try:
            hits_w += stats.wilcoxon(aucs - 0.5).pvalue < 0.05 and aucs.mean() > 0.5
        except ValueError:
            pass
    print(f'raters={a.raters} effect={a.effect} count_slope={a.count_slope}: '
          f'power(t over rater AUCs)={hits_t / a.reps:.2f}  power(Wilcoxon)={hits_w / a.reps:.2f}  '
          f'power(MH odds ratio)={hits_mh / a.reps:.2f}  [{a.reps} reps]')


if __name__ == '__main__':
    main()

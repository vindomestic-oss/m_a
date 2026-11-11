#!/usr/bin/env python3
"""
Build blind-test session design(s) from blind_cache.json (see blind_collect.py).

Per session:
  * N pieces (default 12), no volta brackets, 1..4 voices, spread over collections (<=2 per directory)
  * 5..7 motif items per piece; every item has count >= 8
  * number of "target" items (smooth count 2^a*3^b) per piece ~ uniform on 0..n  (feasible range)
  * decoys (non-smooth count) are matched to the targets on count (log scale) and length
  * a piece may contain one "pair": the SAME motif in two counting variants, one smooth one not
  * one anchor item per session: motif with union count <= 3 (expected relevance ~ 0)
  * first --shared pieces are identical for all sessions (inter-rater agreement)
Variants (names match the filters in the reader):
  all (normal [+ inverted]), direct, inv, ball, bdirect, binv  (b* = incl. bounded occurrences)

Usage: python blind_design.py --seed 1 [--sessions 1] [--pieces 12] [--shared 4] [--out sessions]
"""
import argparse
import json
import math
import os
import random

TAG = ''            # set from --tag; stored in every session (separates experiments)
MIN_COUNT = 8       # set from --min-count
VARIANT_KEY = {'all': 'union', 'direct': 'direct', 'inv': 'inv',
               'ball': 'b_union', 'bdirect': 'b_direct', 'binv': 'b_inv'}


def is_smooth(k):
    if k <= 0:
        return False
    while k % 2 == 0:
        k //= 2
    while k % 3 == 0:
        k //= 3
    return k == 1


def variant_label(v, m):
    has_inv = m['inv'] > 0
    base = {'all': 'normal + inverted' if has_inv else 'normal',
            'direct': 'normal only', 'inv': 'inverted only',
            'ball': 'normal + inverted' if has_inv else 'normal',
            'bdirect': 'normal only', 'binv': 'inverted only'}[v]
    return base + (', incl. bounded' if v.startswith('b') else '')


def motif_variants(m):
    """Distinct counting variants of one motif -> {variant: count} (duplicates removed)."""
    out = {'all': m['union']}
    if m['inv'] > 0 and m['direct'] != m['union']:
        out['direct'] = m['direct']
    if m['inv'] > 0 and m['inv'] != m['union']:
        out['inv'] = m['inv']
    if m['b_union'] != m['union']:
        out['ball'] = m['b_union']
        if m['inv'] > 0 and m['b_direct'] != m['direct']:
            out['bdirect'] = m['b_direct']
        if m['inv'] > 0 and m['b_inv'] != m['inv']:
            out['binv'] = m['b_inv']
    return out


def make_item(rel, m, v, kind, pair=None):
    c = m[VARIANT_KEY[v]]
    return {'piece': rel, 'query': m['query'], 'length': m['length'], 'variant': v,
            'variant_label': variant_label(v, m), 'count': c, 'smooth': is_smooth(c),
            'kind': kind, 'pair_id': pair}


def eligible_pieces(cache, min_count=8):
    out = {}
    for rel, v in cache.items():
        if 'error' in v or v['has_ending'] or not (1 <= v['n_voices'] <= 4):
            continue
        items = []          # (motif, variant, count) with count >= 8
        for m in v['motifs']:
            for var, c in motif_variants(m).items():
                if c >= min_count:
                    items.append((m, var, c))
        if sum(is_smooth(c) for _, _, c in items) >= 1 and len({i[0]['query'] for i in items}) >= 5:
            out[rel] = {'items': items, 'motifs': v['motifs']}
    return out


def _dist(a, b):
    return abs(math.log(a[0]) - math.log(b[0])) + 0.15 * abs(a[1] - b[1])


def build_piece(rel, info, rng, n=None):
    items = info['items']
    n = n or rng.randint(5, 7)
    sm = [i for i in items if is_smooth(i[2])]
    ns = [i for i in items if not is_smooth(i[2])]
    chosen, used = [], set()

    def take(pool_item, kind, pair=None):
        m, v, c = pool_item
        used.add(m['query'])
        chosen.append(make_item(rel, m, v, kind, pair))

    def uniq(pool):
        seen, out = set(), []
        for it in rng.sample(pool, len(pool)):
            if it[0]['query'] not in seen:
                seen.add(it[0]['query']); out.append(it)
        return out

    # 1) number of targets: uniform over the feasible range (0 and n allowed)
    n_sm = len({i[0]['query'] for i in sm})
    n_ns = len({i[0]['query'] for i in ns})
    lo, hi = max(0, n - n_ns), min(n, n_sm)
    if lo > hi:
        return None
    k = rng.randint(lo, hi)
    # 2) optional pair (same motif, smooth + non-smooth variant, counts within x1.6)
    #    only if it still leaves room: needs k>=1 and n-k>=1
    by_q = {}
    for it in items:
        by_q.setdefault(it[0]['query'], []).append(it)
    pairs = [(a, b) for lst in by_q.values() for a in lst for b in lst
             if is_smooth(a[2]) and not is_smooth(b[2]) and max(a[2], b[2]) <= 1.6 * min(a[2], b[2])]
    k_left, n_pair = k, 0
    if 1 <= k <= n - 1 and pairs and rng.random() < 0.5:
        a, b = rng.choice(pairs)
        pid = f"{rel}|{a[0]['query']}"
        take(a, 'target', pid)
        take(b, 'decoy', pid)
        k_left -= 1
        n_pair = 1
    free_dec = (n - k) - n_pair
    sm = uniq([i for i in sm if i[0]['query'] not in used])
    ns = uniq([i for i in ns if i[0]['query'] not in used])
    if k_left > len(sm) or free_dec > len(ns):
        return None
    targets = rng.sample(sm, k_left)
    tq = {t[0]['query'] for t in targets}
    ns = [i for i in ns if i[0]['query'] not in tq]
    allt = [(c['count'], c['length']) for c in chosen if c['kind'] == 'target'] +            [(t[2], t[0]['length']) for t in targets]
    refs = allt or [(s_[2], s_[0]['length']) for s_ in rng.sample(sm, min(3, len(sm)))] or [(12, 3)]
    for t in targets:
        take(t, 'target')
    for _ in range(free_dec):
        rng.shuffle(refs)
        pick = None
        for ref in refs:           # decoy must match some reference target: count x1.6, length +-2
            cand = [it for it in ns if max(it[2], ref[0]) <= 1.6 * min(it[2], ref[0])
                    and abs(it[0]['length'] - ref[1]) <= 2]
            if cand:
                cand.sort(key=lambda it: _dist((it[2], it[0]['length']), ref))
                pick = rng.choice(cand[:2])
                break
        if pick is None:
            return None
        ns.remove(pick)
        take(pick, 'decoy')
    rng.shuffle(chosen)
    return chosen


def anchor_for(rel, info, rng):
    cands = [m for m in info['motifs'] if 2 <= m['union'] <= 3 and m['b_union'] <= 3]
    if not cands:
        return None
    return make_item(rel, rng.choice(cands), 'all', 'anchor')


def pick_pieces(elig, n, rng, exclude=()):
    rels = [r for r in elig if r not in exclude]
    rng.shuffle(rels)
    per_dir, out = {}, []
    for r in rels:
        d = os.path.dirname(r)
        if per_dir.get(d, 0) >= 2:
            continue
        per_dir[d] = per_dir.get(d, 0) + 1
        out.append(r)
        if len(out) == n:
            break
    return out


def build_session(elig, seed, n_pieces, n_shared, shared_pieces):
    rng = random.Random(seed)
    pieces = []
    for rel, items in shared_pieces[:n_shared]:
        pieces.append({'piece': rel, 'shared': True, 'items': items})
    need = n_pieces - len(pieces)
    taken = {p['piece'] for p in pieces}
    for rel in pick_pieces(elig, need * 8, rng, exclude=taken):
        if len(pieces) >= n_pieces:
            break
        items = build_piece(rel, elig[rel], rng)
        if items:
            pieces.append({'piece': rel, 'shared': False, 'items': items})
    # anchor into a random non-shared piece
    for p in rng.sample(pieces, len(pieces)):
        if p['shared']:
            continue
        a = anchor_for(p['piece'], elig[p['piece']], rng)
        if a:
            p['items'].append(a)
            rng.shuffle(p['items'])
            break
    head = [p for p in pieces if p['shared']]
    tail = [p for p in pieces if not p['shared']]
    rng.shuffle(tail)
    order = head + tail
    rng.shuffle(order)
    return {'seed': seed, 'tag': TAG, 'min_count': MIN_COUNT, 'pieces': order}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', default='blind_cache.json')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--sessions', type=int, default=1)
    ap.add_argument('--pieces', type=int, default=12)
    ap.add_argument('--shared', type=int, default=4)
    ap.add_argument('--out', default='sessions')
    ap.add_argument('--min-count', type=int, default=8, help='only motifs/variants with count >= this')
    ap.add_argument('--tag', default='', help='experiment tag, e.g. min16 (separates response files/analysis)')
    a = ap.parse_args()
    global TAG, MIN_COUNT
    TAG, MIN_COUNT = a.tag, a.min_count
    with open(a.cache, encoding='utf-8') as f:
        elig = eligible_pieces(json.load(f), a.min_count)
    print(f"{len(elig)} eligible pieces")
    srng = random.Random(10_000)           # fixed -> shared pieces identical for everybody
    shared = []
    for rel in pick_pieces(elig, a.shared * 8, srng):
        it = build_piece(rel, elig[rel], srng)
        if it:
            shared.append((rel, it))
        if len(shared) == a.shared:
            break
    os.makedirs(a.out, exist_ok=True)
    for s in range(a.sessions):
        seed = a.seed + s
        sess = build_session(elig, seed, a.pieces, a.shared, shared)
        path = os.path.join(a.out, f'session_{seed}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(sess, f, ensure_ascii=False, indent=1)
        its = [i for p in sess['pieces'] for i in p['items']]
        print(f"{path}: {len(sess['pieces'])} pieces, {len(its)} items, "
              f"{sum(i['smooth'] for i in its)} smooth")


if __name__ == '__main__':
    main()

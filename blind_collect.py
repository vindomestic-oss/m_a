#!/usr/bin/env python3
"""
Collect per-motif variant counts for the blind relevance test.

For every file (fresh subprocess, 90 s timeout) runs analyze_motifs and stores, per motif:
  query       - search query string (identifies the motif when the test re-analyses the piece)
  length      - number of notes
  direct / inv / union          - regular counts (direct = direct_only+both, inv = inv_only+both)
  b_direct / b_inv / b_union    - "bounded" counts (equal to the regular ones if no bounded extras)
  mdl, is_repeat
and per piece: n_voices (distinct staff/layer with notes), has_ending (volta brackets in MEI).

Usage:
  python blind_collect.py --cache blind_cache.json --composer Bach
  python blind_collect.py --cache blind_cache.json --filter wtc,inventions
Resumable: files already in the cache are skipped.
"""
import json
import multiprocessing
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import meta_analysis as ma      # reuses file preparation idea, _TIMEOUT, helpers
import kern_reader as kr


def _worker(path, q):
    try:
        import sys as _s, os as _o
        _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
        import kern_reader as _kr
        import xml.etree.ElementTree as ET
        _kr.check_file(path)
        ext = path.rsplit('.', 1)[-1].lower()
        if ext == 'mxl':
            import zipfile
            with zipfile.ZipFile(path) as z:
                nm = next(n for n in z.namelist()
                          if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n)
                raw = z.read(nm)
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
            content = _kr.add_beam_markers(_kr.prepare_grand_staff(content))
        _kr._vtk.setOptions({'pageWidth': 2200, 'adjustPageHeight': True,
                             'scale': 35, 'font': 'Leipzig'})
        if not _kr._vtk.loadData(content):
            q.put(None)
            return
        mei = _kr._vtk.getMEI()
        # voices = distinct (staff, layer) that contain notes
        vs = set()
        root = ET.fromstring(mei)
        for staff in root.iter('{http://www.music-encoding.org/ns/mei}staff'):
            for layer in staff.iter('{http://www.music-encoding.org/ns/mei}layer'):
                if next(layer.iter('{http://www.music-encoding.org/ns/mei}note'), None) is not None:
                    vs.add((staff.get('n'), layer.get('n')))
        motifs = _kr.analyze_motifs(_kr._vtk, mei_str=mei)
        out = []
        for m in motifs:
            nd, ni, nb = m['n_direct_only'], m['n_inv_only'], m['n_both']
            bd, bi, bb = (m.get('b_n_direct_only', nd), m.get('b_n_inv_only', ni),
                          m.get('b_n_both', nb))
            out.append({
                'query': m['queryStr'], 'length': m['length'],
                'direct': nd + nb, 'inv': ni + nb, 'union': nd + ni + nb,
                'b_direct': bd + bb, 'b_inv': bi + bb, 'b_union': bd + bi + bb,
                'display_count': m.get('display_count'), 'mdl': m.get('mdl'),
                'is_repeat': bool(m.get('is_volta')),
            })
        q.put({'n_voices': len(vs), 'has_ending': '<ending' in mei, 'motifs': out})
    except Exception:
        q.put(None)


def _run(ctx, path):
    q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(path, q))
    p.start()
    try:
        r = q.get(timeout=ma._TIMEOUT)
    except Exception:
        r = None
    p.join(timeout=5)
    if p.is_alive():
        p.terminate()
        p.join()
    return r


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', default='blind_cache.json')
    ap.add_argument('--composer', default=None)
    ap.add_argument('--filter', default=None)
    ap.add_argument('--exclude', default=None, help='comma-separated substrings of rel path to drop')
    ap.add_argument('--limit', type=int, default=0, help='analyse at most N new files (testing)')
    a = ap.parse_args()

    allf = (kr.find_kern_files(kr.KERN_DIR) + kr.find_music21_files()
            + kr.find_lilypond_files() + kr.find_tobis_files())
    if a.composer:
        files = [(r, f) for r, f in allf if kr._composer_from_rel(r) == a.composer]
    elif a.filter:
        ts = [t.strip().lower() for t in a.filter.split(',')]
        files = [(r, f) for r, f in allf
                 if any(t in r.lower() or t in os.path.basename(f).lower() for t in ts)]
    else:
        files = [(r, f) for r, f in allf if not r.startswith('music21/')]

    if a.exclude:
        xs = [t.strip().lower() for t in a.exclude.split(',')]
        files = [(r, f) for r, f in files if not any(t in r.lower() for t in xs)]

    cache = {}
    if os.path.isfile(a.cache):
        with open(a.cache, encoding='utf-8') as f:
            cache = json.load(f)
    todo = [(r, f) for r, f in files if r not in cache]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(files)} files in scope, {len(cache)} cached, {len(todo)} to analyse", flush=True)

    ctx = multiprocessing.get_context('spawn')
    for i, (rel, full) in enumerate(todo):
        res = _run(ctx, full)
        cache[rel] = res if res is not None else {'error': True}
        if (i + 1) % 10 == 0 or i == 0:
            print(f"  {i+1}/{len(todo)} {rel}", flush=True)
            with open(a.cache, 'w', encoding='utf-8') as f:
                json.dump(cache, f)
    with open(a.cache, 'w', encoding='utf-8') as f:
        json.dump(cache, f)
    ok = sum(1 for v in cache.values() if 'error' not in v)
    print(f"Done. {ok} OK, {len(cache) - ok} errors. Cache: {a.cache}")


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()

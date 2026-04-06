#!/usr/bin/env python3
"""
Count 1/8-splits vs 1/8-nonsplits per voice.

Definition:
  For every 1/4-beat position (onset = 0, 1, 2, ... quarter notes):
    1/8-split    : attack at that position AND attack at position + 0.5
    1/8-nonsplit : anything else (no attack on 1/4, or only one of the two)

Usage:
    python diag_splits.py <file.krn|file.xml>
    python diag_splits.py --filter french   # all matching lilypond/kern files
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kern_reader as kr


def _load_mei(path):
    ext = path.rsplit('.', 1)[-1].lower()
    if ext == 'krn':
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        content = kr.prepare_grand_staff(content)
        content = kr.add_beam_markers(content)
    elif ext in ('xml', 'musicxml'):
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    else:
        return None
    kr._vtk.setOptions({
        'pageWidth': 2200, 'adjustPageHeight': True,
        'scale': 35, 'font': 'Leipzig',
    })
    if not kr._vtk.loadData(content):
        return None
    return kr._vtk.getMEI()


def splits_per_voice(path):
    """
    Returns dict: voice_key -> {'splits': int, 'nonsplits': int, 'total': int, 'ratio': float}
    voice_key = (staff_n, layer_n)
    """
    mei = _load_mei(path)
    if mei is None:
        return None

    voices, beat_dur_q, _ = kr._voice_notes_from_mei(mei)

    result = {}
    for vk, notes in voices.items():
        if not notes:
            continue
        # attack set on 1/32 grid (resolution 1/16 quarter = 1/64 whole)
        attacks = set(round(n[5] * 16) for n in notes)
        max_q = max(n[5] for n in notes)

        splits = 0
        nonsplits = 0
        q = 0.0
        while q <= max_q + 0.001:
            g_q  = round(q * 16)
            g_q8 = round((q + 0.5) * 16)
            if g_q in attacks and g_q8 in attacks:
                splits += 1
            else:
                nonsplits += 1
            q += 1.0

        total = splits + nonsplits
        result[vk] = {
            'splits':    splits,
            'nonsplits': nonsplits,
            'total':     total,
            'ratio':     splits / total if total else 0.0,
        }
    return result


def _print_file(rel, path):
    res = splits_per_voice(path)
    if res is None:
        print(f"  ERROR loading {rel}")
        return
    print(f"\n{rel}")
    print(f"  {'voice':12s}  {'split':>6s}  {'nonsplit':>8s}  {'total':>6s}  {'ratio':>6s}")
    print(f"  {'-'*12}  {'-'*6}  {'-'*8}  {'-'*6}  {'-'*6}")
    for vk in sorted(res):
        d = res[vk]
        label = f"st{vk[0]} lay{vk[1]}"
        print(f"  {label:12s}  {d['splits']:6d}  {d['nonsplits']:8d}  {d['total']:6d}  {d['ratio']:6.3f}")
    # aggregate across voices
    tot_s = sum(d['splits']    for d in res.values())
    tot_n = sum(d['nonsplits'] for d in res.values())
    tot   = tot_s + tot_n
    print(f"  {'ALL':12s}  {tot_s:6d}  {tot_n:8d}  {tot:6d}  {tot_s/tot if tot else 0:6.3f}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == '--filter':
        terms = [t.strip().lower() for t in args[1].split(',')] if len(args) > 1 else []
        all_files = kr.find_lilypond_files() + kr.find_kern_files(kr.KERN_DIR)
        files = [(r, f) for r, f in all_files
                 if not terms or any(t in r.lower() or t in os.path.basename(f).lower()
                                     for t in terms)]
        print(f"Found {len(files)} files")
        for rel, full in files:
            _print_file(rel, full)
    else:
        path = args[0]
        rel  = os.path.basename(path)
        _print_file(rel, path)


if __name__ == '__main__':
    main()

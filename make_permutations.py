#!/usr/bin/env python3
"""
Generate N permuted kern files from a source kern file.
Pitches are shuffled within each spine column while all durations,
barlines, interpretations, beam markers and other structure are preserved.

Usage: python make_permutations.py
Output: kern/permut/inven01-perm{1..5}.krn
"""

import os
import re
import random

HERE   = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, 'kern', 'osu', 'classical', 'bach', 'inventions', 'inven01.krn')
N_PERM = 5
OUT_DIR = os.path.join(HERE, 'kern', 'permut')

_PITCH = re.compile(r'[A-Ga-g]+')


def _is_data(line):
    s = line.strip()
    return bool(s) and s[0] not in ('*', '!', '=')


def _get_pitch(tok):
    m = _PITCH.search(tok)
    return m.group() if m else None


def _set_pitch(tok, p):
    return _PITCH.sub(p, tok, count=1)


def permute(lines, seed):
    random.seed(seed)

    # Number of columns from the **kern header line
    n_cols = max(len(l.split('\t')) for l in lines if l.startswith('**'))

    # Collect pitches per column (spine)
    col_pitches = [[] for _ in range(n_cols)]
    for line in lines:
        if not _is_data(line):
            continue
        toks = line.rstrip('\r\n').split('\t')
        for ci, tok in enumerate(toks[:n_cols]):
            p = _get_pitch(tok)
            if p:
                col_pitches[ci].append(p)

    # Shuffle pitches within each spine
    for ps in col_pitches:
        random.shuffle(ps)

    # Re-insert shuffled pitches
    col_pos = [0] * n_cols
    out = []
    for line in lines:
        if not _is_data(line):
            out.append(line)
            continue
        ending = '\r\n' if line.endswith('\r\n') else '\n'
        toks = line.rstrip('\r\n').split('\t')
        new_toks = []
        for ci, tok in enumerate(toks):
            if ci < n_cols:
                p = _get_pitch(tok)
                if p is not None and col_pos[ci] < len(col_pitches[ci]):
                    new_toks.append(_set_pitch(tok, col_pitches[ci][col_pos[ci]]))
                    col_pos[ci] += 1
                else:
                    new_toks.append(tok)
            else:
                new_toks.append(tok)
        out.append('\t'.join(new_toks) + ending)
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(SOURCE, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    base = os.path.splitext(os.path.basename(SOURCE))[0]
    for i in range(1, N_PERM + 1):
        out_lines = permute(lines, seed=i * 42)
        fname = f'{base}-perm{i}.krn'
        out_path = os.path.join(OUT_DIR, fname)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.writelines(out_lines)
        print(f'Written: {fname}')

    print(f'\n{N_PERM} permuted files saved to {OUT_DIR}')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Convert musedata/bach Bitbucket archive (stage2 files) to MusicXML.

Source: C:/m_a/musedata_bach_extracted/musedata-bach-*/bg/
Output: C:/m_a/lilypond/musicxml/

Usage:
    python convert_musedata.py [--filter cant] [--dry-run]
"""

import argparse, shutil, sys, tempfile
from pathlib import Path

import music21

BG_ROOT  = Path('C:/m_a/musedata_bach_extracted/musedata-bach-7607ecf4593d/bg')
OUT_DIR  = Path('C:/m_a/lilypond/musicxml')
OUT_DIR.mkdir(parents=True, exist_ok=True)


def find_bwv_works(filter_term=''):
    """Return list of (section, bwv_dir) for all works with stage2 content."""
    works = []
    for section_dir in sorted(BG_ROOT.iterdir()):
        if not section_dir.is_dir():
            continue
        section = section_dir.name
        for bwv_dir in sorted(section_dir.iterdir()):
            if not bwv_dir.is_dir():
                continue
            stage2 = bwv_dir / 'stage2'
            if not stage2.exists():
                continue
            bwv = bwv_dir.name
            if filter_term and filter_term not in section and filter_term not in bwv:
                continue
            works.append((section, bwv_dir))
    return works


def bwv_label(bwv: str) -> str:
    """'1066' → 'BWV_1066', '0001' → 'BWV_1', '0030a' → 'BWV_30a'."""
    import re
    m = re.match(r'^0*(\d+\w*)$', bwv)
    return 'BWV_' + (m.group(1) if m else bwv)


def convert_movement(mvt_dir: Path, out_path: Path) -> bool:
    """Convert one movement directory (all parts) to MusicXML. Returns True on success."""
    part_files = sorted(f for f in mvt_dir.iterdir()
                        if f.is_file() and not f.name.startswith('s') and not f.name.startswith('m'))
    if not part_files:
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for pf in part_files:
            # X:1000 is musedata's "concert pitch" marker; music21 misreads it
            # as a +1000-semitone transposition → replace with X:0
            content = pf.read_text(errors='replace')
            if 'X:1000' in content:
                content = content.replace('X:1000', 'X:0')
            (tmp / (pf.name + '.md')).write_text(content)

        try:
            score = music21.converter.parse(str(tmp), format='musedata')
        except Exception as e:
            print(f'      [error] parse: {e}', flush=True)
            return False

        if score is None or not score.parts:
            return False

        try:
            score.write('musicxml', fp=str(out_path))
            return True
        except Exception as e:
            print(f'      [error] write: {e}', flush=True)
            return False


def convert_work(section: str, bwv_dir: Path, dry_run=False):
    stage2 = bwv_dir / 'stage2'
    bwv = bwv_dir.name
    label = bwv_label(bwv)
    prefix = f'musedata_{section}_{label}'

    mvt_dirs = sorted(d for d in stage2.iterdir() if d.is_dir())
    if not mvt_dirs:
        return 0

    print(f'  {section}/{bwv} ({len(mvt_dirs)} mvt)', flush=True)
    if dry_run:
        return 0

    created = 0
    if len(mvt_dirs) == 1:
        out = OUT_DIR / f'{prefix}.xml'
        if out.exists():
            print(f'    [skip] {out.name}', flush=True)
            return 1
        ok = convert_movement(mvt_dirs[0], out)
        if ok:
            print(f'    [ok] {out.name}', flush=True)
            created += 1
        else:
            print(f'    [fail] {out.name}', flush=True)
    else:
        for i, mvt_dir in enumerate(mvt_dirs, 1):
            out = OUT_DIR / f'{prefix}_{i}.xml'
            if out.exists():
                print(f'    [skip] {out.name}', flush=True)
                created += 1
                continue
            ok = convert_movement(mvt_dir, out)
            if ok:
                print(f'    [ok] {out.name}', flush=True)
                created += 1
            else:
                print(f'    [fail] {out.name}', flush=True)

    return created


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--filter', default='')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    # Skip sections we already have in kern
    SKIP_SECTIONS = {'chorals', 'keybd'}
    SKIP_BWV = {'1046', '1047', '1048', '1049', '1050', '1051'}  # Brandenburg — уже есть в kern

    works = find_bwv_works(args.filter)
    works = [(s, d) for s, d in works if s not in SKIP_SECTIONS and d.name not in SKIP_BWV]
    print(f'Found {len(works)} works to convert')

    total = 0
    for section, bwv_dir in works:
        total += convert_work(section, bwv_dir, dry_run=args.dry_run)

    print(f'\nDone. Created/found {total} XML files.')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Convert Handel musedata archive (stage1/stage2 files) to MusicXML.

Source: C:/m_a/kern/musedata/handel/
Output: C:/m_a/lilypond/musicxml/

Usage:
    python convert_handel.py [--filter hwv319] [--dry-run]
"""

import argparse, tempfile
from pathlib import Path

import music21

HANDEL_ROOT = Path('C:/m_a/kern/musedata/handel')
OUT_DIR     = Path('C:/m_a/lilypond/musicxml')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Non-music subdirs to skip at any level
SKIP_NAMES = {'doc', 'edition', 'editions', 'intro', 'outputs', 'report',
              'index', 'index-b', 'auto', 'h-index'}


def find_works(filter_term=''):
    """Yield (label, stage_dir) for each work. Prefer stage2 over stage1."""
    seen = set()
    for p in sorted(HANDEL_ROOT.rglob('stage1')):
        if p.is_dir() and p.parent not in seen:
            seen.add(p.parent)
    for p in sorted(HANDEL_ROOT.rglob('stage2')):
        if p.is_dir() and p.parent not in seen:
            seen.add(p.parent)

    for work_dir in sorted(seen):
        # Skip if any component is a non-music dir
        rel = work_dir.relative_to(HANDEL_ROOT)
        if any(part in SKIP_NAMES for part in rel.parts):
            continue
        stage = (work_dir / 'stage2') if (work_dir / 'stage2').is_dir() else (work_dir / 'stage1')
        label = 'handel_' + '_'.join(rel.parts).replace(' ', '_')
        if filter_term and filter_term not in label:
            continue
        yield label, stage


def _fix_xml_int_nodes(el):
    """Recursively coerce integer text/tail to str (music21 bug with musedata part names)."""
    if isinstance(el.text, int):
        el.text = str(el.text)
    if isinstance(el.tail, int):
        el.tail = str(el.tail)
    for child in el:
        _fix_xml_int_nodes(child)


def _fix_accidentals(score):
    """Force displayStatus=True for accidentals that contradict the key signature.

    music21 9.9.1 makeAccidentals() has a bug where sharps always get
    displayStatus=False regardless of the key. We fix this by manually checking
    each note: if its accidental alter doesn't match what the key signature
    implies for that pitch class, mark it for display.
    """
    import music21 as _m21
    for part in score.parts:
        # Collect key signatures by offset
        ks_list = list(part.flatten().getElementsByClass('KeySignature'))
        def ks_at(offset):
            ks = None
            for k in ks_list:
                if k.offset <= offset:
                    ks = k
            return ks

        for measure in part.getElementsByClass('Measure'):
            ks = ks_at(measure.offset)
            # Build dict: pitch_class (0-11) → alter from key sig
            key_alters = {}
            if ks:
                for p in ks.alteredPitches:
                    key_alters[p.pitchClass] = p.alter

            # Track accidentals within measure to handle courtesy accidentals
            # (once a pitch is altered in a measure, repeats don't need re-marking)
            seen = {}  # pitchClass → alter seen so far in this measure
            for n in measure.flatten().notes:
                pitches = n.pitches if hasattr(n, 'pitches') else [n.pitch]
                for p in pitches:
                    if p.accidental is None:
                        continue
                    alter = p.accidental.alter
                    pc = p.pitchClass
                    key_alter = key_alters.get(pc, 0)
                    if alter != key_alter:
                        # Accidental contradicts or augments the key sig → show it
                        if seen.get(pc) != alter:
                            p.accidental.displayStatus = True
                            seen[pc] = alter
                        else:
                            p.accidental.displayStatus = False
                    else:
                        # Matches key sig → hide unless it follows a contradiction
                        if seen.get(pc, key_alter) != key_alter:
                            # Preceding note in measure altered this pitch → show courtesy
                            p.accidental.displayStatus = True
                        else:
                            p.accidental.displayStatus = False
                        seen[pc] = alter


def convert_movement(mvt_dir: Path, out_path: Path) -> bool:
    """Convert one movement directory (all part files) to MusicXML."""
    part_files = sorted(f for f in mvt_dir.iterdir() if f.is_file())
    if not part_files:
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for pf in part_files:
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

        _fix_accidentals(score)

        try:
            from music21.musicxml.m21ToXml import ScoreExporter
            import xml.etree.ElementTree as ET
            exp = ScoreExporter(score)
            root = exp.parse()
            _fix_xml_int_nodes(root)
            tree = ET.ElementTree(root)
            ET.indent(tree)
            tree.write(str(out_path), encoding='unicode', xml_declaration=True)
            return True
        except Exception as e:
            print(f'      [error] write: {e}', flush=True)
            return False


def convert_work(label: str, stage_dir: Path, dry_run=False):
    mvt_dirs = sorted(d for d in stage_dir.iterdir() if d.is_dir())
    if not mvt_dirs:
        return 0

    print(f'  {label} ({len(mvt_dirs)} mvt)', flush=True)
    if dry_run:
        return 0

    created = 0
    if len(mvt_dirs) == 1:
        out = OUT_DIR / f'{label}.xml'
        if out.exists():
            print(f'    [skip] {out.name}', flush=True)
            return 1
        ok = convert_movement(mvt_dirs[0], out)
        print(f'    [{"ok" if ok else "fail"}] {out.name}', flush=True)
        if ok:
            created += 1
    else:
        for i, mvt_dir in enumerate(mvt_dirs, 1):
            out = OUT_DIR / f'{label}_{i}.xml'
            if out.exists():
                print(f'    [skip] {out.name}', flush=True)
                created += 1
                continue
            ok = convert_movement(mvt_dir, out)
            print(f'    [{"ok" if ok else "fail"}] {out.name}', flush=True)
            if ok:
                created += 1

    return created


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--filter', default='')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    works = list(find_works(args.filter))
    print(f'Found {len(works)} works to convert')

    total = 0
    for label, stage_dir in works:
        total += convert_work(label, stage_dir, dry_run=args.dry_run)

    print(f'\nDone. Created/found {total} XML files.')


if __name__ == '__main__':
    main()

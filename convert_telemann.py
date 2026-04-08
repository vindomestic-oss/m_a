#!/usr/bin/env python3
"""
Convert Telemann musedata archive (stage1/stage2 files) to MusicXML.

Source: C:/m_a/kern/musedata/telemann/
Output: C:/m_a/lilypond/musicxml/

Usage:
    python convert_telemann.py [--filter vln] [--dry-run]
"""

import argparse, tempfile
from pathlib import Path

import music21

TELE_ROOT = Path('C:/m_a/kern/musedata/telemann')
OUT_DIR   = Path('C:/m_a/lilypond/musicxml')
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _stage_has_data(stage_dir):
    """Return True if majority of movements have non-s/m-prefixed parseable part files."""
    total = ok = 0
    for mvt in stage_dir.iterdir():
        if not mvt.is_dir():
            continue
        total += 1
        for f in mvt.iterdir():
            if f.is_file() and not f.name.startswith('s') and not f.name.startswith('m'):
                ok += 1
                break
    return total > 0 and ok / total > 0.5


def _yield_work(label, path, filter_term):
    """Try path/stage2 then path/stage1; yield (label, stage_dir) if found."""
    s2 = path / 'stage2'
    s1 = path / 'stage1'
    if s2.is_dir() and _stage_has_data(s2):
        stage = s2
    elif s1.is_dir():
        stage = s1
    else:
        return
    label = label.replace(' ', '_')
    if not filter_term or filter_term in label:
        yield label, stage


def find_works(filter_term=''):
    """Yield (label, stage_dir) for each work. Prefer stage2 over stage1."""
    for coll_dir in sorted(TELE_ROOT.iterdir()):
        if not coll_dir.is_dir():
            continue
        coll = coll_dir.name          # chamb / oratorio

        for sub_dir in sorted(coll_dir.iterdir()):
            if not sub_dir.is_dir():
                continue
            sub = sub_dir.name        # ris-t394 / vln / orpheus / seren

            # Case 1: sub_dir itself is a work (has stage1/stage2 directly)
            #   e.g. oratorio/orpheus/stage1  → label telemann_oratorio_orpheus
            if (sub_dir / 'stage1').is_dir() or (sub_dir / 'stage2').is_dir():
                yield from _yield_work(f'telemann_{coll}_{sub}', sub_dir, filter_term)
                continue

            for work_dir in sorted(sub_dir.iterdir()):
                if not work_dir.is_dir():
                    continue
                # Case 2: work_dir has stage1/stage2 directly
                #   e.g. chamb/ris-t394/1/stage1
                if (work_dir / 'stage1').is_dir() or (work_dir / 'stage2').is_dir():
                    yield from _yield_work(f'telemann_{coll}_{sub}_{work_dir.name}', work_dir, filter_term)
                else:
                    # Case 3: one level deeper  e.g. chamb/vln/hamb-41/41n01/stage2
                    for work2_dir in sorted(work_dir.iterdir()):
                        if not work2_dir.is_dir():
                            continue
                        yield from _yield_work(
                            f'telemann_{coll}_{sub}_{work_dir.name}_{work2_dir.name}',
                            work2_dir, filter_term)


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
    for part in score.parts:
        ks_list = list(part.flatten().getElementsByClass('KeySignature'))
        def ks_at(offset):
            ks = None
            for k in ks_list:
                if k.offset <= offset:
                    ks = k
            return ks

        for measure in part.getElementsByClass('Measure'):
            ks = ks_at(measure.offset)
            key_alters = {}
            if ks:
                for p in ks.alteredPitches:
                    key_alters[p.pitchClass] = p.alter

            seen = {}
            for n in measure.flatten().notes:
                pitches = n.pitches if hasattr(n, 'pitches') else [n.pitch]
                for p in pitches:
                    if p.accidental is None:
                        continue
                    alter = p.accidental.alter
                    pc = p.pitchClass
                    key_alter = key_alters.get(pc, 0)
                    if alter != key_alter:
                        if seen.get(pc) != alter:
                            p.accidental.displayStatus = True
                            seen[pc] = alter
                        else:
                            p.accidental.displayStatus = False
                    else:
                        if seen.get(pc, key_alter) != key_alter:
                            p.accidental.displayStatus = True
                        else:
                            p.accidental.displayStatus = False
                        seen[pc] = alter


def convert_movement(mvt_dir: Path, out_path: Path) -> bool:
    """Convert one movement directory (all numeric/p-prefix part files) to MusicXML."""
    part_files = sorted(f for f in mvt_dir.iterdir()
                        if f.is_file() and not f.name.startswith('s') and not f.name.startswith('m'))
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

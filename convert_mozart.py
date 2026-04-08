#!/usr/bin/env python3
"""Convert Mozart musedata archive to MusicXML. Source: kern/musedata/mozart/"""

import argparse, tempfile
from pathlib import Path
import music21

MOZART_ROOT = Path('C:/m_a/kern/musedata/mozart')
OUT_DIR     = Path('C:/m_a/lilypond/musicxml')
OUT_DIR.mkdir(parents=True, exist_ok=True)
SKIP_NAMES  = {'doc', 'index', 'index-b', 'report', 'progs'}


def find_works(filter_term=''):
    seen = set()
    for p in sorted(MOZART_ROOT.rglob('stage*')):
        if p.is_dir() and p.name in ('stage1','stage2') and p.parent not in seen:
            seen.add(p.parent)
    for work_dir in sorted(seen):
        rel = work_dir.relative_to(MOZART_ROOT)
        if any(part in SKIP_NAMES for part in rel.parts):
            continue
        stage = (work_dir/'stage2') if (work_dir/'stage2').is_dir() else (work_dir/'stage1')
        label = 'mozart_' + '_'.join(rel.parts).replace(' ', '_')
        if filter_term and filter_term not in label:
            continue
        yield label, stage


def _part_median_midi(part):
    midi_vals = []
    for n in part.flatten().notes:
        for p in (n.pitches if hasattr(n, 'pitches') else [n.pitch]):
            midi_vals.append(p.midi)
    return sorted(midi_vals)[len(midi_vals) // 2] if midi_vals else 999


def _fix_cello_clef(score, high=60, low=53):
    """Insert treble/bass clef changes in cello parts that go very high."""
    from music21 import clef as m21clef

    def _is_cello_name(part):
        name = str(part.partName or '').lower()
        if 'cello' in name or 'violoncell' in name:
            return True
        for inst in part.flatten().getElementsByClass('Instrument'):
            n = str(getattr(inst, 'partName', '') or
                    getattr(inst, 'instrumentName', '') or '').lower()
            if 'cello' in n or 'violoncell' in n:
                return True
        return False

    # Find cello by name; fall back to lowest-pitched part when names unavailable
    cello_parts = [p for p in score.parts if _is_cello_name(p)]
    if not cello_parts:
        # Fallback: lowest median pitch (reliable for string quartets)
        cello_parts = [min(score.parts, key=_part_median_midi)]

    for part in cello_parts:
        current = 'bass'
        for measure in part.getElementsByClass('Measure'):
            midi_vals = []
            for n in measure.flatten().notes:
                for p in (n.pitches if hasattr(n, 'pitches') else [n.pitch]):
                    midi_vals.append(p.midi)
            if not midi_vals:
                continue
            median = sorted(midi_vals)[len(midi_vals) // 2]
            if median >= high and current != 'treble':
                measure.insert(0, m21clef.TrebleClef())
                current = 'treble'
            elif median < low and current != 'bass':
                measure.insert(0, m21clef.BassClef())
                current = 'bass'


def _fix_xml_int_nodes(el):
    if isinstance(el.text, int): el.text = str(el.text)
    if isinstance(el.tail, int): el.tail = str(el.tail)
    for c in el: _fix_xml_int_nodes(c)


def _fix_accidentals(score):
    for part in score.parts:
        ks_list = list(part.flatten().getElementsByClass('KeySignature'))
        def ks_at(offset):
            ks = None
            for k in ks_list:
                if k.offset <= offset: ks = k
            return ks
        for measure in part.getElementsByClass('Measure'):
            ks = ks_at(measure.offset)
            key_alters = {p.pitchClass: p.alter for p in ks.alteredPitches} if ks else {}
            seen = {}
            for n in measure.flatten().notes:
                for p in (n.pitches if hasattr(n,'pitches') else [n.pitch]):
                    if p.accidental is None: continue
                    alter, pc, ka = p.accidental.alter, p.pitchClass, key_alters.get(p.pitchClass, 0)
                    if alter != ka:
                        p.accidental.displayStatus = seen.get(pc) != alter
                        seen[pc] = alter
                    else:
                        p.accidental.displayStatus = seen.get(pc, ka) != ka
                        seen[pc] = alter


def convert_movement(mvt_dir, out_path):
    part_files = sorted(f for f in mvt_dir.iterdir()
                        if f.is_file() and not f.name.startswith('s') and not f.name.startswith('m'))
    if not part_files: return False
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for pf in part_files:
            c = pf.read_text(errors='replace').replace('X:1000','X:0')
            (tmp/(pf.name+'.md')).write_text(c)
        try:
            score = music21.converter.parse(str(tmp), format='musedata')
        except Exception as e:
            print(f'      [error] parse: {e}', flush=True); return False
        if score is None or not score.parts: return False
        _fix_accidentals(score)
        _fix_cello_clef(score)
        try:
            from music21.musicxml.m21ToXml import ScoreExporter
            import xml.etree.ElementTree as ET
            root = ScoreExporter(score).parse()
            _fix_xml_int_nodes(root)
            tree = ET.ElementTree(root); ET.indent(tree)
            tree.write(str(out_path), encoding='unicode', xml_declaration=True)
            return True
        except Exception as e:
            print(f'      [error] write: {e}', flush=True); return False


def convert_work(label, stage_dir, dry_run=False, force=False):
    mvt_dirs = sorted(d for d in stage_dir.iterdir() if d.is_dir())
    if not mvt_dirs: return 0
    print(f'  {label} ({len(mvt_dirs)} mvt)', flush=True)
    if dry_run: return 0
    created = 0
    if len(mvt_dirs) == 1:
        out = OUT_DIR / f'{label}.xml'
        if out.exists() and not force: print(f'    [skip] {out.name}', flush=True); return 1
        ok = convert_movement(mvt_dirs[0], out)
        print(f'    [{"ok" if ok else "fail"}] {out.name}', flush=True)
        if ok: created += 1
    else:
        for i, mvt_dir in enumerate(mvt_dirs, 1):
            out = OUT_DIR / f'{label}_{i}.xml'
            if out.exists() and not force: print(f'    [skip] {out.name}', flush=True); created += 1; continue
            ok = convert_movement(mvt_dir, out)
            print(f'    [{"ok" if ok else "fail"}] {out.name}', flush=True)
            if ok: created += 1
    return created


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--filter', default='')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='Overwrite existing files')
    args = ap.parse_args()
    works = list(find_works(args.filter))
    print(f'Found {len(works)} works to convert')
    total = sum(convert_work(l, s, args.dry_run, args.force) for l, s in works)
    print(f'\nDone. Created/found {total} XML files.')

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Convert Bach LilyPond collection to MusicXML.
Strategy: LilyPond -> MIDI -> music21 -> MusicXML
Only processes top-level files (have both \score/\book AND \midi blocks).

Usage:
  python lilypond/convert_bach.py
  python lilypond/convert_bach.py --dry-run      # list files only
  python lilypond/convert_bach.py --filter cello # only matching paths
"""
import argparse, subprocess, re, os, sys, shutil
from pathlib import Path
import music21 as m21

LILY    = Path(__file__).parent.parent / 'lilypond_bin/lilypond-2.24.4/bin/lilypond.exe'
SRC_DIR = Path(__file__).parent / 'bach'
OUT_DIR = Path(__file__).parent / 'musicxml'
TMP_DIR = Path(__file__).parent / '_tmp_bach'
OUT_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)


# ── file classification ────────────────────────────────────────────────────────

def is_toplevel(ly_path: Path) -> bool:
    """Return True if file has both a \score/\book block and a \midi block."""
    try:
        text = ly_path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return False
    has_score = bool(re.search(r'\\(score|book)\s*\{', text))
    has_midi  = bool(re.search(r'\\midi\s*(\{|$)', text, re.M))
    return has_score and has_midi


def is_skip(ly_path: Path) -> bool:
    """Skip hub aggregators, title hubs, and arranger/transposed duplicates."""
    name = ly_path.stem.lower()
    skip_patterns = [
        r'hub$', r'title.?hub$',
        r'-viola$', r'-guitar$',       # instrument arrangements
        r'_transposed$',
        r'transposed',
        r'guitar',
        r'viola$',
    ]
    return any(re.search(p, name) for p in skip_patterns)


def short_name(ly_path: Path) -> str:
    """Derive a short output stem from the path."""
    # try to find BWV number
    m = re.search(r'bwv[_-]?(\d+[a-z]?)', str(ly_path).lower())
    bwv = f'bwv{m.group(1)}' if m else None

    # build stem from directory + file name
    parts = ly_path.parts
    # find index after 'bach'
    try:
        idx = [p.lower() for p in parts].index('bach')
        rel_parts = parts[idx+1:]
    except ValueError:
        rel_parts = parts[-2:]

    stem = '_'.join(p.replace('-lys', '').replace('-', '_') for p in rel_parts)
    stem = stem.replace('.ly', '').replace('__', '_')
    # remove leading numbers that are just movement numbers
    stem = re.sub(r'^(\d+)_', r'mv\1_', stem)
    return stem[:80]


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run',  action='store_true')
    parser.add_argument('--filter',   default=None)
    parser.add_argument('--overwrite',action='store_true')
    args = parser.parse_args()

    # collect all .ly files
    all_ly = sorted(SRC_DIR.rglob('*.ly'))
    print(f'Found {len(all_ly)} .ly files')

    candidates = [f for f in all_ly if is_toplevel(f) and not is_skip(f)]
    print(f'Top-level with midi: {len(candidates)}')

    if args.filter:
        candidates = [f for f in candidates
                      if args.filter.lower() in str(f).lower()]
        print(f'After filter "{args.filter}": {len(candidates)}')

    if args.dry_run:
        for f in candidates:
            print(f'  {f.relative_to(SRC_DIR.parent)}')
        return

    ok = err = skip = 0
    for ly in candidates:
        stem    = short_name(ly)
        xml_out = OUT_DIR / f'{stem}.xml'

        if xml_out.exists() and not args.overwrite:
            skip += 1
            continue

        # run LilyPond — generates *.mid in TMP_DIR
        tmp_stem = TMP_DIR / stem
        tmp_stem.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [str(LILY), '-o', str(tmp_stem), str(ly)],
            capture_output=True, text=True, cwd=str(ly.parent)
        )

        # find generated MIDI (may be stem.mid or stem-1.mid etc.)
        midi_files = sorted(TMP_DIR.glob(f'{stem}*.mid'))
        # also check in ly's directory (LilyPond sometimes uses cwd)
        midi_files += sorted(ly.parent.glob('*.mid'))

        if not midi_files:
            print(f'  ERROR no midi: {ly.relative_to(SRC_DIR.parent)}')
            if result.stderr:
                # show last relevant error line
                errs = [l for l in result.stderr.splitlines()
                        if 'Fehler' in l or 'error' in l.lower()]
                if errs:
                    print(f'    {errs[-1][:120]}')
            err += 1
            continue

        # convert first (or only) MIDI to MusicXML
        midi_path = midi_files[0]
        try:
            score = m21.converter.parse(str(midi_path))
            score.write('musicxml', str(xml_out))
            n_notes = sum(1 for n in score.flatten().notes)
            print(f'  OK {stem}  parts={len(score.parts)}  notes={n_notes}')
            ok += 1
        except Exception as e:
            print(f'  ERROR music21 {stem}: {e}')
            err += 1

        # clean up MIDI files found in source dir
        for mf in sorted(ly.parent.glob('*.mid')):
            try: mf.unlink()
            except: pass

    print(f'\nDone: {ok} ok, {err} errors, {skip} skipped')
    print(f'Output: {OUT_DIR}')


if __name__ == '__main__':
    main()

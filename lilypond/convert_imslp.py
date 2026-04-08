#!/usr/bin/env python3
"""
Extract and convert IMSLP LilyPond zip files to MusicXML.

For each zip in imslp_downloads/:
  1. Extract .ly files to a temp dir
  2. Run convert-ly to upgrade syntax
  3. Run lilypond via ly_dump.ily to get note events
  4. Convert to MusicXML and save to lilypond/musicxml/

Usage:
    python lilypond/convert_imslp.py
    python lilypond/convert_imslp.py --dry-run
"""

import argparse, io, os, re, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT      = Path(__file__).parent.parent
LILY_BIN  = ROOT / 'lilypond_bin' / 'lilypond-2.24.4' / 'bin' / 'lilypond.exe'
CONV_LY   = ROOT / 'lilypond_bin' / 'lilypond-2.24.4' / 'bin' / 'convert-ly.py'
PYTHON    = ROOT / 'lilypond_bin' / 'lilypond-2.24.4' / 'bin' / 'python.exe'
DOWNLOADS = ROOT / 'lilypond' / 'imslp_downloads'
OUT_DIR   = ROOT / 'lilypond' / 'musicxml'

sys.path.insert(0, str(ROOT / 'lilypond'))
import convert_ly_direct as cld


def patch_rutger_common(text: str) -> str:
    """Fix Rutger's common.ly / title.ly incompatibilities for LilyPond 2.24."""
    # 0. Remove \version from included files — causes parsing mode regression
    text = re.sub(r'^\s*\\version\s+"[^"]*"\s*$', '', text, flags=re.MULTILINE)
    # 1. compressFullBarRests -> compressEmptyMeasures
    text = text.replace(r'\compressFullBarRests', r'\compressEmptyMeasures')
    # 2. Old define-music-function with (parser loc ...) args — remove parser+location
    text = re.sub(r'\(define-music-function\s*\(parser\s+loc(?:ation)?\s+',
                  '(define-music-function (', text)
    # 2b. Same for define-event-function
    text = re.sub(r'\(define-event-function\s*\(parser\s+loc(?:ation)?\s+',
                  '(define-event-function (', text)
    # 2c. Multi-line define-music-function where args start on next line
    text = re.sub(r'\(define-music-function\s*\n\s*\(parser\s+loc(?:ation)?\s+',
                  '(define-music-function\n  (', text)
    # 3. ParenthesesItem.stencils tweak - comment out
    text = re.sub(r'-\\tweak\s+ParenthesesItem\.stencils\s*\n\s*#\S+',
                  '', text, flags=re.MULTILINE)
    # 4. pKO/pKS/pDO/pDS with invalid articulation syntax — make them no-ops
    text = re.sub(r'^(pKO|pKS|pDO|pDS)\s*=.*$', r'% \g<0>', text, flags=re.MULTILINE)
    # 5. print-page-number-check-first / print-all-headers removed in 2.22
    text = re.sub(r'\bprint-page-number-check-first\b', '(lambda args #t)', text)
    text = re.sub(r'\bprint-all-headers\b', '(lambda args #t)', text)
    # 5b. \on-the-fly removed in 2.24 — drop the conditional, keep the content
    text = re.sub(r'\\on-the-fly\s+[#\\]\S+\s+', '', text)
    # 6. ly:parser-lookup parser sym → ly:parser-lookup sym (parser arg dropped in 2.22)
    text = re.sub(r'\bly:parser-lookup\s+parser\b', 'ly:parser-lookup', text)
    # 7. (ly:music-function-extract fn) parser location args → (fn args) (2.22 style)
    text = re.sub(r'\(\(ly:music-function-extract\s+(\w+)\)\s+parser\s+loc(?:ation)?\s+',
                  r'(\1 ', text)
    # 8. make-thumb-bracket-props: remove 'location' arg from definition and calls
    #    (convert-ly converts 'location' to '(*location*)' in call sites)
    text = re.sub(r'\(define\s*\(make-thumb-bracket-props\s+loc(?:ation)?\s+',
                  '(define (make-thumb-bracket-props ', text)
    text = re.sub(r'\bmake-thumb-bracket-props\s+(?:loc(?:ation)?\b|\(\*location\*\))\s*',
                  'make-thumb-bracket-props ', text)
    # 9. ly:parser-include-string removed in 2.24.
    #    Replace includeOnce definition with a no-op; replace \includeOnce with \include.
    #    Double-inclusion of these files is harmless (paper/layout blocks are idempotent).
    text = re.sub(
        r'includeOnce\s*=\s*\n#\(define-void-function.*?#t\)\)\)\)\)',
        'includeOnce =\n#(define-void-function (filename) (string?) #t)',
        text, flags=re.DOTALL,
    )
    # \includeOnce "foo" → \include "foo"
    text = re.sub(r'\\includeOnce\b', r'\\include', text)
    return text


def get_version(ly_text: str) -> str:
    m = re.search(r'\\version\s+"([^"]+)"', ly_text)
    return m.group(1) if m else '2.24.0'


def upgrade_ly(src: Path, dst: Path) -> bool:
    """Run convert-ly on src → dst. Returns True if successful."""
    result = subprocess.run(
        [str(PYTHON), str(CONV_LY), '-o', str(dst), str(src)],
        capture_output=True, text=True, timeout=30,
    )
    if not dst.exists():
        shutil.copy(src, dst)  # use original if convert-ly produced nothing
    return dst.exists()


def score_files(names: list[str]) -> list[str]:
    """Pick the single best top-level score .ly file from a name list."""
    # top-level only (no subdirs)
    top = [n for n in names if n.endswith('.ly')
           and not n.startswith('__')
           and '/' not in n.replace('\\', '/')]

    # exclude helpers / clef variants / individual parts
    _EXCLUDE = re.compile(
        r'(score-common|score-orig|score-g\b|common-grand|modern.clef'
        r'|^scoreA|^scoreB|^scoreC|^scoreD'   # part files like scoreAViola.ly
        r'|paper.score|bc.music|bc.figure)',    # basso-continuo only
        re.I,
    )
    candidates = [n for n in top if not _EXCLUDE.search(Path(n).name)]

    # prefer the "plain" score: *-score.ly or Score.ly or *_score*.ly
    main = [n for n in candidates
            if re.search(r'(^|[-_])score([-_.]|$)', Path(n).name, re.I)]
    if main:
        # if multiple (e.g. score_w_hpd vs score), prefer the longer/fuller one
        main.sort(key=lambda n: -len(n))
        return [main[0]]

    # fallback: single remaining candidate
    if len(candidates) == 1:
        return candidates
    if len(top) == 1:
        return top
    return []


def process_zip(zip_path: Path, dry_run=False) -> list[str]:
    """Process one zip. Returns list of output XML filenames created."""
    created = []
    with zipfile.ZipFile(zip_path) as z:
        all_names = [n for n in z.namelist() if not n.startswith('__')]
        ly_names  = [n for n in all_names if n.endswith('.ly')]
        # also include .ily files (LilyPond include files used by some collections)
        ily_names = [n for n in all_names if n.endswith('.ily')]
        chosen    = score_files(ly_names)
        if not chosen:
            print(f'  [skip] no .ly files in {zip_path.name}')
            return []

        print(f'  {zip_path.name}: processing {chosen}', flush=True)
        if dry_run:
            return []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # extract all .ly and .ily files (needed for \include)
            all_ly = ly_names + ily_names
            for name in all_ly:
                dest = tmp / Path(name).name
                raw = z.read(name).decode('utf-8', errors='replace')
                dest.write_text(raw, encoding='utf-8')

            # upgrade .ly and .ily files in-place if any has old version
            # Check version BEFORE patching (patch_rutger_common strips \version lines)
            any_old = any(
                get_version((tmp / Path(n).name).read_text(encoding='utf-8', errors='replace')) < '2.24'
                for n in all_ly
            )
            if any_old:
                for name in all_ly:
                    src = tmp / Path(name).name
                    upg = tmp / (src.stem + '_up' + src.suffix)
                    upgrade_ly(src, upg)
                    if upg.exists():
                        src.write_bytes(upg.read_bytes())
                        upg.unlink()

            # Apply compatibility patches AFTER convert-ly
            for name in all_ly:
                f = tmp / Path(name).name
                txt = f.read_text(encoding='utf-8', errors='replace')
                txt = patch_rutger_common(txt)
                f.write_text(txt, encoding='utf-8')

            # Strip \version from ALL included files — only wrapper's \version "2.24.0" counts
            for pat in ('*.ly', '*.ily'):
                for f in tmp.glob(pat):
                    txt = f.read_text(encoding='utf-8', errors='replace')
                    txt = re.sub(r'^\s*\\version\s+"[^"]*"\s*$', '', txt, flags=re.MULTILINE)
                    f.write_text(txt, encoding='utf-8')

            for name in chosen:
                ly_file = tmp / Path(name).name

                # derive output name and check early before running LilyPond
                zip_stem = re.sub(r'^IMSLP\d+-PMLP\d+-|^IMSLP\d+-WIMA\.[^-]+-', '', zip_path.stem)
                ly_stem  = Path(name).stem
                out_name = f'{zip_stem}_{ly_stem}.xml' if ly_stem not in zip_stem else f'{zip_stem}.xml'
                out_path = OUT_DIR / out_name

                # Check if any output files already exist (single or multi-movement)
                mv1_path = OUT_DIR / (out_path.stem + '_1.xml')
                if out_path.exists() or mv1_path.exists():
                    existing = sorted(p.name for p in OUT_DIR.glob(out_path.stem + '*.xml'))
                    for e in existing:
                        print(f'    [skip] {e} already exists', flush=True)
                    created.extend(existing)
                    continue

                try:
                    events = cld.run_lilypond(ly_file)
                except Exception as e:
                    print(f'    [error] {name}: {e}', flush=True)
                    continue
                if events is None:
                    print(f'    [fail] {name}', flush=True)
                    continue

                try:
                    score_groups = cld._split_by_score(events)
                    if len(score_groups) <= 1:
                        score = cld.notes_to_score(events)
                        if score is None:
                            print(f'    [empty] {name}')
                            continue
                        score.write('musicxml', fp=str(out_path))
                        print(f'    [ok] -> {out_name}', flush=True)
                        created.append(out_name)
                    else:
                        for i, grp in enumerate(score_groups, 1):
                            mv_path = OUT_DIR / (out_path.stem + f'_{i}.xml')
                            try:
                                score_mv = cld.notes_to_score(grp)
                                if score_mv is None:
                                    print(f'    [empty] {name} movement {i}')
                                    continue
                                score_mv.write('musicxml', fp=str(mv_path))
                            except Exception as e:
                                print(f'    [error] {name} mvt {i}: {e}', flush=True)
                                continue
                            print(f'    [ok] -> {mv_path.name}', flush=True)
                            created.append(mv_path.name)
                except Exception as e:
                    print(f'    [error] {name} (score build): {e}', flush=True)

    return created


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    zips = sorted(DOWNLOADS.glob('*.zip'))
    print(f'Found {len(zips)} zip files')

    total_ok = 0
    for z in zips:
        created = process_zip(z, dry_run=args.dry_run)
        total_ok += len(created)

    print(f'\nDone. Created {total_ok} XML files.')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Convert all LilyPond WTC files to MusicXML via clean MIDI (no \articulate) + music21.
Usage: python lilypond/convert_all.py
"""
import subprocess, re, os
from pathlib import Path
import music21 as m21

LILY    = Path(__file__).parent.parent / 'lilypond_bin/lilypond-2.24.4/bin/lilypond.exe'
LY_DIR  = Path(__file__).parent
OUT_DIR = LY_DIR / 'musicxml'
TMP_DIR = LY_DIR / '_tmp'
OUT_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)

def _extract_midi_voices(parts_path: Path) -> tuple[str, str]:
    """
    Return (upper_expr, lower_expr) from the *Midi book in the parts file.
    E.g. '<< \\rightHand \\dynamics \\tempi >>'
    """
    text = parts_path.read_text(encoding='utf-8')
    # find the last \score { ... \midi {} } block (inside the Midi book)
    m = re.search(
        r'\\score\s*\{[^}]*\\keepWithTag\s+midi\s*'
        r'\\articulate\s*(<<.*?>>)\s*\\midi\s*\{\}',
        text, re.S
    )
    if not m:
        # try without \articulate (some files may differ)
        m = re.search(
            r'\\score\s*\{[^}]*\\keepWithTag\s+midi\s*(<<.*?>>)\s*\\midi\s*\{\}',
            text, re.S
        )
    if m:
        inner = m.group(1).strip()
        # split on  \new Staff = "upper" ...  and  \new Staff = "lower" ...
        staffs = re.findall(r'\\new\s+Staff\s*=\s*"[^"]*"\s*<<([^>]+)>>', inner)
        if len(staffs) >= 2:
            return staffs[0].strip(), staffs[1].strip()
        return inner, inner
    return r'\rightHand \dynamics \tempi', r'\leftHand \dynamics \tempi'


def make_wrapper(ly_path: Path, stem: str) -> Path:
    """Create a temporary .ly that generates clean MIDI without \\articulate."""
    # find include name for parts file
    text = ly_path.read_text(encoding='utf-8')
    inc  = re.search(r'\\include\s+"(includes/[^"]+parts\.ily)"', text)
    parts_include = inc.group(1) if inc else f'includes/{stem}-parts.ily'
    parts_path    = LY_DIR / parts_include

    upper, lower = _extract_midi_voices(parts_path)

    wrapper = f"""\
\\version "2.24.0"
\\include "includes/global-variables.ily"
\\include "{parts_include}"

\\score {{
  <<
    \\new Staff = "upper" << {upper} >>
    \\new Staff = "lower" << {lower} >>
  >>
  \\midi {{}}
}}
"""
    out = TMP_DIR / f'{stem}-clean.ly'
    out.write_text(wrapper, encoding='utf-8')
    return out


ly_files = sorted(LY_DIR.glob('*-individual.ly'))
print(f'{len(ly_files)} files to convert')

ok = err = 0
for ly in ly_files:
    stem     = ly.stem.replace('-individual', '')
    xml_path = OUT_DIR / f'{stem}.xml'

    if xml_path.exists():
        print(f'  skip {stem}')
        ok += 1
        continue

    # Step 1: create wrapper and run LilyPond → MIDI
    wrapper_ly = make_wrapper(ly, stem)
    midi_path  = TMP_DIR / f'{stem}-clean.mid'

    result = subprocess.run(
        [str(LILY), '-o', str(TMP_DIR / f'{stem}-clean'), str(wrapper_ly)],
        capture_output=True, text=True, cwd=str(LY_DIR)
    )
    if not midi_path.exists():
        # fallback: try original ly file
        midi_fallback = OUT_DIR / f'{stem}.mid'
        if not midi_fallback.exists():
            subprocess.run(
                [str(LILY), '-o', str(OUT_DIR / stem), str(ly)],
                capture_output=True, text=True, cwd=str(LY_DIR)
            )
        midi_path = midi_fallback if midi_fallback.exists() else None

    if not midi_path or not midi_path.exists():
        print(f'  ERROR no midi: {stem}')
        print(result.stderr[-200:] if result.stderr else '')
        err += 1
        continue

    # Step 2: MIDI → MusicXML
    try:
        score = m21.converter.parse(str(midi_path))
        score.write('musicxml', str(xml_path))
        print(f'  OK {stem}  parts={len(score.parts)}')
        ok += 1
    except Exception as e:
        print(f'  ERROR music21 {stem}: {e}')
        err += 1

print(f'\nDone: {ok} ok, {err} errors')
print(f'Output: {OUT_DIR}')

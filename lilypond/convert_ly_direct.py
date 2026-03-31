#!/usr/bin/env python3
"""
Direct LilyPond → MusicXML converter (no MIDI).
Uses LilyPond's Scheme API to extract notes during compilation.

Strategy:
  - Creates a wrapper .ly that hooks toplevel-score-handler
  - LilyPond writes note data as JSON-lines to a temp file
  - Python reads the notes and builds MusicXML via music21

Usage:
  python lilypond/convert_ly_direct.py
  python lilypond/convert_ly_direct.py --filter bwv772
  python lilypond/convert_ly_direct.py --dry-run
"""

import argparse, copy, json, os, re, subprocess, sys, tempfile
from pathlib import Path
from fractions import Fraction

import music21 as m21
from music21 import note as m21note, stream, pitch as m21pitch, duration as m21dur
from music21 import meter, key, tempo

# ── paths ─────────────────────────────────────────────────────────────────────

LILY       = Path(__file__).parent.parent / 'lilypond_bin/lilypond-2.24.4/bin/lilypond.exe'
DUMP_ILY   = Path(__file__).parent / 'ly_dump.ily'
SRC_DIR    = Path(__file__).parent / 'bach'
OUT_DIR    = Path(__file__).parent / 'musicxml'
TMP_DIR    = Path(__file__).parent / '_tmp_direct'
OUT_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)

# Diatonic step names (LilyPond 0=C 1=D 2=E 3=F 4=G 5=A 6=B)
STEP_NAMES  = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
# Natural semitones for each step (relative to C=0)
STEP_SEMI   = [0, 2, 4, 5, 7, 9, 11]


# ── file classification (same as convert_bach.py) ────────────────────────────

def is_toplevel(ly_path: Path) -> bool:
    try:
        text = ly_path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return False
    has_score = bool(re.search(r'\\(score|book)\s*\{', text))
    has_midi  = bool(re.search(r'\\midi\s*(\{|$)', text, re.M))
    return has_score and has_midi


def is_skip(ly_path: Path) -> bool:
    name = ly_path.stem.lower()
    skip_patterns = [
        r'hub$', r'title.?hub$',
        r'-viola$', r'-guitar$',
        r'_transposed$', r'transposed', r'guitar', r'viola$',
    ]
    return any(re.search(p, name) for p in skip_patterns)


def short_name(ly_path: Path) -> str:
    m = re.search(r'bwv[_-]?(\d+[a-z]?)', str(ly_path).lower())
    bwv = f'bwv{m.group(1)}' if m else None
    parts = ly_path.parts
    try:
        idx = [p.lower() for p in parts].index('bach')
        rel_parts = parts[idx+1:]
    except ValueError:
        rel_parts = parts[-2:]
    stem = '_'.join(p.replace('-lys', '').replace('-', '_') for p in rel_parts)
    stem = stem.replace('.ly', '').replace('__', '_')
    stem = re.sub(r'^(\d+)_', r'mv\1_', stem)
    return stem[:80]


# ── LilyPond runner ──────────────────────────────────────────────────────────

def _make_wrapper(ly_path: Path, notes_path: Path) -> Path:
    """Create a temp wrapper .ly that sets up the dump and includes the source.
    If the source uses articulate.ly, patch it out to get unarticulated durations."""
    dump_ily_fwd   = str(DUMP_ILY).replace('\\', '/')
    notes_path_fwd = str(notes_path).replace('\\', '/')

    # Check if source uses articulate.ly; if so, create a patched copy without it
    include_path = ly_path
    try:
        src = ly_path.read_text(encoding='utf-8', errors='replace')
        if re.search(r'\\include\s+["\']articulate\.ly["\']', src):
            patched = re.sub(r'\\include\s+["\']articulate\.ly["\']',
                             '% articulate.ly disabled for note extraction', src)
            patched_path = TMP_DIR / f'_patched_{ly_path.stem}.ly'
            patched_path.write_text(patched, encoding='utf-8')
            include_path = patched_path
    except Exception:
        pass

    ly_path_fwd = str(include_path).replace('\\', '/')
    wrapper = f'''\
\\version "2.24.0"
#(define ly:dump-output-file "{notes_path_fwd}")
\\include "{dump_ily_fwd}"
\\include "{ly_path_fwd}"
'''
    wrapper_path = TMP_DIR / f'_wrap_{ly_path.stem}.ly'
    wrapper_path.write_text(wrapper, encoding='utf-8')
    return wrapper_path


def run_lilypond(ly_path: Path) -> list[dict] | None:
    """Run LilyPond on ly_path; return list of note dicts or None on error."""
    notes_path  = TMP_DIR / f'{ly_path.stem}.jsonl'
    wrapper_ly  = _make_wrapper(ly_path, notes_path)

    if notes_path.exists():
        notes_path.unlink()

    result = subprocess.run(
        [str(LILY), '--loglevel=ERROR',
         '-dno-point-and-click',
         '-o', str(TMP_DIR / ly_path.stem),
         str(wrapper_ly)],
        capture_output=True, text=True,
        cwd=str(ly_path.parent)
    )

    if not notes_path.exists():
        return None

    notes = []
    with open(notes_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                notes.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return notes


# ── note data → music21 ───────────────────────────────────────────────────────

def _onset_frac(on_str: str) -> Fraction:
    """Parse "n/d" or "n" onset string → Fraction (in quarter notes)."""
    # LilyPond moments are in whole notes; music21 offsets are in quarter notes → ×4
    if '/' in on_str:
        n, d = on_str.split('/')
        return Fraction(int(n) * 4, int(d))
    return Fraction(int(on_str) * 4)


def _alter_from_semi(step: int, semi: int) -> float:
    """Compute alteration in semitones from step name and chromatic semitone."""
    nat = STEP_SEMI[step]
    diff = semi - nat
    # Handle wraparound (e.g. Cb: step=0 nat=0 semi=11 → diff=11 → should be -1)
    if diff > 6:
        diff -= 12
    elif diff < -6:
        diff += 12
    return float(diff)


def _dur_from_moment_str(dur_str: str) -> m21dur.Duration:
    """Parse a LilyPond moment duration string 'n/d' (whole notes) → music21 Duration."""
    ql = _onset_frac(dur_str)  # _onset_frac already multiplies by 4 → quarter notes
    return m21dur.Duration(quarterLength=float(ql))


def _fix_pickup_measure(part: m21.stream.Part, pickup_shift: float) -> None:
    """No-op placeholder; pickup XML fix is done in _postprocess_pickup_xml."""
    pass


import xml.etree.ElementTree as _ET

def _postprocess_pickup_xml(xml_path: str, pickup_ql: float) -> None:
    """Remove leading padding rests from each voice in the pickup measure; fix backup elements."""
    if pickup_ql <= 0:
        return
    try:
        tree = _ET.parse(xml_path)
        root = tree.getroot()
        ns = root.tag.split('}')[0][1:] if root.tag.startswith('{') else ''
        tag = lambda t: ('{%s}%s' % (ns, t)) if ns else t

        modified = False
        for part in root.iter(tag('part')):
            measures = list(part.iter(tag('measure')))
            if not measures:
                continue
            m1 = measures[0]
            divs_el = m1.find('.//' + tag('divisions'))
            if divs_el is None:
                continue
            divs = int(divs_el.text)
            pickup_divs = int(round(pickup_ql * divs))

            # Pass 1: remove leading padding rest from each voice
            first_seen: set = set()
            to_remove = []
            for note_el in list(m1.findall(tag('note'))):
                v_el = note_el.find(tag('voice'))
                v = v_el.text if v_el is not None else '1'
                if note_el.find(tag('chord')) is not None:
                    continue
                if v not in first_seen:
                    first_seen.add(v)
                    rest_el = note_el.find(tag('rest'))
                    dur_el  = note_el.find(tag('duration'))
                    if rest_el is not None and dur_el is not None:
                        if int(dur_el.text) == pickup_divs:
                            to_remove.append(note_el)
            for note_el in to_remove:
                m1.remove(note_el)
            if to_remove:
                m1.set('implicit', 'yes')
                modified = True

            # Pass 2: recalculate backup durations (each backup = cursor pos at that point)
            cursor = 0
            for child in list(m1):
                if child.tag == tag('note'):
                    if child.find(tag('chord')) is None:
                        dur_el = child.find(tag('duration'))
                        if dur_el is not None:
                            cursor += int(dur_el.text)
                elif child.tag == tag('backup'):
                    dur_el = child.find(tag('duration'))
                    if dur_el is not None and cursor > 0:
                        dur_el.text = str(cursor)
                    cursor = 0
                elif child.tag == tag('forward'):
                    dur_el = child.find(tag('duration'))
                    if dur_el is not None:
                        cursor += int(dur_el.text)

        if modified:
            tree.write(xml_path, encoding='unicode', xml_declaration=True)
    except Exception:
        pass


def notes_to_score(note_events: list[dict]) -> m21.stream.Score:
    """Convert raw note events to a music21 Score."""
    if not note_events:
        return m21.stream.Score()

    # Separate by (staff, voice)
    from collections import defaultdict
    by_voice: dict[tuple, list] = defaultdict(list)
    time_sigs: list[dict] = []
    key_sigs:  list[dict] = []

    # Detect pickup measure from \partial — compute onset shift
    pickup_shift = Fraction(0)
    p_events = [ev for ev in note_events
                if ev.get('t') == 'P' and _onset_frac(ev.get('on', '0')) == Fraction(0)]
    if p_events:
        pickup_q = _onset_frac(p_events[0]['dur'])
        first_ts = next((ev for ev in note_events if ev.get('t') == 'T'), None)
        if first_ts:
            bar_q = Fraction(first_ts['num'] * 4, first_ts['den'])
            if bar_q > pickup_q:
                pickup_shift = bar_q - pickup_q

    for ev in note_events:
        t = ev.get('t')
        if t in ('N', 'R'):
            st = ev.get('st', '1')
            vc = ev.get('vc', '1')
            by_voice[(st, vc)].append(ev)
        elif t == 'T':
            time_sigs.append(ev)
        elif t == 'K':
            key_sigs.append(ev)

    if not by_voice:
        return m21.stream.Score()

    # Build score: one Part per staff, one voice layer per voice
    score = m21.stream.Score()

    # Collect staff IDs in ORDER OF FIRST APPEARANCE (preserves treble-before-bass)
    seen = set()
    staff_ids = []
    for ev in note_events:
        if ev.get('t') in ('N', 'R'):
            st = ev.get('st', '1')
            if st not in seen:
                seen.add(st)
                staff_ids.append(st)

    # Build time sig map: onset_frac → (num, den)
    ts_map = {}
    for ts in time_sigs:
        on = _onset_frac(ts['on'])
        ts_map[on] = (ts['num'], ts['den'])

    # Default time sig if none found
    if not ts_map:
        ts_map[Fraction(0)] = (4, 4)

    # Key sig map: onset → key string
    ks_map = {}
    for ks in key_sigs:
        on = _onset_frac(ks['on'])
        ks_map[on] = ks

    from music21 import tie as m21tie

    for staff_id in staff_ids:
        # Collect all notes for this staff, sorted by onset then voice
        staff_notes = []
        for (st, vc), evs in by_voice.items():
            if st == staff_id:
                for ev in evs:
                    staff_notes.append((ev, vc))
        staff_notes.sort(key=lambda x: (_onset_frac(x[0]['on']), x[1]))

        # Collect voice IDs in order of first appearance
        seen_vc: set = set()
        voice_ids_for_staff: list = []
        for ev, vc in staff_notes:
            if vc not in seen_vc:
                seen_vc.add(vc)
                voice_ids_for_staff.append(vc)

        # Mark tie-stop: for each voice the next note after a tie=true note
        tie_stop_indices: set = set()
        by_vc: dict[str, list] = {}
        for i, (ev, vc) in enumerate(staff_notes):
            by_vc.setdefault(vc, []).append(i)
        for vc, indices in by_vc.items():
            for j, i in enumerate(indices):
                if staff_notes[i][0].get('tie') and staff_notes[i][0].get('t', 'N') == 'N':
                    for k in range(j + 1, len(indices)):
                        ni = indices[k]
                        if staff_notes[ni][0].get('t', 'N') == 'N':
                            tie_stop_indices.add(ni)
                            break

        def _make_note_or_rest(ev, i):
            """Return a music21 Note or Rest from a JSON event dict."""
            ev_type = ev.get('t', 'N')
            d = _dur_from_moment_str(ev['dur'])
            if ev_type == 'R':
                r = m21note.Rest()
                r.duration = d
                return r
            step  = ev['step']
            semi  = ev['semi']
            ly_oct = ev['oct']
            pname = STEP_NAMES[step]
            alter = _alter_from_semi(step, semi)
            std_oct = ly_oct + 4
            p = m21pitch.Pitch(pname)
            p.octave = std_oct
            if alter == 1.0:    p.accidental = m21pitch.Accidental('sharp')
            elif alter == -1.0: p.accidental = m21pitch.Accidental('flat')
            elif alter == 2.0:  p.accidental = m21pitch.Accidental('double-sharp')
            elif alter == -2.0: p.accidental = m21pitch.Accidental('double-flat')
            elif alter == 0.5:  p.accidental = m21pitch.Accidental('half-sharp')
            elif alter == -0.5: p.accidental = m21pitch.Accidental('half-flat')
            n = m21note.Note()
            n.pitch = p
            n.duration = d
            is_tie_start = bool(ev.get('tie'))
            is_tie_stop  = i in tie_stop_indices
            if is_tie_start and is_tie_stop:
                n.tie = m21tie.Tie('continue')
            elif is_tie_start:
                n.tie = m21tie.Tie('start')
            elif is_tie_stop:
                n.tie = m21tie.Tie('stop')
            return n

        def _make_flat(include_sigs=True) -> m21.stream.Part:
            """Create an empty flat Part with time/key sigs."""
            flat = m21.stream.Part()
            if include_sigs:
                inserted_ts: set = set()
                for on_frac, (num, den) in sorted(ts_map.items()):
                    if on_frac not in inserted_ts:
                        flat.insert(float(on_frac), meter.TimeSignature(f'{num}/{den}'))
                        inserted_ts.add(on_frac)
                for on_frac, ks_ev in sorted(ks_map.items()):
                    s = ks_ev['step']; sm = ks_ev['semi']
                    mode = ks_ev.get('mode', 'major')
                    pname = STEP_NAMES[s]
                    alter = _alter_from_semi(s, sm)
                    try:
                        p = m21pitch.Pitch(pname)
                        p.octave = None
                        if alter == 1.0:  p = m21pitch.Pitch(pname + '#')
                        elif alter == -1.0: p = m21pitch.Pitch(pname + '-')
                        flat.insert(float(on_frac), key.Key(p.name, mode))
                    except Exception:
                        pass
            return flat

        # Build one flat stream per voice
        voice_flats: dict[str, m21.stream.Part] = {}
        for vc_id in voice_ids_for_staff:
            voice_flats[vc_id] = _make_flat(include_sigs=True)

        for i, (ev, vc) in enumerate(staff_notes):
            try:
                obj = _make_note_or_rest(ev, i)
                on_frac = _onset_frac(ev['on']) + pickup_shift
                voice_flats[vc].insert(float(on_frac), obj)
            except Exception:
                pass

        if len(voice_ids_for_staff) == 1:
            # Single voice: simple path
            flat = voice_flats[voice_ids_for_staff[0]]
            try:
                part = flat.makeMeasures(inPlace=False)
                part.makeTies(inPlace=True)
                _fix_pickup_measure(part, float(pickup_shift))
                try:
                    part.makeBeams(inPlace=True)
                except Exception:
                    pass
            except Exception:
                part = flat
            part.id = f'Staff{staff_id}'
            score.append(part)
            continue

        # Multiple voices: make measures per voice then merge into Voice containers
        voice_made: dict[str, m21.stream.Part] = {}
        for vc_id in voice_ids_for_staff:
            try:
                vm = voice_flats[vc_id].makeMeasures(inPlace=False)
                vm.makeTies(inPlace=True)
                voice_made[vc_id] = vm
            except Exception:
                voice_made[vc_id] = m21.stream.Part()

        # Collect union of all measure numbers across all voices
        all_m_nums = sorted(set(
            m.number
            for vpm in voice_made.values()
            for m in vpm.getElementsByClass('Measure')
        ))
        # Build a lookup: m_num -> first voice_made Part that has it (for time/key sigs)
        m_sig_source: dict = {}
        for vc_id in voice_ids_for_staff:
            vpm = voice_made.get(vc_id)
            if not vpm:
                continue
            for m in vpm.getElementsByClass('Measure'):
                if m.number not in m_sig_source:
                    m_sig_source[m.number] = m

        combined_part = m21.stream.Part()
        combined_part.id = f'Staff{staff_id}'

        for m_num in all_m_nums:
            new_m = m21.stream.Measure(number=m_num)

            # Carry over time/key sigs from whichever voice has this measure
            m_obj = m_sig_source.get(m_num)
            if m_obj:
                for obj in m_obj.getElementsByClass(('TimeSignature', 'KeySignature', 'Clef')):
                    new_m.insert(obj.offset, copy.deepcopy(obj))

            for vi, vc_id in enumerate(voice_ids_for_staff):
                v_obj = m21.stream.Voice()
                v_obj.id = str(vi + 1)
                v_made = voice_made.get(vc_id)
                if v_made:
                    try:
                        v_measure = v_made.measure(m_num)
                        if v_measure:
                            for n in v_measure.flatten().notesAndRests:
                                v_obj.insert(n.offset, copy.deepcopy(n))
                    except Exception:
                        pass
                new_m.insert(0, v_obj)

            combined_part.append(new_m)

        _fix_pickup_measure(combined_part, float(pickup_shift))
        score.append(combined_part)

    return score


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run',   action='store_true')
    parser.add_argument('--filter',    default=None)
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--limit',     type=int, default=None)
    args = parser.parse_args()

    all_ly = sorted(SRC_DIR.rglob('*.ly'))
    print(f'Found {len(all_ly)} .ly files')

    candidates = [f for f in all_ly if is_toplevel(f) and not is_skip(f)]
    print(f'Top-level with score+midi: {len(candidates)}')

    if args.filter:
        candidates = [f for f in candidates
                      if args.filter.lower() in str(f).lower()]
        print(f'After filter "{args.filter}": {len(candidates)}')

    if args.limit:
        candidates = candidates[:args.limit]

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

        # Run LilyPond dump
        events = run_lilypond(ly)

        if events is None:
            print(f'  ERROR no output: {ly.relative_to(SRC_DIR.parent)}')
            err += 1
            continue

        n_notes = sum(1 for e in events if e.get('t') == 'N')
        if n_notes == 0:
            print(f'  EMPTY (0 notes): {ly.relative_to(SRC_DIR.parent)}')
            err += 1
            continue

        # Build MusicXML
        try:
            score = notes_to_score(events)
            score.write('musicxml', str(xml_out))
            # Fix pickup measure in the written XML
            p_events = [ev for ev in events
                        if ev.get('t') == 'P' and _onset_frac(ev.get('on', '0')) == Fraction(0)]
            if p_events:
                first_ts = next((ev for ev in events if ev.get('t') == 'T'), None)
                if first_ts:
                    bar_q = Fraction(first_ts['num'] * 4, first_ts['den'])
                    pickup_q = _onset_frac(p_events[0]['dur'])
                    _postprocess_pickup_xml(str(xml_out), float(bar_q - pickup_q))
            n_parts = len(score.parts)
            print(f'  OK {stem}  notes={n_notes}  parts={n_parts}')
            ok += 1
        except Exception as e:
            print(f'  ERROR xml {stem}: {e}')
            err += 1

    print(f'\nDone: {ok} ok, {err} errors, {skip} skipped')
    print(f'Output: {OUT_DIR}')


if __name__ == '__main__':
    main()

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
from music21 import note as m21note, chord as m21chord, stream, pitch as m21pitch, duration as m21dur
from music21 import meter, key, tempo, bar as m21bar, spanner as m21spanner

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


_INC_RE   = re.compile(r'\\include\s+"([^"]+)"')
_TITLE_RE = re.compile(r'\btitle\s*=\s*"([^"]+)"')
_SUB_RE   = re.compile(r'\bsubtitle\s*=\s*"([^"]+)"')
_PIECE_RE = re.compile(r'\bpiece\s*=\s*"([^"]+)"')


def _parse_ly_titles(ly_path: Path) -> tuple[str, list[str]]:
    """Return (global_title, [piece1, piece2, ...]) from a LilyPond file.
    Expands one level of \\include from the same directory.
    global_title combines title + subtitle when both are present.
    If no global title is found in the file itself, searches sibling .ly files
    in the same directory for one that includes this file (hub/master file).
    piece list follows document order (one entry per \\score block's \\header).
    """
    text = ly_path.read_text(encoding='utf-8', errors='replace')
    for m in _INC_RE.finditer(text):
        inc_path = ly_path.parent / m.group(1)
        if inc_path.exists():
            text += inc_path.read_text(encoding='utf-8', errors='replace')

    title_m    = _TITLE_RE.search(text)
    subtitle_m = _SUB_RE.search(text)
    title    = title_m.group(1).strip()    if title_m    else ''
    subtitle = subtitle_m.group(1).strip() if subtitle_m else ''

    # If no global title found, look for a hub file in the same directory
    # that \\include's this file and carries the suite-level title.
    if not title and not subtitle:
        fname = ly_path.name
        for sibling in ly_path.parent.glob('*.ly'):
            if sibling == ly_path:
                continue
            try:
                sib_text = sibling.read_text(encoding='utf-8', errors='replace')
            except Exception:
                continue
            # Check if the sibling includes this file
            if not any(m.group(1) == fname for m in _INC_RE.finditer(sib_text)):
                continue
            t_m = _TITLE_RE.search(sib_text)
            s_m = _SUB_RE.search(sib_text)
            title    = t_m.group(1).strip() if t_m else ''
            subtitle = s_m.group(1).strip() if s_m else ''
            if title or subtitle:
                break  # found a hub with a title

    if title and subtitle and subtitle.lower() != title.lower():
        global_title = f'{title}, {subtitle}'
    else:
        global_title = title or subtitle

    pieces = [p.strip() for p in _PIECE_RE.findall(text)]
    return global_title, pieces


def _patch_xml_title(xml_path: str, title: str) -> None:
    """Replace <movement-title> in a MusicXML file with the given title."""
    try:
        import xml.etree.ElementTree as ET
        ET.register_namespace('', '')
        text = Path(xml_path).read_text(encoding='utf-8')
        import re as _re
        text = _re.sub(
            r'<movement-title>[^<]*</movement-title>',
            f'<movement-title>{title}</movement-title>',
            text, count=1
        )
        Path(xml_path).write_text(text, encoding='utf-8')
    except Exception:
        pass


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
            # Also remove explicit \articulate commands (used as score-level wrapper)
            patched = re.sub(r'\\articulate\b', '', patched)
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

def _split_by_score(events: list) -> list[list]:
    """Split event list at SCORE markers; returns one sub-list per score."""
    groups: list[list] = []
    cur: list = []
    for ev in events:
        if ev.get('t') == 'SCORE':
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(ev)
    if cur:
        groups.append(cur)
    return groups if groups else [events]


def _shift_multi_score_events(events: list) -> list:
    """
    When a JSONL file contains multiple scores (from a \\book with multiple
    \\score blocks), each score resets its internal clock to onset 0.  This
    function detects SCORE boundary markers and shifts each score's events so
    they are concatenated end-to-end in quarter-note time.

    Returns a new event list with 'on' and 'dur' fields adjusted.
    """
    # Split into per-score groups at SCORE markers
    groups: list[list] = []
    cur: list = []
    for ev in events:
        if ev.get('t') == 'SCORE':
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(ev)
    if cur:
        groups.append(cur)

    if len(groups) <= 1:
        return events  # single score — nothing to shift

    def _frac_of(s: str) -> Fraction:
        if '/' in s:
            n, d = s.split('/')
            return Fraction(int(n), int(d))
        return Fraction(int(s))

    def _frac_to_str(f: Fraction) -> str:
        return str(f.numerator) if f.denominator == 1 else f'{f.numerator}/{f.denominator}'

    def _end_of_group(group: list) -> Fraction:
        """Return the end time of the group in LilyPond whole-note units."""
        end = Fraction(0)
        for ev in group:
            if ev.get('t') in ('N', 'R'):
                on  = _frac_of(ev.get('on', '0'))
                dur = _frac_of(ev.get('dur', '0'))
                end = max(end, on + dur)
        return end

    result = []
    cumulative = Fraction(0)
    for group in groups:
        if cumulative == 0:
            result.extend(group)
        else:
            for ev in group:
                shifted = dict(ev)
                if 'on' in ev:
                    shifted['on'] = _frac_to_str(_frac_of(ev['on']) + cumulative)
                result.append(shifted)
        cumulative += _end_of_group(group)

    return result


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


def _split_wide_range_part(score: m21.stream.Score) -> None:
    """
    If the score has one Part with multiple voices in clearly different registers,
    split into treble and bass Parts.
    Algorithm: find the largest gap between consecutive voice averages; split there
    if gap >= MIN_GAP semitones and the lower group has avg < BASS_MAX.
    """
    MIN_GAP  = 7    # minimum gap (semitones) between groups to justify a split
    BASS_MAX = 60   # lower group must have avg below this to be considered bass

    # Merge truly-stray parts back into the first part before checking.
    # Only absorbs Part2 with ≤ 2 notes — these arise when a single stray chord
    # (e.g. the final << re2. \\ re,2. >> in Menuet1 left hand) gets home_staff="two"
    # while all real voices landed in Part1 via cross-staff heuristic.
    # A threshold of ≤ 2 notes is conservative enough to avoid absorbing any
    # legitimate (even sparse) bass line.
    if len(score.parts) >= 2:
        for p in list(score.parts[1:]):
            part_notes = sum(1 for _ in p.flatten().notes)
            if part_notes <= 2:
                p1 = score.parts[0]
                for m in p.getElementsByClass('Measure'):
                    mnum = m.number
                    target = p1.measure(mnum)
                    if target is not None:
                        for v in m.getElementsByClass('Voice'):
                            target.insert(0, copy.deepcopy(v))
                score.remove(p)

    if len(score.parts) != 1:
        return

    part = score.parts[0]
    measures = list(part.getElementsByClass('Measure'))
    if not measures:
        return

    # Collect average MIDI per voice ID
    voice_midis: dict[str, list[int]] = {}
    for m in measures:
        for v in m.getElementsByClass('Voice'):
            vid = str(v.id)
            for n in v.flatten().notes:
                if isinstance(n, m21note.Note):
                    voice_midis.setdefault(vid, []).append(n.pitch.midi)

    if len(voice_midis) < 2:
        return

    voice_avg = {vid: sum(ms) / len(ms) for vid, ms in voice_midis.items() if ms}
    # Sort voices by average pitch ascending
    sorted_vids = sorted(voice_avg, key=lambda v: voice_avg[v])

    # Find the largest gap between consecutive averages
    best_gap = 0
    best_split = 0   # split after index best_split (inclusive) → bass
    for i in range(len(sorted_vids) - 1):
        gap = voice_avg[sorted_vids[i + 1]] - voice_avg[sorted_vids[i]]
        if gap > best_gap:
            best_gap = gap
            best_split = i

    if best_gap < MIN_GAP:
        return  # no clear register gap

    bass_vids   = set(sorted_vids[:best_split + 1])
    treble_vids = set(sorted_vids[best_split + 1:])

    # Lower group must be in genuine bass territory
    lower_avg = sum(voice_avg[v] for v in bass_vids) / len(bass_vids)
    if lower_avg >= BASS_MAX:
        return

    if not treble_vids or not bass_vids:
        return

    # Require the lower group to be a real melodic part, not just isolated chord tones.
    # If it has fewer than 25% of total notes it is a chord-fill voice (e.g. cello suite
    # melodyTwo) and should stay on the same staff as the upper voice.
    total_lower = sum(len(voice_midis.get(v, [])) for v in bass_vids)
    total_all   = sum(len(ms) for ms in voice_midis.values())
    if total_all > 0 and total_lower / total_all < 0.25:
        return

    # Build treble and bass Parts
    treble_part = m21.stream.Part()
    treble_part.id = part.id + '_treble'
    bass_part   = m21.stream.Part()
    bass_part.id = part.id + '_bass'

    for m in measures:
        tm = m21.stream.Measure(number=m.number)
        bm = m21.stream.Measure(number=m.number)
        # Copy time/key sigs to both staves
        for obj in m.getElementsByClass(('TimeSignature', 'KeySignature')):
            tm.insert(obj.offset, copy.deepcopy(obj))
            bm.insert(obj.offset, copy.deepcopy(obj))
        # Distribute voices; track per-part voice order for renumbering
        t_vi = 1
        b_vi = 1
        for v in m.getElementsByClass('Voice'):
            vid = str(v.id)
            vc = copy.deepcopy(v)
            if vid in treble_vids:
                vc.id = str(t_vi)
                t_vi += 1
                tm.insert(0, vc)
            else:
                vc.id = str(b_vi)
                b_vi += 1
                bm.insert(0, vc)
        treble_part.append(tm)
        bass_part.append(bm)

    score.remove(part)
    # Fixed clefs for split parts — do NOT use auto-clef, which would add
    # mid-piece clef changes based on local averages and make the upper part
    # appear in bass clef when a lower inner voice dominates a window.
    treble_part.measures(1, 1)[0].insert(0, m21clef.TrebleClef())
    bass_part.measures(1, 1)[0].insert(0, m21clef.BassClef())
    score.insert(0, treble_part)
    score.append(bass_part)


from music21 import clef as m21clef


def _assign_stem_directions(score: m21.stream.Score) -> None:
    """
    In each measure that has multiple voices, assign explicit stem directions:
    voice ranked highest by average pitch → 'up', next → 'down', rest → 'up'/'down' alternating.
    Single-voice measures are left untouched (verovio auto-stems).
    """
    for part in score.parts:
        for meas in part.getElementsByClass('Measure'):
            voices = list(meas.getElementsByClass('Voice'))
            if len(voices) < 2:
                continue
            # Rank voices by average pitch descending (highest pitch → stems up)
            def voice_avg(v):
                pitches = [n.pitch.midi for n in v.flatten().notes
                           if isinstance(n, m21note.Note)]
                return sum(pitches) / len(pitches) if pitches else 0
            ranked = sorted(voices, key=voice_avg, reverse=True)
            for i, v in enumerate(ranked):
                direction = 'up' if i == 0 else 'down'
                for n in v.flatten().notesAndRests:
                    if isinstance(n, (m21note.Note, m21chord.Chord)):
                        n.stemDirection = direction

def _add_auto_clefs(part: m21.stream.Part) -> None:
    """
    Insert clef objects into the Part based on local pitch range.
    Analyzes notes in sliding windows of ~4 measures; changes clef when the
    average pitch clearly indicates a different clef than is currently active.
    Thresholds: avg MIDI < 58 → bass, avg MIDI > 63 → treble (hysteresis gap 58-63).
    """
    measures = list(part.getElementsByClass('Measure'))
    if not measures:
        return

    # Gather average MIDI per measure
    midi_per_measure: list[float | None] = []
    for m in measures:
        pitches = [n.pitch.midi for n in m.flatten().notes
                   if isinstance(n, m21note.Note)]
        midi_per_measure.append(sum(pitches) / len(pitches) if pitches else None)

    # Smooth: for each measure use average of window ±2 measures
    WIN = 2
    smoothed: list[float | None] = []
    for i in range(len(measures)):
        vals = [v for v in midi_per_measure[max(0,i-WIN):i+WIN+1] if v is not None]
        smoothed.append(sum(vals) / len(vals) if vals else None)

    # Decide clef per measure, with hysteresis
    BASS_THRESH   = 58   # avg below this → bass
    TREBLE_THRESH = 63   # avg above this → treble

    current_clef = None   # will be set on first measure
    for i, (m, avg) in enumerate(zip(measures, smoothed)):
        if avg is None:
            continue
        if avg < BASS_THRESH:
            desired = 'bass'
        elif avg > TREBLE_THRESH:
            desired = 'treble'
        else:
            desired = current_clef  # stay in current when ambiguous

        if desired is None:
            desired = 'treble'  # default

        if desired != current_clef:
            # Remove any existing clef in this measure
            for c in list(m.getElementsByClass('Clef')):
                m.remove(c)
            if desired == 'bass':
                m.insert(0, m21clef.BassClef())
            else:
                m.insert(0, m21clef.TrebleClef())
            current_clef = desired


import xml.etree.ElementTree as _ET


def _compute_shifts(note_events: list) -> tuple:
    """
    Compute pickup_shift, mid_shifts, and section_pickup_offsets from P and T events.
    Returns:
      pickup_shift:            Fraction — global shift applied to all note offsets
      mid_shifts:              list of (threshold_q, extra_q) Fractions
      section_pickup_offsets:  list of (measure_start_q_float, padding_ql_float)
                               for each mid-piece pickup measure (used by postprocess)
    """
    # Time sig helper — defaults to 4/4 when no T events present
    ts_sorted = sorted([ev for ev in note_events if ev.get('t') == 'T'],
                       key=lambda e: _onset_frac(e['on']))
    def _bar_q_at(onset_q: Fraction) -> Fraction:
        best = Fraction(4)  # default 4/4
        for ts in ts_sorted:
            if _onset_frac(ts['on']) <= onset_q:
                best = Fraction(ts['num'] * 4, ts['den'])
        return best

    # Initial pickup (P at onset 0)
    p0 = [ev for ev in note_events
          if ev.get('t') == 'P' and _onset_frac(ev.get('on', '0')) == Fraction(0)]
    pickup_shift = Fraction(0)
    if p0:
        bar_q = _bar_q_at(Fraction(0))
        pickup_q = _onset_frac(p0[0]['dur'])
        if bar_q > pickup_q:
            pickup_shift = bar_q - pickup_q

    # \set Timing.measurePosition at start (e.g. \partialPickup — no \partial event)
    # The MP pos is the offset of the first note within the bar; all note onsets start
    # from 0, so pickup_shift = pos_q shifts them into the correct position.
    if not pickup_shift:
        mp0 = [ev for ev in note_events
               if ev.get('t') == 'MP' and _onset_frac(ev.get('on', '0')) == Fraction(0)]
        if mp0:
            mp_pos_q = _onset_frac(mp0[0]['pos'])
            bar_q = _bar_q_at(Fraction(0))
            if Fraction(0) < mp_pos_q < bar_q:
                pickup_shift = mp_pos_q

    # Mid-piece pickup sections (P events at onset > 0)
    # Deduplicate by onset — multiple staves emit identical P events.
    mid_shifts: list[tuple[Fraction, Fraction]] = []
    seen_p_onsets: set = set()
    for p_ev in sorted([e for e in note_events if e.get('t') == 'P'],
                       key=lambda e: _onset_frac(e['on'])):
        p_on_q = _onset_frac(p_ev['on'])
        if p_on_q == Fraction(0) or p_on_q in seen_p_onsets:
            continue
        seen_p_onsets.add(p_on_q)
        p_dur_q = _onset_frac(p_ev['dur'])
        b_q = _bar_q_at(p_on_q)
        if b_q > p_dur_q:
            mid_shifts.append((p_on_q, b_q - p_dur_q))

    # Compute expected measure start offset for each section pickup
    # (used by _postprocess_pickup_xml to find the right measure by position)
    section_pickup_offsets: list[tuple[float, float]] = []
    cumulative_extra = Fraction(0)
    for threshold_q, extra_q in mid_shifts:
        measure_start_q = threshold_q + pickup_shift + cumulative_extra
        section_pickup_offsets.append((float(measure_start_q), float(extra_q)))
        cumulative_extra += extra_q

    return pickup_shift, mid_shifts, section_pickup_offsets


def _postprocess_pickup_xml(xml_path: str, pickup_ql: float,
                             section_pickup_offsets: list = None) -> None:
    """
    Fix pickup measures in MusicXML:
    - First measure: remove leading padding rests of pickup_ql, mark implicit.
    - Mid-piece pickup measures (identified by section_pickup_offsets): same treatment.
      Each entry is (measure_start_q_float, padding_ql_float). Measures are found by
      accumulating their expected quarter-note offsets using the time signature.
    - Renumber all measures: implicit ones get unique negative numbers (not displayed),
      explicit measures get 1, 2, 3, …
    """
    if pickup_ql <= 0 and not section_pickup_offsets:
        return
    try:
        tree = _ET.parse(xml_path)
        root = tree.getroot()
        ns = root.tag.split('}')[0][1:] if root.tag.startswith('{') else ''
        tag = lambda t: ('{%s}%s' % (ns, t)) if ns else t

        def _fix_pickup_measure(m_el, divs, padding_divs):
            """Remove leading padding rests from each voice; fix backup durations.
            The padding may be split across multiple consecutive rests (e.g. 5.5q
            becomes a whole + dotted-quarter rest). Collects all leading rests per
            voice and removes them if their total equals padding_divs.
            Returns True if the measure was modified."""
            # Collect consecutive leading rests per voice (before first non-rest)
            voice_leading: dict = {}   # v -> [note_el, ...]
            voice_done: set = set()
            for note_el in list(m_el.findall(tag('note'))):
                if note_el.find(tag('chord')) is not None:
                    continue
                v_el = note_el.find(tag('voice'))
                v = v_el.text if v_el is not None else '1'
                if v in voice_done:
                    continue
                rest_el = note_el.find(tag('rest'))
                dur_el  = note_el.find(tag('duration'))
                if rest_el is not None and dur_el is not None:
                    voice_leading.setdefault(v, []).append(note_el)
                else:
                    voice_done.add(v)   # first non-rest seen — stop collecting

            to_remove = []
            for v, rests in voice_leading.items():
                # Greedily collect leading rests up to exactly padding_divs.
                # Stops as soon as cumulative == padding_divs, so a real pickup
                # rest that follows the padding is kept.
                candidate = []
                cumulative = 0
                for r in rests:
                    dur_el = r.find(tag('duration'))
                    if dur_el is None:
                        continue
                    dur = int(dur_el.text)
                    if cumulative < padding_divs:
                        candidate.append(r)
                        cumulative += dur
                    else:
                        break
                if cumulative == padding_divs:
                    to_remove.extend(candidate)
            for note_el in to_remove:
                m_el.remove(note_el)
            if not to_remove:
                return False
            m_el.set('implicit', 'yes')
            # Recalculate backup durations
            cursor = 0
            for child in list(m_el):
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
            return True

        modified = False
        for part in root.iter(tag('part')):
            measures = list(part.iter(tag('measure')))
            if not measures:
                continue
            # divisions may only appear in the first measure
            divs_el = measures[0].find('.//' + tag('divisions'))
            if divs_el is None:
                continue
            divs = int(divs_el.text)

            # Determine initial bar_q from the time signature in the first measure
            bar_q = 4.0  # default 4/4
            for m_el in measures[:1]:
                ts_el = m_el.find('.//' + tag('time'))
                if ts_el is not None:
                    beats = ts_el.find(tag('beats'))
                    btype = ts_el.find(tag('beat-type'))
                    if beats is not None and btype is not None:
                        bar_q = int(beats.text) * 4.0 / int(btype.text)

            # Build offset→padding_ql map for section pickups
            section_map: dict[float, float] = {}
            for off_q, p_ql in (section_pickup_offsets or []):
                section_map[off_q] = p_ql

            # Walk measures, tracking running quarter-note offset
            running_offset = 0.0
            for m_el in measures:
                # Update bar_q if this measure changes the time signature
                ts_el = m_el.find('.//' + tag('time'))
                if ts_el is not None:
                    beats = ts_el.find(tag('beats'))
                    btype = ts_el.find(tag('beat-type'))
                    if beats is not None and btype is not None:
                        bar_q = int(beats.text) * 4.0 / int(btype.text)

                padding_ql = None
                if running_offset < 0.05 and pickup_ql > 0:
                    # First measure: initial pickup
                    padding_ql = pickup_ql
                else:
                    # Check if this measure matches a known section pickup offset
                    for off_q, p_ql in section_map.items():
                        if abs(running_offset - off_q) < 0.1:
                            padding_ql = p_ql
                            break

                if padding_ql is not None:
                    padding_divs = int(round(padding_ql * divs))
                    if _fix_pickup_measure(m_el, divs, padding_divs):
                        modified = True

                running_offset += bar_q

            # Renumber: implicit measures get unique negative numbers (not displayed),
            # explicit measures get 1, 2, 3, …
            implicit_num = 0
            display_num = 1
            for m_el in measures:
                if m_el.get('implicit') == 'yes':
                    m_el.set('number', str(implicit_num))
                    implicit_num -= 1
                else:
                    m_el.set('number', str(display_num))
                    display_num += 1

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

    pickup_shift, mid_shifts, _section_pickup_offsets = _compute_shifts(note_events)

    # First pass: determine home staff for each voice.
    # Use majority staff (staff containing >= 2/3 of actual notes) when a voice
    # predominantly lives in a different staff than its first appearance (e.g. voices
    # declared in Upper but living mostly in Lower via \change Staff).
    # Fall back to first-appearance staff for true cross-staff voices (balanced split).
    from collections import Counter as _Counter
    vc_first_st: dict[str, str] = {}
    vc_note_counts: dict[str, _Counter] = {}
    for ev in note_events:
        if ev.get('t') in ('N', 'R'):
            vc = ev.get('vc', '1')
            if vc not in vc_first_st:
                vc_first_st[vc] = ev.get('st', '1')
        if ev.get('t') == 'N':  # actual notes only (not rests) for majority vote
            vc = ev.get('vc', '1')
            vc_note_counts.setdefault(vc, _Counter())[ev.get('st', '1')] += 1
    vc_home_st: dict[str, str] = {}
    for vc, first_st in vc_first_st.items():
        counts = vc_note_counts.get(vc, _Counter())
        if counts:
            total = sum(counts.values())
            best_st, best_n = counts.most_common(1)[0]
            # Override first-appearance staff only when the majority is overwhelming (>= 2/3)
            if best_st != first_st and best_n >= total * 2 / 3:
                vc_home_st[vc] = best_st
            else:
                vc_home_st[vc] = first_st
        else:
            vc_home_st[vc] = first_st

    for ev in note_events:
        t = ev.get('t')
        if t in ('N', 'R'):
            vc = ev.get('vc', '1')
            # Use home staff for this voice (merges cross-staff voices into one Part)
            home_st = vc_home_st.get(vc, ev.get('st', '1'))
            by_voice[(home_st, vc)].append(ev)
        elif t == 'T':
            time_sigs.append(ev)
        elif t == 'K':
            key_sigs.append(ev)

    if not by_voice:
        return m21.stream.Score()

    # Merge sparse voices (≤5 notes) into the dominant voice on the same staff.
    # These arise from SimultaneousMusic chords creating one sub-voice per note.
    # Guard: only merge if doing so won't create time-overlapping notes — overlapping
    # notes indicate genuine polyphony (voice splits) rather than chord artifacts.
    def _notes_overlap(evs_a: list, evs_b: list) -> bool:
        """Return True if any note in evs_a overlaps in time with any note in evs_b."""
        b_ivs = []
        for ev in evs_b:
            if ev.get('t') == 'N':
                on = _onset_frac(ev['on'])
                b_ivs.append((on, on + _onset_frac(ev['dur'])))
        for ev in evs_a:
            if ev.get('t') != 'N':
                continue
            a_on = _onset_frac(ev['on'])
            a_end = a_on + _onset_frac(ev['dur'])
            for b_on, b_end in b_ivs:
                if a_on < b_end and a_end > b_on:
                    return True
        return False

    for st in set(k[0] for k in by_voice):
        # Find dominant voice on this staff (most notes)
        st_voices = {vc: evs for (s, vc), evs in by_voice.items() if s == st}
        if len(st_voices) <= 1:
            continue
        main_vc = max(st_voices, key=lambda v: sum(1 for e in st_voices[v] if e.get('t') == 'N'))
        main_n  = sum(1 for e in st_voices[main_vc] if e.get('t') == 'N')
        for vc, evs in list(st_voices.items()):
            if vc == main_vc:
                continue
            n = sum(1 for e in evs if e.get('t') == 'N')
            if n <= 5 or n < main_n * 0.05:
                # st_voices[main_vc] is the same list object as by_voice[(st, main_vc)],
                # so it reflects any previous merges in this loop iteration.
                if not _notes_overlap(evs, st_voices[main_vc]):
                    by_voice[(st, main_vc)].extend(evs)
                    del by_voice[(st, vc)]

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

        # Mark tie-stop: for each original voice, the next note after a tie=true note.
        # Use ev['vc'] (original sub-voice) rather than the merged voice key so that
        # ties within chords (e.g. one note of a SimultaneousMusic chord) resolve to
        # the correct continuation note in the same sub-voice.
        # Cross-voice fallback: if the same-voice next note has a different pitch,
        # search all voices for a note with the same pitch at onset = (tie_start_onset + dur).
        tie_stop_indices: set = set()
        by_vc: dict[str, list] = {}
        for i, (ev, vc) in enumerate(staff_notes):
            orig_vc = ev.get('vc', vc)
            by_vc.setdefault(orig_vc, []).append(i)
        # Build pitch+onset lookup for cross-voice resolution
        _onset_pitch_idx: dict[tuple, list] = {}
        for i, (ev, _vc) in enumerate(staff_notes):
            if ev.get('t', 'N') == 'N':
                _pkey = (_onset_frac(ev['on']), ev.get('step'), ev.get('oct'))
                _onset_pitch_idx.setdefault(_pkey, []).append(i)
        for vc, indices in by_vc.items():
            for j, i in enumerate(indices):
                ev_i = staff_notes[i][0]
                if ev_i.get('tie') and ev_i.get('t', 'N') == 'N':
                    step_i, oct_i = ev_i.get('step'), ev_i.get('oct')
                    # Expected onset of tie destination = onset + dur
                    exp_on = _onset_frac(ev_i['on']) + _onset_frac(ev_i['dur'])
                    # First try: same original voice, pitch must match
                    found = False
                    for k in range(j + 1, len(indices)):
                        ni = indices[k]
                        ni_ev = staff_notes[ni][0]
                        if ni_ev.get('t', 'N') != 'N':
                            continue
                        if ni_ev.get('step') == step_i and ni_ev.get('oct') == oct_i:
                            tie_stop_indices.add(ni)
                            found = True
                        break  # only check first note in same voice (whether pitch matches or not)
                    if not found:
                        # Cross-voice: find same pitch at expected onset
                        candidates = _onset_pitch_idx.get((exp_on, step_i, oct_i), [])
                        if candidates:
                            tie_stop_indices.add(candidates[0])

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
                    try:
                        # Use sharps count from pitch-alist (reliable) rather than mode string
                        sharps = ks_ev.get('sharps', None)
                        if sharps is not None:
                            flat.insert(float(on_frac), key.KeySignature(sharps))
                        else:
                            # Fallback for old-format events without 'sharps'
                            s = ks_ev['step']; sm = ks_ev['semi']
                            mode = ks_ev.get('mode', 'major')
                            pname = STEP_NAMES[s]
                            alter = _alter_from_semi(s, sm)
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
                # Skip rests that come from a non-home staff (cross-staff filler rests
                # from the other grand-staff hand should not pollute the home-staff voice).
                if ev.get('t') == 'R' and ev.get('st') != staff_id:
                    continue
                obj = _make_note_or_rest(ev, i)
                on_frac = _onset_frac(ev['on']) + pickup_shift
                for threshold_q, extra_q in mid_shifts:
                    if _onset_frac(ev['on']) >= threshold_q:
                        on_frac += extra_q
                voice_flats[vc].insert(float(on_frac), obj)
            except Exception:
                pass

        # Merge simultaneous notes at the same offset into Chords within each voice
        for vc_id, flat in voice_flats.items():
            # Collect offsets that have multiple Note objects
            from collections import defaultdict
            offset_notes: dict = defaultdict(list)
            for el in list(flat.getElementsByClass(m21note.Note)):
                offset_notes[el.offset].append(el)
            for off, nlist in offset_notes.items():
                if len(nlist) < 2:
                    continue
                # Build a Chord from all notes at this offset.
                # Individual note ties are already set in _make_note_or_rest;
                # do NOT set chord.tie (that would override per-note ties and
                # mark all notes in the chord as tied, not just the intended one).
                chord = m21chord.Chord(nlist)
                chord.duration = nlist[0].duration
                for n in nlist:
                    flat.remove(n)
                flat.insert(off, chord)

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
            _add_auto_clefs(part)
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
        _add_auto_clefs(combined_part)
        score.append(combined_part)

    _split_wide_range_part(score)
    _assign_stem_directions(score)
    _apply_repeats(score, note_events, pickup_shift, mid_shifts)
    return score


def _apply_repeats(score: m21.stream.Score, events: list, pickup_shift,
                   mid_shifts=None) -> None:
    """Insert repeat barlines and volta brackets from BAR/VOLTA events."""
    bar_evs   = [e for e in events if e.get('t') == 'BAR']
    volta_evs = [e for e in events if e.get('t') == 'VOLTA']
    if not bar_evs and not volta_evs:
        return
    if mid_shifts is None:
        mid_shifts = []

    def ev_q(ev) -> float:
        # BAR/VOLTA events mark measure boundaries, not note positions.
        # Apply mid_shifts only when onset is STRICTLY GREATER than the threshold
        # (at the threshold the event marks the start of the pickup bar, before
        # the pickup note itself; notes at the threshold get the full extra shift).
        base = float(_onset_frac(ev['on']))
        result = base + float(pickup_shift)
        for threshold_q, extra_q in mid_shifts:
            if base > float(threshold_q):
                result += float(extra_q)
        return result

    for part in score.parts:
        measures = list(part.getElementsByClass('Measure'))
        if not measures:
            continue

        def m_start(i):
            return float(measures[i].offset)

        def m_end(i):
            if i + 1 < len(measures):
                return float(measures[i + 1].offset)
            return float(measures[i].offset) + float(measures[i].barDuration.quarterLength)

        def find_start(q):
            for m in measures:
                if abs(float(m.offset) - q) < 0.1:
                    return m
            return None

        def find_ending(q):
            for i, m in enumerate(measures):
                if abs(m_end(i) - q) < 0.1:
                    return m
            return None

        # Start/end repeat barlines (from \repeat "volta" without \alternative)
        for ev in bar_evs:
            q = ev_q(ev)
            if ev['bar'] == 'start-repeat':
                m = find_start(q)
                if m and m.leftBarline is None:
                    m.leftBarline = m21bar.Repeat('start')
            elif ev['bar'] == 'end-repeat':
                m = find_ending(q)
                if m:
                    m.rightBarline = m21bar.Repeat('end')

        # Volta brackets
        volta_start_q: dict = {}
        for ev in sorted(volta_evs, key=ev_q):
            q = ev_q(ev)
            n = ev['n']
            if ev['volta-type'] == 'start':
                volta_start_q[n] = q
                if n == 1:
                    # End-repeat barline on last body measure
                    m = find_ending(q)
                    if m:
                        m.rightBarline = m21bar.Repeat('end')
                # Start-repeat barline on the body's first measure
                # (already emitted as BAR start-repeat, but handle here too)
                start_m = find_start(q)
                if start_m:
                    start_m.leftBarline = None  # remove any accidental barline
            elif ev['volta-type'] == 'stop':
                start_q = volta_start_q.pop(n, None)
                if start_q is None:
                    continue
                bracket_ms = [m for m in measures
                               if start_q - 0.05 <= float(m.offset) < q - 0.05]
                if bracket_ms:
                    part.insert(0, m21spanner.RepeatBracket(bracket_ms, number=n))


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

        # Split by SCORE markers — multi-score books get one file per movement
        score_groups = _split_by_score(events)

        # Parse human-readable titles from the source file
        global_title, pieces = _parse_ly_titles(ly)

        # Build MusicXML
        try:
            if len(score_groups) <= 1:
                targets = [(xml_out, events, 0)]
            else:
                targets = [
                    (xml_out.with_name(f'{stem}_{i + 1}.xml'), grp, i)
                    for i, grp in enumerate(score_groups)
                ]
            for out_path, evs, score_idx in targets:
                score = notes_to_score(evs)
                score.write('musicxml', str(out_path))
                pickup_shift, _ms, section_pickup_offsets = _compute_shifts(evs)
                if pickup_shift > 0 or section_pickup_offsets:
                    _postprocess_pickup_xml(str(out_path), float(pickup_shift),
                                            section_pickup_offsets)
                # Patch movement title
                piece = pieces[score_idx] if score_idx < len(pieces) else ''
                if global_title and piece:
                    xml_title = f'{global_title}, {piece}'
                elif global_title:
                    xml_title = global_title
                elif piece:
                    xml_title = piece
                else:
                    xml_title = stem.replace('_', ' ')
                _patch_xml_title(str(out_path), xml_title)
            n_parts = len(score.parts)
            suffix = f'  ({len(score_groups)} movements)' if len(score_groups) > 1 else ''
            print(f'  OK {stem}  notes={n_notes}  parts={n_parts}{suffix}')
            ok += 1
        except Exception as e:
            print(f'  ERROR xml {stem}: {e}')
            err += 1

    print(f'\nDone: {ok} ok, {err} errors, {skip} skipped')
    print(f'Output: {OUT_DIR}')


if __name__ == '__main__':
    main()

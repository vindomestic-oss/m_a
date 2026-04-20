import math
import re
import threading
import xml.etree.ElementTree as ET
from collections import defaultdict

_PITCH_CLASS   = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
_DIATONIC_STEP = {'c': 0, 'd': 1, 'e': 2, 'f': 3, 'g': 4, 'a': 5, 'b': 6}
_MOTIF_COLORS  = [
    '#e74c3c', '#2980b9', '#27ae60', '#e67e22',
    '#8e44ad', '#16a085', '#d81b60', '#f39c12',
]
_MEI_NS = 'http://www.music-encoding.org/ns/mei'
_XML_ID = '{http://www.w3.org/XML/1998/namespace}id'

# Predefined rhythmic vocab patterns — always searched and shown in the motif dict.
# Format: any valid /search query string (rhythm-only, interval, contour).
VOCAB_QUERIES: list[str] = [
    "(1/4)3/16,1/16;0",          # dotted rhythm: dotted-8th + 16th at quarter-beat start
    "(1/8)3/32,1/32;0",          # dotted rhythm: dotted-16th + 32nd at eighth-beat start
    "(1/4)1/16,3/16;0",          # reverse dotted rhythm
    "(1/8)1/32,3/32;0",          # reverse dotted rhythm

    "(1/4)3/16,1/32,1/32;0",     # dotted variant with 2 1/32
    "(1/4)1/16,1/16,1/8;0",
    "(1/8)1/32,1/32,1/16;0",

    "(1/4)1/16?,1/8,>=1/16;0",   # syncope: 8th on 2nd 16th of beat (opt. leading 16th)
    
    "(1/8)1/16;01_",             # attack-grid syncope: no attack at beat, attack at 1/16, held (not rest) at 2/16
    "(1/4)1/8;01_",              # same at quarter-beat scale: attack on 2nd 8th of quarter, held at next beat
    "(1/4)1/16;?0011",           # attacks on 3rd+4th 16th of beat (beat pos wildcard, silence at 2nd 16th)
]

# Per-file beat_dur_q overrides (filename substring → beat_dur_q in quarter notes).
# Use to force a specific metric feel when the time signature is ambiguous.
_BEAT_DUR_OVERRIDES: dict[str, float] = {
    'bwv_988_v27': 1.0,   # 6/8 felt as 2+2+2 (3 quarter beats), not 3+3
}


_DUR_NAMES = {
    4.0: '&#119133;', 3.0: '&#119134;.', 2.0: '&#119134;',
    1.5: '&#9833;.',  1.0: '&#9833;',    0.75: '&#9834;.',
    0.5: '&#9834;',   0.375: '&#9835;.', 0.25: '&#9835;',
}
_DIATONIC_NAMES = ['0', '1', '2', '3', '4', '5', '6']


def _dur_q_to_str(d):
    """Convert duration in quarter notes to a search-format fraction string.
    _parse_dur computes val = num * 4.0 / den, so the inverse is d/4 as a fraction.
    Examples: 0.25 → '1/16', 0.5 → '1/8', 1.0 → '1/4', 1.5 → '3/8'."""
    from fractions import Fraction
    f = Fraction(d / 4.0).limit_denominator(64)
    return f"{f.numerator}/{f.denominator}"


def _dur_q_label(d):
    """Fraction string in quarter-note units for display (e.g. 1/3 for triplet eighth)."""
    from fractions import Fraction
    f = Fraction(d).limit_denominator(100)
    return f"{f.numerator}/{f.denominator}"


def _pattern_to_query(pattern, phase):
    """Convert a motif pattern tuple ((interval, dur), ...) to a search query string."""
    durs = [_dur_q_to_str(p[1]) for p in pattern]
    dur_part = durs[0] if len(set(durs)) == 1 else ",".join(durs)
    iv_part  = "".join(f"+{iv}" if iv >= 0 else str(iv) for iv in (p[0] for p in pattern))
    return f"{dur_part};{phase};{iv_part}"


def _interval_label(dsteps, dur_q):
    """Human-readable label for one interval+duration step (diatonic)."""
    abs_d = abs(dsteps)
    octaves = abs_d // 7
    rem     = abs_d % 7
    iname = _DIATONIC_NAMES[rem] if rem < 7 else str(rem)
    if octaves:
        iname += f'+{octaves}о'
    arrow = '&uarr;' if dsteps > 0 else ('&darr;' if dsteps < 0 else '&mdash;')
    dname = _DUR_NAMES.get(dur_q, _dur_q_to_str(dur_q))
    return f'{arrow}{iname}<sub>{dname}</sub>'


def _to_midi(pname, oct_str, accid=None):
    base = _PITCH_CLASS.get(pname.lower(), 0) + (int(oct_str) + 1) * 12
    if accid == 's':    base += 1
    elif accid == 'f':  base -= 1
    elif accid == 'ss': base += 2
    elif accid == 'ff': base -= 2
    return base


def _to_quarters(dur_str, dots=0):
    """Duration in quarter notes, quantised to 16th-note grid."""
    try:
        base = 4.0 / float(dur_str)
    except (ValueError, ZeroDivisionError, TypeError):
        return 0.0
    total = base
    for _ in range(int(dots)):
        base /= 2
        total += base
    return round(total * 16) / 16


def _metric_phase(onset_q, dur_q, beat_dur_q=1.0):
    """
    Return the metric phase of a note within its beat.
    Phase = position of the note within the beat, counted in units of dur_q.
    beat_dur_q: beat duration in quarter notes (1.0 for 4/4, 1.5 for 9/8, 0.5 for 3/8).
    Examples:
      8th in 4/4  (beat=1.0): n_per_beat=2 → phase 0 or 1
      8th in 9/8  (beat=1.5): n_per_beat=3 → phase 0, 1, or 2
      triplet 1/3 in 4/4:     n_per_beat=3 → phase 0, 1, or 2
      triplet 1/6 in 4/4:     n_per_beat=6 → phase % 3 (0,1,2) — groups of 3
      16th in 12/8 (beat=1.5): n_per_beat=6 → kept at 6 (phase 0 = beat only)
      32nd in 3/4 (beat=1.0): n_per_beat=8 → capped to 4 → phase 0-3 (same as 16th)
    """
    if dur_q <= 0 or beat_dur_q <= 0:
        return 0
    n_per_beat = max(1, round(beat_dur_q / dur_q))
    if n_per_beat <= 1:
        return 0
    # Compound meter detection: beat_dur_q is a multiple of 3/4 (e.g. 1.5 for 6/8,9/8,12/8).
    # round(beat_dur_q * 4) divisible by 3 identifies compound beats (1.5→6, 0.75→3, etc.).
    is_compound = (round(beat_dur_q * 4) % 3 == 0)
    if n_per_beat % 3 == 0:
        if is_compound and n_per_beat >= 6:
            # Compound meter (e.g. 16th in 12/8): keep up to 6 phases so that
            # phase 0 only hits beat boundaries, not also dotted-eighth positions.
            n_per_beat = min(n_per_beat, 6)
        else:
            # Simple meter triplets (1/3, 1/6 …): collapse — "first of triplet group"
            # is the musically meaningful position, not beat start.
            n_per_beat = 3
    # Cap binary subdivisions at 4 phases (same resolution as 16th notes).
    # Prevents 32nd/64th notes from generating excessive phase slots.
    elif n_per_beat > 4:
        n_per_beat = 4
    pos_in_beat = onset_q % beat_dur_q
    raw = pos_in_beat / dur_q
    # Notes not on the regular note grid (pos/dur ≈ X.5, fractional part > 0.35)
    # get a sentinel value (n_per_beat) that never equals any valid phase [0..n-1].
    # This prevents off-grid notes (from ornament/tuplet passages) from accidentally
    # matching any phase in searches or motif grouping.
    if abs(raw - round(raw)) > 0.35:
        return n_per_beat
    phase = int(round(raw)) % n_per_beat
    return phase



def _voice_notes_from_mei(mei_str):
    """
    Parse MEI and return per-voice note lists.
    voice_key = (staff_n, layer_n)
    Returns {voice_key: [(xml_id, pname, oct_int, dur_quarters, midi, onset_quarters), ...]}
    onset_quarters: absolute time from piece start, computed from measure structure
    (tracks ALL events including rests/ties so onset is consistent across voices).
    """
    tree    = ET.fromstring(mei_str)
    tag_pfx = '{%s}' % _MEI_NS

    # Initial time signature from scoreDef.
    # verovio may encode it as attributes on <scoreDef> (meter.count/meter.unit)
    # or as a <meterSig count="..." unit="..."/> child inside <staffDef>.
    beats_per_measure = 4.0
    beat_dur_q = 1.0   # beat duration in quarter notes

    def _parse_meter(c, u):
        mc, mu = int(c), int(u)
        bpm = mc * 4.0 / mu
        # Compound meter (3/8, 6/8, 9/8, 12/8 …): beat = dotted note = 3 subdivisions
        # Simple meter: cap beat at quarter note so 2/2 doesn't give 8 phases for 1/16
        bdq = (4.0 / mu * 3) if (mc % 3 == 0 and mu >= 8) else min(4.0 / mu, 1.0)
        return bpm, bdq

    for sd in tree.iter(tag_pfx + 'scoreDef'):
        c = sd.get('meter.count'); u = sd.get('meter.unit')
        if not (c and u):
            for ms in sd.iter(tag_pfx + 'meterSig'):
                c = ms.get('count'); u = ms.get('unit')
                if c and u:
                    break
        if c and u:
            beats_per_measure, beat_dur_q = _parse_meter(c, u)
            break

    def proc_note(n, dur_override=None, dots_override=None, onset=0.0, scale=1.0, dur_q=None):
        nid   = n.get(_XML_ID)
        pname = n.get('pname', '')
        if not pname or not nid:
            return None
        tie = n.get('tie', '')
        if 'm' in tie or 't' in tie:   # skip tied continuation — but still counts time
            return None
        oct_str = n.get('oct', '4')
        if dur_q is not None:
            actual_dur = dur_q
        else:
            dur  = dur_override if dur_override is not None else n.get('dur', '4')
            dots = dots_override if dots_override is not None else int(n.get('dots', 0))
            actual_dur = _to_quarters(dur, dots) * scale
        accid   = n.get('accid') or n.get('accid.ges')
        return (nid, pname, int(oct_str), actual_dur,
                _to_midi(pname, oct_str, accid), onset)

    def iter_events(el, scale=1.0):
        """Yield (event_element, scale) pairs, recursing into beam/tuplet containers.
        Tuplet ratio num/numbase is applied as a multiplier to note durations."""
        for child in el:
            t = child.tag.split('}')[-1]
            if t == 'tuplet':
                num     = int(child.get('num', 1))
                numbase = int(child.get('numbase', 1))
                yield from iter_events(child, scale * numbase / num)
            elif t in ('beam', 'ligature', 'ftrem', 'btrem'):
                yield from iter_events(child, scale)
            else:
                yield child, scale

    # Base PPQ for MusicXML-sourced MEI: verovio sets dur.ppq on every note/rest with
    # the actual performed duration in MIDI ticks.  When verovio omits <tuplet> wrappers
    # for some measures (a known verovio quirk), dur and dots stay at the nominal value
    # (e.g. dur='8' for a triplet eighth) but dur.ppq correctly reflects the real duration.
    # kern-sourced MEI has no dur.ppq at all; _base_ppq stays None and the existing
    # _to_quarters(dur, dots)*scale path is used unchanged.
    #
    # MusicXML files can have mid-piece <divisions> changes, which cause verovio to reset
    # its PPQ tick scale.  Pre-scan in document order: whenever a plain quarter note is
    # seen, record the new base; store a per-element base in _elem_base so that
    # _elem_dur_q always uses the correct local scale.
    _base_ppq  = None   # first base seen (for fallback)
    _elem_base = {}     # id(el) -> base_ppq effective at that element
    _scan_base = None
    import math as _math
    # Detect PPQ base (= quarter-note duration in verovio's tick unit).
    # Strategy: collect implied bases from all non-dotted notes, weighted by
    # reliability: dur=4/8/16/32 are always exact multiples of base; dur=1/2 in
    # compound meters get ppq = odd multiple of base (3×, 6×, …) so they are
    # unreliable.  Pick the most-frequent implied base from reliable notes; fall
    # back to whole/half only if no reliable notes exist.
    _base_candidates = {}  # implied_base -> count
    for _el in tree.iter():
        _ppq = _el.get('dur.ppq')
        if _ppq is None:
            continue
        _dur_tag = _el.get('dur')
        _dots    = int(_el.get('dots', 0) or 0)
        if _dots:
            continue
        _raw = int(_ppq)
        if _dur_tag == '4' and _raw > 0:
            _base_candidates[_raw] = _base_candidates.get(_raw, 0) + 4  # high weight
        elif _dur_tag == '8' and _raw > 0:
            _base_candidates[_raw * 2] = _base_candidates.get(_raw * 2, 0) + 2
        elif _dur_tag == '16' and _raw > 0:
            _base_candidates[_raw * 4] = _base_candidates.get(_raw * 4, 0) + 1
        elif _dur_tag == '32' and _raw > 0:
            _base_candidates[_raw * 8] = _base_candidates.get(_raw * 8, 0) + 1
    if _base_candidates:
        _scan_base = max(_base_candidates, key=_base_candidates.get)
    else:
        # Last resort: whole or half.
        for _el in tree.iter():
            _ppq = _el.get('dur.ppq')
            if _ppq is None:
                continue
            _dur_tag = _el.get('dur')
            _dots    = int(_el.get('dots', 0) or 0)
            if not _dots and _dur_tag in ('1', '2'):
                _factor = {'1': 4, '2': 2}[_dur_tag]
                _raw    = int(_ppq)
                if _raw > 0 and _raw % _factor == 0:
                    _scan_base = _raw // _factor
                    break
    _base_ppq = _scan_base
    # Full pass to assign per-element bases and track mid-piece divisions changes.
    _scan_base2 = _scan_base
    for _el in tree.iter():
        _ppq = _el.get('dur.ppq')
        if _ppq is not None:
            _dur_tag = _el.get('dur')
            _dots    = int(_el.get('dots', 0) or 0)
            if not _dots and _dur_tag == '4' and _scan_base2 is not None:
                _new = int(_ppq)
                if _new != _scan_base2 and _new > 0:
                    _ratio = _new / _scan_base2
                    _log2  = _math.log2(_ratio) if _ratio > 0 else float('nan')
                    if abs(_log2 - round(_log2)) < 0.01:  # power-of-2 → legit change
                        _scan_base2 = _new
        _elem_base[id(_el)] = _scan_base2

    def _elem_dur_q(el, scale):
        """Duration in quarters: prefer dur.ppq/local_base, fall back to dur+dots+scale."""
        ppq = el.get('dur.ppq')
        if ppq:
            local_base = _elem_base.get(id(el)) or _base_ppq
            if local_base:
                return int(ppq) / local_base
        return _to_quarters(el.get('dur', '4'), int(el.get('dots', 0))) * scale

    voices           = defaultdict(list)
    measure_onset    = 0.0
    pickup_dur_q     = 0.0
    _first_measure   = True
    rpt_section_start = 0.0   # onset where current repeat section started
    _rpt_active       = False  # True after a rptstart has been seen
    repeat_ranges    = []     # list of (start_onset, end_onset) for single-play repeats
    _measure_starts  = {}     # measure xml:id -> onset at start (for volta detection)
    _measure_ends    = {}     # measure xml:id -> onset at end

    for measure_el in tree.iter(tag_pfx + 'measure'):
        # Pick up meter changes inside the measure
        for ms in measure_el.iter(tag_pfx + 'meterSig'):
            c = ms.get('count'); u = ms.get('unit')
            if c and u:
                beats_per_measure, beat_dur_q = _parse_meter(c, u)
                break

        max_pos = 0.0   # actual measure duration (for pickup bar detection)
        for staff_el in measure_el.findall(tag_pfx + 'staff'):
            sn = int(staff_el.get('n', 1))
            for layer_el in staff_el.findall(tag_pfx + 'layer'):
                ln  = int(layer_el.get('n', 1))
                key = (sn, ln)
                pos = 0.0   # position within measure
                pos_real = 0.0  # pos excluding mRest (for pickup detection)

                for child, scale in iter_events(layer_el):
                    t = child.tag.split('}')[-1]
                    onset = measure_onset + pos
                    if t == 'note':
                        dur = _elem_dur_q(child, scale)
                        if child.get('grace'):   # grace note (q/Q in kern) — skip, no pos advance
                            pass
                        else:
                            e = proc_note(child, onset=onset, scale=scale, dur_q=dur)
                            if e:
                                voices[key].append(e)
                            pos += dur
                            pos_real = pos
                    elif t == 'chord':
                        dur = _elem_dur_q(child, scale)
                        if child.get('grace'):   # grace chord — skip
                            pass
                        else:
                            cands = [proc_note(n,
                                               dur_override=child.get('dur', '4'),
                                               dots_override=int(child.get('dots', 0)),
                                               onset=onset, scale=scale, dur_q=dur)
                                     for n in child.findall(tag_pfx + 'note')]
                            cands = [c for c in cands if c]
                            if cands:
                                voices[key].append(max(cands, key=lambda x: x[4]))
                            pos += dur
                            pos_real = pos
                    elif t in ('rest', 'space'):
                        dur = _elem_dur_q(child, scale)
                        pos += dur
                        pos_real = pos
                    elif t == 'mRest':
                        pos += beats_per_measure
                        # pos_real NOT updated: mRest must not inflate pickup detection

                max_pos = max(max_pos, pos_real)

        # Pickup bar (anacrusis): use actual notes duration when:
        # 1. verovio explicitly marks metcon='false' (kern pickup bars), OR
        # 2. actual note content < full measure (MusicXML implicit measures where
        #    verovio doesn't set metcon; mRest filler voices are excluded via pos_real)
        # Cap at beats_per_measure: MusicXML cross-measure tied chords can produce
        # max_pos > beats_per_measure with metcon='false' — those are NOT short measures.
        # Exception: when actual content greatly exceeds the time-sig measure length
        # (wrong time signature in source MusicXML, e.g. 3/8 for a 4/4 piece),
        # advance by actual content so voices stay in sync.
        _overfull = max_pos > beats_per_measure * 1.5 + 1e-9
        if _overfull:
            eff_pos = max_pos
        else:
            eff_pos = min(max_pos, beats_per_measure)
        onset_before_update = measure_onset
        _m_id = measure_el.get(_XML_ID, '')
        if _m_id:
            _measure_starts[_m_id] = onset_before_update
        if eff_pos > 0 and (measure_el.get('metcon') == 'false' or
                            eff_pos < beats_per_measure - 1e-9 or
                            _overfull):
            if _first_measure and not _overfull:
                pickup_dur_q = eff_pos
            measure_onset += eff_pos
        else:
            measure_onset += beats_per_measure
        if _m_id:
            _measure_ends[_m_id] = measure_onset
        _first_measure = False
        # Detect repeat barlines for section-repeat tracking
        _left  = measure_el.get('left', '')
        _right = measure_el.get('right', '')
        if _left == 'rptstart':
            rpt_section_start = onset_before_update
            _rpt_active = True
        if _right == 'rptend':
            repeat_ranges.append((rpt_section_start, measure_onset))
            rpt_section_start = measure_onset
            _rpt_active = False
        elif _right == 'dblheavy':
            # Verovio merges a backward+forward repeat pair into a single dblheavy
            # barline — always means two independent repeat sections (||:A:||||:B:||).
            # Split here so both sections are tracked as separate ranges → no unfolding.
            # Note: no _rpt_active guard — the first section may start implicitly
            # (no explicit rptstart at the beginning of the piece).
            repeat_ranges.append((rpt_section_start, measure_onset))
            rpt_section_start = measure_onset
            _rpt_active = True

    # Merge tied notes from <tie> elements (MusicXML-sourced MEI).
    # kern-sourced MEI uses tie="i/m/t" attributes (handled in proc_note);
    # MusicXML-sourced MEI uses standalone <tie startid=... endid=...> elements.
    tie_start_to_end = {}
    for el in tree.iter(tag_pfx + 'tie'):
        sid = el.get('startid', '').lstrip('#')
        eid = el.get('endid',   '').lstrip('#')
        if sid and eid:
            tie_start_to_end[sid] = eid
    if tie_start_to_end:
        for key in list(voices):
            notes = voices[key]
            id_to_idx = {n[0]: i for i, n in enumerate(notes)}
            to_remove = set()
            new_notes = list(notes)
            for i, note in enumerate(notes):
                nid = note[0]
                if nid in tie_start_to_end:
                    extra_dur = 0.0
                    cur = nid
                    _visited = {cur}
                    while cur in tie_start_to_end:
                        eid = tie_start_to_end[cur]
                        if eid in _visited:   # self-loop or cycle → stop
                            break
                        _visited.add(eid)
                        if eid in id_to_idx:
                            j = id_to_idx[eid]
                            extra_dur += notes[j][3]
                            to_remove.add(j)
                            cur = eid
                        else:
                            break
                    if extra_dur > 0:
                        n = new_notes[i]
                        new_notes[i] = (n[0], n[1], n[2], n[3] + extra_dur, n[4], n[5])
            voices[key] = [n for i, n in enumerate(new_notes) if i not in to_remove]

    # Build slur/phrase map: startid → endid
    # verovio writes kern ( ) as <slur> or <phrase> elements (not inline attributes)
    slur_ends = {}
    for tag in ('slur', 'phrase'):
        for el in tree.iter(tag_pfx + tag):
            sid = el.get('startid', '').lstrip('#')
            eid = el.get('endid',   '').lstrip('#')
            if sid and eid:
                slur_ends[sid] = eid

    # Merge ornamental 2-note slur pairs per voice
    # Only applies to kern-sourced MEI — MusicXML slurs are phrase markings, not ornaments
    result = {}
    for key, notes in voices.items():
        if _base_ppq is None:
            result[key] = _merge_ornamental_slurs(notes, slur_ends)
        else:
            result[key] = notes

    # ── Detect volta (1st/2nd ending) groups ────────────────────────────────────
    # Requires <expansion plist> with pattern: ... body A1 body A2 ...
    # where A1 is ending n=1 and A2 is ending n=2.
    volta_groups = []
    try:
        exp_el = None
        for _exp in tree.iter(tag_pfx + 'expansion'):
            if _exp.get('type', '') != 'norep':
                exp_el = _exp
                break
        if exp_el is not None and _measure_starts:
            _plist = [x.lstrip('#') for x in exp_el.get('plist', '').split()]
            # Collect ending n values by xml:id
            _ending_n = {}
            for _el in tree.iter(tag_pfx + 'ending'):
                _eid = _el.get(_XML_ID, '')
                if _eid:
                    _ending_n[_eid] = _el.get('n', '').strip().rstrip('.')
            # Compute onset range for each section/ending by its direct-child measures
            _sec_range = {}
            for _tag in ('section', 'ending'):
                for _el in tree.iter(tag_pfx + _tag):
                    _eid = _el.get(_XML_ID, '')
                    _ms  = [c for c in _el if c.tag == tag_pfx + 'measure']
                    if _eid and _ms:
                        _s = _measure_starts.get(_ms[0].get(_XML_ID, ''))
                        _e = _measure_ends.get(_ms[-1].get(_XML_ID, ''))
                        if _s is not None and _e is not None:
                            _sec_range[_eid] = (_s, _e)
            # Scan plist for pattern: body volta1 body volta2
            _n = len(_plist)
            _i = 0
            while _i <= _n - 4:
                _a, _b, _c, _d = _plist[_i], _plist[_i+1], _plist[_i+2], _plist[_i+3]
                if (_a == _c
                        and _b in _ending_n and _d in _ending_n
                        and _ending_n[_b] == '1' and _ending_n[_d] == '2'
                        and _a in _sec_range and _b in _sec_range and _d in _sec_range):
                    volta_groups.append({
                        'body':   _sec_range[_a],
                        'volta1': _sec_range[_b],
                        'volta2': _sec_range[_d],
                    })
                    _i += 4
                else:
                    _i += 1
    except Exception:
        pass

    return result, beat_dur_q, pickup_dur_q, repeat_ranges, volta_groups


def _merge_ornamental_slurs(notes, slur_ends):
    """
    Detect 2-note slur pairs where note[i] starts a slur that ends at note[i+1],
    and note[i] is strictly shorter (ornament/appoggiatura).
    The ornament note is dropped; its duration is added to the main note;
    onset of the merged note = onset of the ornament (start of the figure).
    """
    merged = []
    i = 0
    while i < len(notes):
        if i + 1 < len(notes):
            a, b = notes[i], notes[i + 1]
            if slur_ends.get(a[0]) == b[0] and a[3] < b[3]:
                # a is ornament: absorb into b
                merged.append((b[0], b[1], b[2], a[3] + b[3], b[4], a[5]))
                i += 2
                continue
        merged.append(notes[i])
        i += 1
    return merged


def _remove_unison_voices(voices_dict):
    """
    Detect voices that double each other in unison (same MIDI pitch at same onset).
    Removes notes from the duplicate voice for each unison segment so it does not
    produce artifact motifs with a small time shift.

    A pair of voices is considered "unison" in a segment when:
      - They share ≥4 consecutive notes with identical MIDI pitch at identical onset
        (quantised to 1/16), with no gap > 4 sixteenths between consecutive shared notes
      - Alternatively the pair is globally unison: ≥80 % of the shorter voice's notes
        match the other voice — then all matching notes are suppressed

    The voice with the higher staff number loses its notes in those segments.
    Unison detection runs on the original (pre-repeat-unfolding) voice dict.
    """
    vkeys = list(voices_dict.keys())
    if len(vkeys) < 2:
        return voices_dict

    def _q16(onset):
        return round(onset * 16)

    voice_idx = {}   # vk -> {q16_onset: note}
    for vk, notes in voices_dict.items():
        voice_idx[vk] = {_q16(n[5]): n for n in notes}

    suppress = {vk: set() for vk in vkeys}  # vk -> set of note-ids to drop

    for i in range(len(vkeys)):
        for j in range(i + 1, len(vkeys)):
            vk_a, vk_b = vkeys[i], vkeys[j]
            idx_a = voice_idx[vk_a]
            idx_b = voice_idx[vk_b]

            shared_q16 = sorted(
                q for q in idx_a
                if q in idx_b and idx_a[q][4] == idx_b[q][4]
            )
            if len(shared_q16) < 4:
                continue

            shorter = min(len(idx_a), len(idx_b))

            # Case A: globally unison (≥80 % of shorter voice matches)
            if len(shared_q16) >= 0.8 * shorter:
                sn_a, sn_b = vk_a[0], vk_b[0]
                vk_drop  = vk_b if sn_a <= sn_b else vk_a
                idx_drop = voice_idx[vk_drop]
                for q in shared_q16:
                    n = idx_drop.get(q)
                    if n:
                        suppress[vk_drop].add(n[0])
                continue

            # Case B: local unison runs — gap ≤ 4 sixteenths between consecutive shared notes
            runs = []
            run = [shared_q16[0]]
            for k in range(1, len(shared_q16)):
                prev, cur = shared_q16[k - 1], shared_q16[k]
                if cur - prev <= 4:
                    run.append(cur)
                else:
                    if len(run) >= 4:
                        runs.append(run)
                    run = [cur]
            if len(run) >= 4:
                runs.append(run)

            if not runs:
                continue

            sn_a, sn_b = vk_a[0], vk_b[0]
            vk_drop  = vk_b if sn_a <= sn_b else vk_a
            idx_drop = voice_idx[vk_drop]
            for run in runs:
                for q in run:
                    n = idx_drop.get(q)
                    if n:
                        suppress[vk_drop].add(n[0])

    if not any(suppress.values()):
        return voices_dict

    result = {}
    for vk, notes in voices_dict.items():
        drop = suppress[vk]
        result[vk] = [n for n in notes if n[0] not in drop]
    return result


def _interval_seq(notes, beat_dur_q=1.0, pickup_dur_q=0.0):
    """
    notes: [(nid, pname, oct, dur, midi, onset), ...]
    Returns [(diatonic_interval, dur_of_first_note, nid_first, nid_second, onset_quarters, phase,
              contiguous, dp0), ...]
    dp0: absolute diatonic pitch of the first note (oct*7 + step) — used for transposition tracking.
    pickup_dur_q: duration of the anacrusis measure (0 if none); subtracted from onset before
    computing metric phase so beat 1 of measure 1 always has phase 0.
    """
    result = []
    for i in range(len(notes) - 1):
        nid0, pname0, oct0, dur0, _, onset0 = notes[i]
        nid1, pname1, oct1, _,   _, onset1  = notes[i + 1]
        dp0 = oct0 * 7 + _DIATONIC_STEP.get(pname0.lower(), 0)
        dp1 = oct1 * 7 + _DIATONIC_STEP.get(pname1.lower(), 0)
        phase0 = _metric_phase(onset0 - pickup_dur_q, dur0, beat_dur_q)
        contiguous = round((onset0 + dur0) * 16) == round(onset1 * 16)
        result.append((dp1 - dp0, dur0, nid0, nid1, onset0, phase0, contiguous, dp0))
    return result


def _find_motifs(all_seqs, min_len=2, min_count=2, max_motifs=50, max_pat_len=None,
                 beat_dur_q=1.0, pickup_dur_q=0.0, all_seqs_full=None):
    """
    all_seqs: [(voice_key, interval_seq), ...]  — used for pattern discovery (may be capped)
    all_seqs_full: if given, re-count occurrences on full sequences after discovery
    Returns list of {'pattern': tuple, 'occurrences': [[nid, ...], ...]}

    Pattern key = (body, start_phase) where:
      - body = tuple of (interval, dur) pairs — rhythm+pitch content
      - start_phase = metric phase of the first note, measured in units of the
        *minimum* note duration in the body (same unit as _search_motif uses)
    Two occurrences of the same body at different metric phases are treated as distinct motifs.
    Window-shift and sub-pattern dominance deduplication operate on body only.
    """
    # Step 1: collect raw positions per (body, start_phase) key per voice
    pat_voice_raw = defaultdict(lambda: defaultdict(list))
    for vi, (_vk, seq) in enumerate(all_seqs):
        n = len(seq)
        if n < min_len:
            continue
        for start in range(n):
            onset0    = seq[start][4]
            dp0_first = seq[start][7]
            max_ln = (n - start) if max_pat_len is None else min(max_pat_len, n - start)
            for ln in range(min_len, max_ln + 1):
                if not all(seq[start + k][6] for k in range(ln)):
                    break
                body = tuple((s[0], s[1]) for s in seq[start:start + ln])
                # Phase uses min body duration as unit — same as _search_motif
                min_body_dur = min(s[1] for s in seq[start:start + ln])
                start_phase  = _metric_phase(onset0 - pickup_dur_q, min_body_dur, beat_dur_q)
                key  = (body, start_phase)
                nids = [seq[start][2]] + [seq[start + k][3] for k in range(ln)]
                pat_voice_raw[key][vi].append((start, nids, onset0, dp0_first))

    # Step 2: interleaved per-voice greedy + cross-voice dedup in one pass.
    # last_end_v advances whenever an occurrence is consumed (kept OR cross-deduped),
    # so the same voice cannot produce a second occurrence sharing notes with any kept one.
    pat_occs = defaultdict(list)   # key -> [(nids, dp0_first, onset_q), ...]
    for (body, phase), voice_dict in pat_voice_raw.items():
        ln = len(body)
        all_cands = []
        for vi, positions in voice_dict.items():
            for start, nids, onset, dp0_first in positions:
                all_cands.append((round(onset * 16), start, vi, nids, dp0_first))
        all_cands.sort(key=lambda x: (x[0], x[2]))  # onset_q, then voice index
        last_end_v = {}
        seen_oq = set()
        for onset_q, start, vi, nids, dp0_first in all_cands:
            if start < last_end_v.get(vi, -1):
                continue  # overlaps previous kept occurrence in same voice
            if onset_q in seen_oq:
                last_end_v[vi] = start + ln + 1  # block this voice even though cross-deduped
                continue
            pat_occs[(body, phase)].append((nids, dp0_first, onset_q))
            seen_oq.add(onset_q)
            last_end_v[vi] = start + ln + 1

    # Step 3: merge inversions — same interleaved greedy+dedup, joint over direct+inverted.
    # Prefer direct over inverted at the same onset (sort is_inv=False before True).
    absorbed = set()
    for key in list(pat_occs.keys()):
        body, phase = key
        if key in absorbed:
            continue
        body_inv = tuple((-iv, dur) for iv, dur in body)
        if body_inv == body:
            continue
        inv_key = (body_inv, phase)
        if inv_key in pat_occs and inv_key not in absorbed:
            ln = len(body)
            all_voices = set(pat_voice_raw[key].keys()) | set(pat_voice_raw[inv_key].keys())
            all_cands = []
            for vi in all_voices:
                for start, nids, onset, dp0_first in pat_voice_raw[key].get(vi, []):
                    all_cands.append((round(onset * 16), start, vi, nids, dp0_first, False))
                for start, nids, onset, dp0_first in pat_voice_raw[inv_key].get(vi, []):
                    all_cands.append((round(onset * 16), start, vi, nids, dp0_first, True))
            # Whichever form appears first in the piece is "direct".
            min_oq_d = min((c[0] for c in all_cands if not c[5]), default=float('inf'))
            min_oq_i = min((c[0] for c in all_cands if c[5]),     default=float('inf'))
            if min_oq_i < min_oq_d:
                all_cands = [(oq, st, vi, nids, dp0, not inv) for oq, st, vi, nids, dp0, inv in all_cands]
                result_key = inv_key
                absorbed.add(key)
            else:
                result_key = key
                absorbed.add(inv_key)
            # Sort: onset_q, then direct before inverted, then voice
            all_cands.sort(key=lambda x: (x[0], x[5], x[2]))
            last_end_v = {}
            seen_oq = set()
            merged = []
            for onset_q, start, vi, nids, dp0_first, is_inv in all_cands:
                if start < last_end_v.get(vi, -1):
                    continue
                if onset_q in seen_oq:
                    last_end_v[vi] = start + ln + 1
                    continue
                merged.append((nids, dp0_first, is_inv, onset_q))
                seen_oq.add(onset_q)
                last_end_v[vi] = start + ln + 1
            pat_occs[result_key] = merged

    # Normalize non-merged entries to 4-tuples
    for key in pat_occs:
        if key not in absorbed and pat_occs[key] and len(pat_occs[key][0]) == 3:
            pat_occs[key] = [(n, d, False, oq) for n, d, oq in pat_occs[key]]

    candidates = [
        (key, occs) for key, occs in pat_occs.items()
        if key not in absorbed and len(occs) >= min_count
        and not all(iv == 0 for iv, _dur in key[0])
    ]
    # sort key uses total occurrence count (len) and body length
    if not candidates:
        return []

    # Sort: count desc, length desc, phase asc (prefer earlier metric position), body for stability
    candidates.sort(key=lambda x: (len(x[1]), len(x[0][0]), -x[0][1], x[0][0]), reverse=True)

    def _is_window_shift(p, q):
        """Cyclic rotation: p shifted by k (wrapping) becomes q."""
        if len(p) != len(q):
            return False
        return any(p[k:] + p[:k] == q for k in range(1, len(p)))

    def _linear_window_dominated(long_body, long_oqs16, short_body, short_oqs16):
        """Return True if short is a sliding-window fragment of long (or same length shifted).
        long must have count >= count of short (longer or equal pattern chosen as representative).
        Checks both directions: long starts before short (k>0) and short starts before long (k<0).
        Overlap must be >= max(2, min(Llong, Lshort)//2) intervals.
        Onset confirmation: short_oqs16 mostly aligns with long_oqs16 shifted by k notes.
        """
        Ll, Ls = len(long_body), len(short_body)
        min_overlap = max(2, min(Ll, Ls) // 2)
        occ_match = max(2, len(short_oqs16) * 2 // 3)
        # Direction 1: long starts k notes before short
        for k in range(1, Ll - min_overlap + 1):
            overlap = min(Ll - k, Ls)
            if overlap < min_overlap:
                break
            if long_body[k:k + overlap] == short_body[:overlap]:
                shift16 = round(sum(long_body[i][1] for i in range(k)) * 16)
                if len(short_oqs16 & {oq + shift16 for oq in long_oqs16}) >= occ_match:
                    return True
        # Direction 2: short starts k notes before long (only equal-length, or short longer —
        # but we only call with Ll >= Ls so this handles equal-length reverse shifts)
        if Ll == Ls:
            for k in range(1, Ls - min_overlap + 1):
                if short_body[k:] == long_body[:Ls - k]:
                    shift16 = round(sum(short_body[i][1] for i in range(k)) * 16)
                    if len(long_oqs16 & {oq + shift16 for oq in short_oqs16}) >= occ_match:
                        return True
        return False

    # Pre-pass: mark linear-window-shift duplicates suppressed by their longest same-count parent.
    # For each candidate with count C, check if a longer candidate with count C' >= C is its
    # sliding-window parent. The longer pattern is the representative; shorter ones are suppressed.
    cand_oqs16 = [{oq for *_, oq in occs} for _, occs in candidates]
    window_suppressed = [False] * len(candidates)
    for i, ((body_i, phase_i), occs_i) in enumerate(candidates):
        if window_suppressed[i]:
            continue
        cnt_i = len(occs_i)
        for j in range(i + 1, len(candidates)):
            if window_suppressed[j]:
                continue
            (body_j, _phase_j), occs_j = candidates[j]
            cnt_j = len(occs_j)
            if cnt_j > cnt_i:
                continue  # j appears more often — can't be suppressed by i
            Li, Lj = len(body_i), len(body_j)
            if Li < Lj:
                continue  # i is shorter than j; can't be j's parent
            if _linear_window_dominated(body_i, cand_oqs16[i], body_j, cand_oqs16[j]):
                window_suppressed[j] = True

    selected        = []
    selected_bodies = []
    for ci, ((body, phase), occs) in enumerate(candidates):
        if len(selected) >= max_motifs:
            break
        if window_suppressed[ci]:
            continue
        body_oqs16 = cand_oqs16[ci]
        dominated = any(
            (len(sb) > len(body) and
             any(sb[i:i + len(body)] == body for i in range(len(sb) - len(body) + 1)))
            or _is_window_shift(sb, body)
            for sb in selected_bodies
        )
        if not dominated:
            # compute three onset groups: direct-only, inv-only, coinciding
            direct_oqs = {oq for _n, _d, inv, oq in occs if not inv}
            inv_oqs    = {oq for _n, _d, inv, oq in occs if inv}
            n_direct_only = len(direct_oqs - inv_oqs)
            n_inv_only    = len(inv_oqs - direct_oqs)
            n_both        = len(direct_oqs & inv_oqs)
            # deduplicate: sort by (onset_q, is_inv) so direct beats inverse at same onset
            occs_sorted = sorted(occs, key=lambda x: (x[3], x[2]))
            ref_pitch = next((dp for _n, dp, inv, _oq in occs_sorted if not inv), None)
            if ref_pitch is None:
                ref_pitch = occs_sorted[0][1]
            seen_oq = set()
            dedup_occs = []
            transforms = []
            for nids, dp, inv, oq in occs_sorted:
                if oq not in seen_oq:
                    dedup_occs.append(nids)
                    transforms.append({
                        'transposition': dp - ref_pitch,
                        'inversion':     inv,
                        'onset_q':       oq,
                    })
                    seen_oq.add(oq)
            selected.append({
                'pattern':        body,
                'occurrences':    dedup_occs,
                'transforms':     transforms,
                'phase':          phase,
                'n_direct_only':  n_direct_only,
                'n_inv_only':     n_inv_only,
                'n_both':         n_both,
            })
            selected_bodies.append(body)

    # Re-count on full sequences if provided (discovery ran on capped seqs).
    # Targeted linear scan — O(n×L) per pattern, not O(n²).
    if all_seqs_full is not None and selected:
        needed_bodies = set()
        for m in selected:
            needed_bodies.add(m['pattern'])
            if m['n_inv_only'] > 0 or m['n_both'] > 0:
                needed_bodies.add(tuple((-iv, dur) for iv, dur in m['pattern']))
        bodies_by_len = defaultdict(set)
        for b in needed_bodies:
            bodies_by_len[len(b)].add(b)
        full_raw = defaultdict(lambda: defaultdict(list))
        for vi, (_vk, seq) in enumerate(all_seqs_full):
            n = len(seq)
            for start in range(n):
                onset0    = seq[start][4]
                dp0_first = seq[start][7]
                for L, bodies_L in bodies_by_len.items():
                    if start + L > n:
                        continue
                    if not all(seq[start + k][6] for k in range(L)):
                        continue
                    b = tuple((s[0], s[1]) for s in seq[start:start + L])
                    if b not in bodies_L:
                        continue
                    min_body_dur = min(s[1] for s in seq[start:start + L])
                    sp = _metric_phase(onset0 - pickup_dur_q, min_body_dur, beat_dur_q)
                    nids = [seq[start][2]] + [seq[start + k][3] for k in range(L)]
                    full_raw[(b, sp)][vi].append((start, nids, onset0, dp0_first))

        for m in selected:
            body = m['pattern']; phase = m['phase']
            key = (body, phase)
            inv_body = tuple((-iv, dur) for iv, dur in body)
            inv_key  = (inv_body, phase)
            has_inv  = inv_key in full_raw
            ln = len(body)
            all_voices = set(full_raw[key].keys()) | (set(full_raw[inv_key].keys()) if has_inv else set())
            all_cands = []
            for vi in all_voices:
                for start, nids, onset, dp0_first in full_raw[key].get(vi, []):
                    all_cands.append((round(onset * 16), start, vi, nids, dp0_first, False))
                if has_inv:
                    for start, nids, onset, dp0_first in full_raw[inv_key].get(vi, []):
                        all_cands.append((round(onset * 16), start, vi, nids, dp0_first, True))
            all_cands.sort(key=lambda x: (x[0], x[5], x[2]))
            last_end_v = {}; seen_oq = set(); merged = []
            for onset_q, start, vi, nids, dp0_first, is_inv in all_cands:
                if start < last_end_v.get(vi, -1):
                    continue
                if onset_q in seen_oq:
                    last_end_v[vi] = start + ln + 1
                    continue
                merged.append((nids, dp0_first, is_inv, onset_q))
                seen_oq.add(onset_q)
                last_end_v[vi] = start + ln + 1
            if not merged:
                continue
            direct_oqs = {oq for _n, _d, inv, oq in merged if not inv}
            inv_oqs    = {oq for _n, _d, inv, oq in merged if inv}
            m['n_direct_only'] = len(direct_oqs - inv_oqs)
            m['n_inv_only']    = len(inv_oqs - direct_oqs)
            m['n_both']        = len(direct_oqs & inv_oqs)
            occs_sorted = sorted(merged, key=lambda x: (x[3], x[2]))
            ref_pitch = next((dp for _n, dp, inv, _oq in occs_sorted if not inv), None)
            if ref_pitch is None:
                ref_pitch = occs_sorted[0][1]
            seen_oq = set(); dedup_occs = []; transforms = []
            for nids, dp, inv, oq in occs_sorted:
                if oq not in seen_oq:
                    dedup_occs.append(nids)
                    transforms.append({'transposition': dp - ref_pitch, 'inversion': inv, 'onset_q': oq})
                    seen_oq.add(oq)
            m['occurrences'] = dedup_occs
            m['transforms']  = transforms

    return selected


def _get_note_beat_positions(mei_str):
    """
    Returns {nid: label} where label is the note's position within its measure
    (in quarter notes, quantised to 16ths) as a string — for debug overlay.
    """
    tree = ET.fromstring(mei_str)
    tag_pfx = '{%s}' % _MEI_NS
    bpm = 4.0
    for sd in tree.iter(tag_pfx + 'scoreDef'):
        c = sd.get('meter.count'); u = sd.get('meter.unit')
        if c and u:
            bpm = int(c) * 4.0 / int(u)
            break
    voices, _bdq, _pdq, _rr, _vg = _voice_notes_from_mei(mei_str)
    labels = {}
    for _vk, notes in voices.items():
        for nid, _pname, _oct, dur, _midi, onset in notes:
            pos = round((onset % bpm) * 16) / 16
            phase = _metric_phase(onset - _pdq, dur, _bdq)
            labels[nid] = f'{pos:g}|{phase}'
    return labels


def _parse_dur(s):
    """
    Parse a duration string like '1/16', '>1/8', '<=3/8' to (op, quarter_float).
    op is one of '=', '>', '<', '>=', '<='.
    """
    s = s.strip()
    op = '='
    for prefix in ('>=', '<=', '>', '<'):
        if s.startswith(prefix):
            op = prefix
            s = s[len(prefix):]
            break
    if '/' in s:
        num, den = s.split('/', 1)
        val = float(num) * 4.0 / float(den)
    else:
        val = float(s)
    return (op, val)


def _dur_matches(actual, spec):
    op, val = spec
    if op == '=':  return abs(actual - val) < 1e-9
    if op == '>':  return actual > val + 1e-9
    if op == '<':  return actual < val - 1e-9
    if op == '>=': return actual >= val - 1e-9
    if op == '<=': return actual <= val + 1e-9
    return False


def _search_attack_grid(cell_q, subdiv_q, pattern, seqs, pickup_dur_q, search_rpt_info):
    """
    Attack-grid search: pattern string aligned to repeating cells.
    cell_q    = cell duration in quarter notes (e.g. 0.5 for 1/8-cell).
    subdiv_q  = slot duration in quarter notes (e.g. 0.25 for 1/16-slots).
    pattern   = string of '0'/'1'/'_':
        '1' = note attack required at this slot
        '0' = no attack (rest OR held note — either is fine)
        '_' = no attack AND the most-recently-attacked note in the pattern must still
              be ringing (its duration reaches past this slot); rejects rests
    Slots beyond ceil(cell_q/subdiv_q) are look-ahead into the next cell;
    they constrain but do NOT block the greedy advance (next cell starts at +cell_q).
    Returns {"occs": [[nid,...], ...], "count": N, ...}.
    """
    attack_ks = [k for k, ch in enumerate(pattern) if ch == '1']
    if not attack_ks:
        return {"occs": [], "count": 0, "repeat_pairs": [], "is_inv": [], "is_volta": False}

    all_cands = []   # (onset_q16, vi_idx, onset_f, nids)
    for vi, (_vk, seq) in enumerate(seqs):
        if not seq:
            continue
        # onset → nid and onset → duration for all notes
        # seq[j][2]=nid, seq[j][4]=onset (quarters), seq[j][1]=duration (quarters)
        onset_to_nid = {round(seq[j][4] * 16): seq[j][2] for j in range(len(seq))}
        onset_to_dur = {round(seq[j][4] * 16): seq[j][1] for j in range(len(seq))}
        # last note of voice: nid = seq[-1][3], onset ≈ seq[-1][4] + seq[-1][1]
        _lkey = round((seq[-1][4] + seq[-1][1]) * 16)
        if _lkey not in onset_to_nid:
            onset_to_nid[_lkey] = seq[-1][3]
        onset_set = set(onset_to_nid)

        first_q = seq[0][4]
        last_q  = seq[-1][4]
        # first cell start at or before first note onset
        k0 = int((first_q - pickup_dur_q) / cell_q)
        cs = pickup_dur_q + k0 * cell_q
        if cs > first_q + 1e-9:
            cs -= cell_q

        while cs <= last_q + 1e-9:
            ok = True
            nids_here = []
            for k, ch in enumerate(pattern):
                t16 = round((cs + k * subdiv_q) * 16)
                has_atk = t16 in onset_set
                if ch == '1':
                    if not has_atk:
                        ok = False; break
                    nids_here.append(onset_to_nid[t16])
                elif ch == '0':
                    if has_atk:
                        ok = False; break
                elif ch == '?':
                    pass  # wildcard: any of attack / rest / held is accepted
                else:  # '_': no attack + the note from the most recent '1' still rings here
                    if has_atk:
                        ok = False; break
                    # find most recent '1' slot before k and check its duration
                    _ringing = False
                    for _kk in range(k - 1, -1, -1):
                        if pattern[_kk] == '1':
                            _atk16 = round((cs + _kk * subdiv_q) * 16)
                            _dur_q = onset_to_dur.get(_atk16)
                            if _dur_q is not None:
                                # note must end strictly after t16
                                _end16 = _atk16 + round(_dur_q * 16)
                                _ringing = _end16 > t16
                            break
                    if not _ringing:
                        ok = False; break
            if ok and nids_here:
                first_atk_q = cs + attack_ks[0] * subdiv_q
                all_cands.append((round(first_atk_q * 16), vi, first_atk_q, nids_here))
            cs += cell_q   # advance by one full cell (look-ahead does not block)

    # cross-voice dedup: same onset counted once
    all_cands.sort(key=lambda x: (x[0], x[1]))
    seen = set()
    occs_with_onset = []
    is_inv_flags = []
    for oq, _vi, of_, ns in all_cands:
        if oq in seen:
            continue
        seen.add(oq)
        occs_with_onset.append((of_, ns))
        is_inv_flags.append(False)

    # repeat unfolding (mirrors _search_motif logic)
    def _sp2(nid):
        return nid[:-4] if nid.endswith('__p2') else nid
    repeat_pairs = []
    if search_rpt_info:
        _rpt_list = search_rpt_info if isinstance(search_rpt_info, list) else [search_rpt_info]
        all_p2 = set(); all_pairs_s = []
        for rr in _rpt_list:
            rpt_start_q = rr['rpt_start']; rpt_end_q = rr['rpt_end']
            shift_q = rr['shift'];         play2_end_q = rr['play2_end']
            p1_idxs = [j for j, (o, _) in enumerate(occs_with_onset)
                       if rpt_start_q - 1e-9 <= o < rpt_end_q - 1e-9]
            p2_idxs = [j for j, (o, _) in enumerate(occs_with_onset)
                       if rpt_end_q - 1e-9 <= o < play2_end_q - 1e-9]
            all_p2.update(p2_idxs)
            if p2_idxs:
                p1_by_oq16 = {round(occs_with_onset[j][0] * 16): j for j in p1_idxs}
                for j2 in p2_idxs:
                    o2 = occs_with_onset[j2][0]
                    j1 = p1_by_oq16.get(round((o2 - shift_q) * 16))
                    if j1 is not None:
                        all_pairs_s.append((j1, j2))
        if all_p2:
            def _nids_overlap(i1, i2):
                s1 = {_sp2(n) for n in occs_with_onset[i1][1]}
                s2 = {_sp2(n) for n in occs_with_onset[i2][1]}
                return bool(s1 & s2)
            repeat_pairs = [(j1, j2, _nids_overlap(j1, j2)) for j1, j2 in all_pairs_s]

    occs_with_onset = [(o, [_sp2(nid) for nid in nids]) for o, nids in occs_with_onset]
    occs = [nids for _, nids in occs_with_onset]
    skip = sum(1 for _, _, s in repeat_pairs if s)
    return {"occs": occs, "count": len(occs) - skip, "repeat_pairs": repeat_pairs,
            "is_inv": is_inv_flags, "is_volta": bool(search_rpt_info)}


def _search_motif(query):
    """
    Parse query "dur[,dur...];phase;+iv-iv..." (phase optional, default 0).
    Rhythm-only mode: "dur[,dur...];phase" or "dur[,dur...]" — no intervals,
    N durations = N notes, any interval accepted.
    Durations may have operators: >1/16, <=1/8, etc. (default = exact match).
    N+1 durations accepted for N intervals; last one checks last note's duration.
    Returns {"occs": [[nid,...], ...], "count": N}, sorted by onset.
    """
    import _core as _kr
    _state = _kr._state
    _state_lock = _kr._state_lock
    # strip optional explicit scale prefix: (dur) at very start, e.g. (1/8) or (3/4)
    explicit_scale_q = None
    m_scale = re.match(r'^\(([^)]+)\)(.*)', query)
    if m_scale:
        _, scale_val = _parse_dur(m_scale.group(1).strip())
        explicit_scale_q = scale_val
        query = m_scale.group(2)

    # detect attack-grid format: (cell)subdiv;010... where pattern is all 0s and 1s, len>=2
    if explicit_scale_q is not None:
        _ag_m = re.match(r'^([^;]+);([01_?]{2,})$', query.strip())
        if _ag_m:
            _, _ag_subdiv_q = _parse_dur(_ag_m.group(1).strip())
            with _state_lock:
                _ag_seqs   = list(_state.get("seqs", []))
                _ag_pickup = _state.get("pickup_dur_q", 0.0)
                _ag_rpt    = _state.get("search_rpt_info")
            return _search_attack_grid(explicit_scale_q, _ag_subdiv_q, _ag_m.group(2),
                                       _ag_seqs, _ag_pickup, _ag_rpt)

    parts = query.split(';')
    # strip optional ;inv modifier
    invert = parts[-1].strip().lower() == 'inv'
    if invert:
        parts = parts[:-1]
    # detect rhythm-only: 1 part, or 2 parts where second has no +/-
    rhythm_only = False
    if len(parts) == 1:
        dur_str = parts[0]
        start_phase = 0
        rhythm_only = True
    elif len(parts) == 2 and not re.search(r'[+-]\d', parts[1]):
        dur_str = parts[0]
        start_phase = int(parts[1].strip()) if parts[1].strip() else 0
        rhythm_only = True
    elif len(parts) == 3:
        dur_str, phase_str, ivs_str = parts
        start_phase = int(phase_str.strip())
    elif len(parts) == 2:
        dur_str, ivs_str = parts
        start_phase = 0
    else:
        raise ValueError("Формат: длит;фаза;+iv-iv… или длит;фаза (только ритм)")

    # detect ? on first duration token → optional leading note
    _dur_tokens = dur_str.split(',')
    _opt_first_flag = len(_dur_tokens) > 0 and _dur_tokens[0].strip().endswith('?')
    if _opt_first_flag:
        _dur_tokens[0] = _dur_tokens[0].strip()[:-1]
    durs = [_parse_dur(s) for s in _dur_tokens]

    if rhythm_only:
        if len(durs) < 2:
            raise ValueError("Для ритмического поиска нужно минимум 2 длительности")
        # if first spec has operator (not exact), treat it as pre-gap condition
        pre_gap_spec = None
        if durs[0][0] != '=':
            pre_gap_spec = durs[0]
            durs = durs[1:]
            if len(durs) < 2:
                raise ValueError("После условия паузы нужно минимум 2 длительности нот")
        # optional first note (? suffix): may be present or absent (rest/tie)
        opt_first_dur = None
        if _opt_first_flag and pre_gap_spec is None:
            opt_first_dur = durs[0]
            durs = durs[1:]
            if len(durs) < 2:
                raise ValueError("После '?' нужно минимум 2 длительности")
        n = len(durs) - 1
        last_dur = durs[n]
        durs = durs[:n]
        intervals = None   # any interval accepted
        pattern = None
    else:
        opt_first_dur = None
        pre_gap_spec = None
        # contour mode: ivs_str contains only +/-/= chars, no digits (e.g. "+-+")
        contour_chars = re.findall(r'[+\-=]', ivs_str)
        if contour_chars and not re.search(r'\d', ivs_str):
            contour = contour_chars   # list of '+', '-', '='
            intervals = None
            n = len(contour)
        else:
            contour = None
            iv_parts = re.findall(r'[+-]\d+(?:\|\d+)*', ivs_str)
            if not iv_parts:
                raise ValueError("Интервалы не найдены (ожидается +N/-N или контур +-=)")
            def _parse_iv_token(tok):
                m2 = re.match(r'([+-])(\d+)((?:\|\d+)*)', tok)
                sign = 1 if m2.group(1) == '+' else -1
                alts = [sign * int(m2.group(2))]
                for v in re.findall(r'\d+', m2.group(3)):
                    alts.append(sign * int(v))
                return alts
            intervals = [_parse_iv_token(p) for p in iv_parts]
            n = len(intervals)
        last_dur = None
        if len(durs) == 1:
            durs = durs * n
        elif len(durs) == n + 1:
            last_dur = durs[n]
            durs = durs[:n]
        elif len(durs) != n:
            raise ValueError(f"Длительностей {len(durs)}, интервалов {n} (ожидается 1, {n} или {n+1})")
        pattern = list(zip(contour if contour else intervals, durs))

    # build inverted pattern (negate exact intervals; swap +/- in contour)
    if invert and not rhythm_only:
        def _inv_key(k):
            if isinstance(k, str):
                return '-' if k == '+' else ('+' if k == '-' else '=')
            if isinstance(k, list):
                return [-x for x in k]
            return -k
        pattern_inv = [(_inv_key(k), d) for k, d in pattern]
    else:
        pattern_inv = None

    with _state_lock:
        seqs              = list(_state.get("seqs", []))
        beat_dur_q        = _state.get("beat_dur_q", 1.0)
        pickup_dur_q      = _state.get("pickup_dur_q", 0.0)
        search_rpt_info   = _state.get("search_rpt_info")

    # compute phase using the smallest note duration in the pattern as unit
    # rhythm_only: durs elements are (op, val) → s[1] = val
    # interval:    pattern elements are (interval, (op, val)) → s[1][1] = val
    if rhythm_only:
        all_dur_vals = (([opt_first_dur[1]] if opt_first_dur is not None else []) +
                        [s[1] for s in durs] + ([last_dur[1]] if last_dur is not None else []))
    else:
        # pattern elements are (contour_char_or_interval, dur_spec); dur_spec = (op, val)
        all_dur_vals = [s[1][1] for s in pattern] + ([last_dur[1]] if last_dur is not None else [])
    min_dur_q = min(all_dur_vals) if all_dur_vals else None

    # Phase 1: collect ALL matching positions across voices (no greedy yet).
    # Phase 2: sort by (onset_q, is_inv=False first) then run joint greedy — mirrors
    # _find_motifs step 3 so direct always beats inverted at the same onset.
    _all_cands = []   # (onset_q, is_inv, vi_idx, i, onset_f, nids)
    for _vi_idx, (_vk, seq) in enumerate(seqs):
        if len(seq) < n:
            continue
        for i in range(len(seq) - n + 1):
            _curr_is_inv = False
            # phase of first note, measured in units of the smallest pattern duration
            if explicit_scale_q is not None and min_dur_q is not None:
                # explicit scale: no caps — use exact n_per_beat from scale/dur ratio
                n_pb = max(1, round(explicit_scale_q / min_dur_q))
                pos_in = (seq[i][4] - pickup_dur_q) % explicit_scale_q
                raw_ph = pos_in / min_dur_q
                rounded_ph = int(round(raw_ph))
                if abs(raw_ph - rounded_ph) > 0.35 or rounded_ph >= n_pb:
                    ph = n_pb  # sentinel — off-grid or at period boundary, never matches
                else:
                    ph = rounded_ph
                _tgt_ph = (start_phase + 1) % n_pb if opt_first_dur is not None else start_phase
            elif min_dur_q is not None:
                ph = _metric_phase(seq[i][4] - pickup_dur_q, min_dur_q, beat_dur_q)
                _tgt_ph = start_phase  # no n_pb available; opt_first not fully supported
            else:
                ph = seq[i][5]
                _tgt_ph = start_phase
            if ph != _tgt_ph:
                continue
            # pre-gap check: first spec was >x / >=x / <x / <=x → gap before this note
            if pre_gap_spec is not None:
                if i == 0:
                    # start of voice — matches > and >=, not < or <=
                    gap_ok = pre_gap_spec[0] in ('>', '>=')
                elif not seq[i - 1][6]:  # non-contiguous → rest before this note
                    gap = seq[i][4] - (seq[i - 1][4] + seq[i - 1][1])
                    gap_ok = _dur_matches(gap, pre_gap_spec)
                else:
                    # contiguous — check duration of the preceding note
                    gap_ok = _dur_matches(seq[i - 1][1], pre_gap_spec)
                if not gap_ok:
                    continue
            if rhythm_only:
                if not all(_dur_matches(seq[i + k][1], durs[k]) for k in range(n)):
                    continue
            elif contour:
                def _dir(iv):
                    return '+' if iv > 0 else ('-' if iv < 0 else '=')
                def _match_pat(pat):
                    return all(_dir(seq[i + k][0]) == pat[k][0] and
                               _dur_matches(seq[i + k][1], pat[k][1])
                               for k in range(n))
                _d_ok = _match_pat(pattern)
                _i_ok = pattern_inv is not None and _match_pat(pattern_inv)
                if not (_d_ok or _i_ok):
                    continue
                _curr_is_inv = _i_ok and not _d_ok
            else:
                def _match_pat(pat):
                    return all((seq[i + k][0] in pat[k][0] if isinstance(pat[k][0], list)
                                else seq[i + k][0] == pat[k][0]) and
                               _dur_matches(seq[i + k][1], pat[k][1])
                               for k in range(n))
                _d_ok = _match_pat(pattern)
                _i_ok = pattern_inv is not None and _match_pat(pattern_inv)
                if not (_d_ok or _i_ok):
                    continue
                _curr_is_inv = _i_ok and not _d_ok
            # check last note's duration: seq[i+n][1] is its duration as first note of next interval
            if last_dur is not None and i + n < len(seq):
                if not _dur_matches(seq[i + n][1], last_dur):
                    continue
            # exclude matches with rests between notes (use precomputed contiguous flag)
            if not all(seq[i + k][6] for k in range(n)):
                continue
            # optional leading note: include if contiguous, right duration, right phase
            _opt_nid = None
            if opt_first_dur is not None and i > 0 and seq[i - 1][6]:
                if _dur_matches(seq[i - 1][1], opt_first_dur):
                    if explicit_scale_q is not None and min_dur_q is not None:
                        _n_pb2 = max(1, round(explicit_scale_q / min_dur_q))
                        _pos2  = (seq[i - 1][4] - pickup_dur_q) % explicit_scale_q
                        _rph2  = _pos2 / min_dur_q
                        _iph2  = int(round(_rph2))
                        if abs(_rph2 - _iph2) <= 0.35 and _iph2 == start_phase % _n_pb2:
                            _opt_nid = seq[i - 1][2]
                    else:
                        _opt_nid = seq[i - 1][2]
            onset_q = round((seq[i - 1][4] if _opt_nid else seq[i][4]) * 16)
            nids = ([_opt_nid] if _opt_nid else []) + [seq[i][2]] + [seq[i + k][3] for k in range(n)]
            # compute next valid start: after scale period end (if scale given), else i+n+1
            _next_start_i = i + n + 1
            if explicit_scale_q is not None and min_dur_q is not None:
                _scale_end = seq[i][4] - _tgt_ph * min_dur_q + explicit_scale_q
                _nsi = i + n + 1
                while _nsi < len(seq) and seq[_nsi][4] < _scale_end - 1e-9:
                    _nsi += 1
                _next_start_i = _nsi
            _all_cands.append((onset_q, _curr_is_inv, _vi_idx, i, seq[i][4], nids, _next_start_i))

    # Phase 2: sort (direct before inverted at same onset, then by voice), joint greedy.
    # Cross-dedup does NOT advance per-voice last_end — same semantics as _find_motifs.
    _all_cands.sort(key=lambda x: (x[0], x[1], x[2]))
    _last_end_v = {}
    seen_onsets = set()
    used_nids   = set()   # NIDs already claimed; prevents cross-voice note sharing
    occs_with_onset = []
    is_inv_flags    = []
    for _oq, _inv, _vi, _i, _of, _ns, _nsi in _all_cands:
        if _i < _last_end_v.get(_vi, -1):
            continue
        if _oq in seen_onsets:
            continue  # cross-onset dedup — don't advance last_end_v
        # strip __p2 suffix before NID collision check so repeat copies don't block each other
        _ns_base = [_n[:-4] if _n.endswith('__p2') else _n for _n in _ns]
        if used_nids.intersection(_ns_base):
            continue  # shares notes with an already-accepted occurrence — don't advance last_end_v
        occs_with_onset.append((_of, _ns))
        is_inv_flags.append(_inv)
        seen_onsets.add(_oq)
        used_nids.update(_ns_base)
        _last_end_v[_vi] = _nsi

    def _strip_p2(nid):
        return nid[:-4] if nid.endswith('__p2') else nid

    # Apply repeat_pairs — simple repeat or volta unfolding (loop over all ranges)
    # occs_with_onset is already in chronological order (A1,A2,B1,B2,...) — no reordering needed.
    repeat_pairs = []
    if search_rpt_info:
        _rpt_list = search_rpt_info if isinstance(search_rpt_info, list) else [search_rpt_info]
        all_p2 = set(); all_pairs_s = []
        for rr in _rpt_list:
            rpt_start_q = rr['rpt_start']; rpt_end_q = rr['rpt_end']
            shift_q = rr['shift'];         play2_end_q = rr['play2_end']
            p1_idxs = [j for j, (o, _) in enumerate(occs_with_onset)
                       if rpt_start_q - 1e-9 <= o < rpt_end_q - 1e-9]
            p2_idxs = [j for j, (o, _) in enumerate(occs_with_onset)
                       if rpt_end_q - 1e-9 <= o < play2_end_q - 1e-9]
            all_p2.update(p2_idxs)
            if p2_idxs:
                p1_by_oq16 = {round(occs_with_onset[j][0] * 16): j for j in p1_idxs}
                for j2 in p2_idxs:
                    o2 = occs_with_onset[j2][0]
                    j1 = p1_by_oq16.get(round((o2 - shift_q) * 16))
                    if j1 is not None:
                        all_pairs_s.append((j1, j2))
        if all_p2:
            def _nids_overlap(i1, i2):
                s1 = set(_strip_p2(n) for n in occs_with_onset[i1][1])
                s2 = set(_strip_p2(n) for n in occs_with_onset[i2][1])
                return bool(s1 & s2)
            repeat_pairs = [(j1, j2, _nids_overlap(j1, j2)) for j1, j2 in all_pairs_s]

    occs_with_onset = [(o, [_strip_p2(nid) for nid in nids]) for o, nids in occs_with_onset]
    occs = [nids for _, nids in occs_with_onset]
    _skip_p2_true_count = sum(1 for _, _, skip in repeat_pairs if skip)
    display_count = len(occs) - _skip_p2_true_count
    is_volta_result = bool(search_rpt_info)
    return {"occs": occs, "count": display_count, "repeat_pairs": repeat_pairs,
            "is_inv": is_inv_flags, "is_volta": is_volta_result}


def _mdl_score(n, L, transforms):
    """MDL saving = n*(L-1) - L - transp_cost.
    Sequence bonus: if ≥3 occurrences have constant ∆transposition,
    the transposition list encodes as (start, step, count) → cost = log2(n+1).
    """
    import math
    if n < 2 or L < 1:
        return 0
    transposes = [t['transposition'] for t in transforms]
    n_distinct = len(set(transposes))
    is_seq = False
    if n >= 3:
        deltas = [transposes[i + 1] - transposes[i] for i in range(n - 1)]
        if len(set(deltas)) == 1 and deltas[0] != 0:
            is_seq = True
    transp_cost = math.log2(n + 1) if is_seq else n * math.log2(n_distinct + 1)
    return round(n * (L - 1) - L - transp_cost)


def analyze_motifs(vtk, mei_str=None, beat_dur_q_override=None):
    """
    Run motif analysis on the currently-loaded verovio score.
    Returns list of:
      {'color': str, 'occs': [[nid, ...], ...], 'count': int, 'length': int}
    where each inner list is the note IDs of one occurrence of the motif.
    """
    try:
        if mei_str is None:
            mei_str = vtk.getMEI()
        voices, beat_dur_q, pickup_dur_q, repeat_ranges, volta_groups = _voice_notes_from_mei(mei_str)
        if beat_dur_q_override is not None:
            beat_dur_q = beat_dur_q_override

        rpt_start = rpt_end = shift = play2_end = 0.0

        _all_rpt_ranges = []   # [(p1_start, p1_end, shift, p2_end), ...]
        # ── Build merged action list: simple repeats + volta groups in timeline order ──
        # Skip repeat_ranges that are covered by a volta group (overlap check).
        _volta_spans = [(vg['body'][0], vg['volta2'][1]) for vg in volta_groups]
        _actions = []  # (start, 'volta'|'simple', payload)
        for rs, re in repeat_ranges:
            if any(rs < vce and re > vcs for vcs, vce in _volta_spans):
                continue   # covered by a volta group — skip
            _actions.append((rs, 'simple', (rs, re)))
        for vg in volta_groups:
            _actions.append((vg['body'][0], 'volta', vg))
        _actions.sort(key=lambda x: x[0])

        # Only unfold when: volta present, or exactly one simple repeat remains
        if not (volta_groups or len(_actions) == 1):
            _actions = []

        if _actions:
            # Set rpt_start/rpt_end/shift/play2_end for _is_spl_rpt flag
            if volta_groups:
                vg0 = volta_groups[0]
                rpt_start = vg0['body'][0]
                rpt_end   = vg0['volta1'][1]
                shift     = rpt_end - rpt_start
                play2_end = rpt_end + (vg0['body'][1] - vg0['body'][0])
            else:
                rpt_start, rpt_end = _actions[0][2]
                shift     = rpt_end - rpt_start
                play2_end = rpt_end + shift
            seq_voices = {vk: list(notes) for vk, notes in voices.items()}
            cum_shift = 0.0
            for _, _atype, _payload in _actions:
                if _atype == 'volta':
                    vg = _payload
                    bs, be   = vg['body']
                    v1s, v1e = vg['volta1']
                    v2s, v2e = vg['volta2']
                    body_dur = be  - bs
                    gap      = v1e - bs
                    bs_u  = bs  + cum_shift;  be_u  = be  + cum_shift
                    v1e_u = v1e + cum_shift;  v2s_u = v2s + cum_shift;  v2e_u = v2e + cum_shift
                    next_v = {}
                    for vk, notes in seq_voices.items():
                        pre     = [n for n in notes if n[5] < bs_u]
                        body    = [n for n in notes if bs_u  <= n[5] < be_u]
                        v1      = [n for n in notes if be_u  <= n[5] < v1e_u]
                        v2      = [n for n in notes if v2s_u <= n[5] < v2e_u]
                        post    = [n for n in notes if n[5] >= v2e_u]
                        body_p2 = [(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5] + gap)     for n in body]
                        v2_sh   = [(n[0],        n[1], n[2], n[3], n[4], n[5] + body_dur) for n in v2]
                        post_sh = [(n[0],        n[1], n[2], n[3], n[4], n[5] + body_dur) for n in post]
                        next_v[vk] = pre + body + v1 + body_p2 + v2_sh + post_sh
                    seq_voices = next_v
                    _all_rpt_ranges.append((bs_u, v1e_u, gap, v1e_u + body_dur))
                    cum_shift += body_dur
                else:  # 'simple'
                    rs, re = _payload
                    rs_u = rs + cum_shift;  re_u = re + cum_shift;  sh_r = re - rs
                    next_v = {}
                    for vk, notes in seq_voices.items():
                        pre_r  = [n for n in notes if n[5] < rs_u]
                        rep_r  = [n for n in notes if rs_u <= n[5] < re_u]
                        post_r = [n for n in notes if n[5] >= re_u]
                        rep_r2  = [(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5] + sh_r) for n in rep_r]
                        post_r2 = [(n[0],        n[1], n[2], n[3], n[4], n[5] + sh_r) for n in post_r]
                        next_v[vk] = pre_r + rep_r + rep_r2 + post_r2
                    seq_voices = next_v
                    _all_rpt_ranges.append((rs_u, re_u, sh_r, re_u + sh_r))
                    cum_shift += sh_r
        else:
            seq_voices = voices

        seq_voices = _remove_unison_voices(seq_voices)
        # Budget ~2.8e-6 × V × n² seconds; cap n per voice so total < 3s.
        # cap = sqrt(3 / (2.8e-6 × V)), min 100.
        _n_v = max(1, len(seq_voices))
        _cap = max(100, int(math.sqrt(3.0 / (2.8e-6 * _n_v))))
        all_seqs = [(vk, _interval_seq(notes[:_cap], beat_dur_q, pickup_dur_q))
                    for vk, notes in seq_voices.items()
                    if len(notes) >= 4]
        _max_voice_len = max((len(n) for n in seq_voices.values()), default=0)
        all_seqs_full = [(vk, _interval_seq(notes, beat_dur_q, pickup_dur_q))
                         for vk, notes in seq_voices.items()
                         if len(notes) >= 4] if _cap < _max_voice_len else None
        # soprano_global: highest note at each 1/16-grid position across ALL staves/voices.
        # Catches cross-staff melodic handoffs (e.g. scale descending from RH into LH).
        _all_notes_g = [n for notes in seq_voices.values() for n in notes]
        if _all_notes_g:
            _min_dur_g = min(n[3] for n in _all_notes_g)
            _step_g = max(_min_dur_g, 0.25)  # at most 1/16 grid
            _EPS_g = _step_g * 0.05
            _min_on_g = min(n[5] for n in _all_notes_g)
            _max_on_g = max(n[5] for n in _all_notes_g)
            _T0_g = _min_on_g - (_min_on_g % _step_g) if _step_g > 0 else _min_on_g
            _glob_sop = []
            _T_g = round(_T0_g, 9)
            while _T_g <= _max_on_g + _EPS_g:
                _cands_g = [n for n in _all_notes_g if abs(n[5] - _T_g) <= _EPS_g]
                if _cands_g:
                    _best_g = max(_cands_g, key=lambda n: n[4])
                    _glob_sop.append((_best_g[0], _best_g[1], _best_g[2], _step_g, _best_g[4], _T_g))
                _T_g = round(_T_g + _step_g, 9)
            if len(_glob_sop) >= 4:
                all_seqs.append((('soprano_global', 0), _interval_seq(_glob_sop[:_cap], beat_dur_q, pickup_dur_q)))
                if all_seqs_full is not None:
                    all_seqs_full.append((('soprano_global', 0), _interval_seq(_glob_sop, beat_dur_q, pickup_dur_q)))
        motifs = _find_motifs(all_seqs, beat_dur_q=beat_dur_q, pickup_dur_q=pickup_dur_q,
                              all_seqs_full=all_seqs_full)
        # Repeat-unfolding flag: True for both simple repeat and volta unfolding.
        _is_spl_rpt      = shift > 0
        _is_volta_unfold = bool(volta_groups) and shift > 0
        result = []
        for i, m in enumerate(motifs):
            steps = [_interval_label(iv, dur) for iv, dur in m['pattern']]
            phase = m.get('phase', 0)
            phase_pfx = {0: '', 1: '_|', 2: '_|_|'}.get(phase, '')
            transforms = m.get('transforms', [])
            min_dur_q = min((p[1] for p in m['pattern']), default=0.25)
            profile = []
            prev_oq = None
            for t in transforms:
                oq = t.get('onset_q', 0)
                if prev_oq is None:
                    dist = 0
                else:
                    dist = round((oq - prev_oq) / 16.0 / min_dur_q)
                profile.append({
                    'transp': t['transposition'],
                    'inv':    t['inversion'],
                    'dist':   dist,
                })
                prev_oq = oq
            n_occ = len(m['occurrences'])
            L_pat = len(m['pattern'])
            # ── Separate play-1 / play-2 / non-repeat by onset range ─────────────
            # _find_motifs already ran on the unfolded sequence, so play-2
            # occurrences exist with shifted onsets.
            # Order output: [play-1..., play-2..., non-repeat...]
            repeat_pairs   = []
            occs_out       = list(m['occurrences'])
            transforms_out = transforms
            _nd = m.get('n_direct_only', n_occ)
            _ni = m.get('n_inv_only', 0)
            _nb = m.get('n_both', 0)
            def _strip_p2(nid):
                return nid[:-4] if nid.endswith('__p2') else nid
            # Use _all_rpt_ranges for volta; fall back to single range for simple repeat
            _ranges = _all_rpt_ranges if _all_rpt_ranges else (
                [(rpt_start, rpt_end, shift, play2_end)] if shift > 0 else [])
            if _ranges:
                # Collect all p1/p2 pairs across every unfolded range
                all_p1 = set(); all_p2 = set(); all_pairs = []
                for _rs, _re, _sh, _p2e in _ranges:
                    _rs16 = _rs*16; _re16 = _re*16; _sh16 = _sh*16; _p2e16 = _p2e*16
                    _p1 = [j for j, t in enumerate(transforms)
                           if _rs16 <= t['onset_q'] < _re16]
                    _p2 = [j for j, t in enumerate(transforms)
                           if _re16 <= t['onset_q'] < _p2e16]
                    all_p1.update(_p1); all_p2.update(_p2)
                    _p1_oq = {transforms[j]['onset_q']: j for j in _p1}
                    for j2 in _p2:
                        j1 = _p1_oq.get(transforms[j2]['onset_q'] - _sh16)
                        if j1 is not None:
                            all_pairs.append((j1, j2))
                nr_idxs = [j for j in range(len(transforms))
                           if j not in all_p1 and j not in all_p2]
                if all_p2:
                    occs_out = [[_strip_p2(nid) for nid in m['occurrences'][j]]
                                for j in range(len(transforms))]
                    transforms_out = transforms
                    def _nids_overlap(pos1, pos2):
                        return bool(set(occs_out[pos1]) & set(occs_out[pos2]))
                    repeat_pairs = [(j1, j2, _nids_overlap(j1, j2))
                                    for j1, j2 in all_pairs]
                    n_occ = len(occs_out)
                    paired_p2   = {j2 for _, j2 in all_pairs}
                    unpaired_p2 = [j for j in all_p2 if j not in paired_p2]
                    structural  = len(all_p1) + len(nr_idxs) + len(unpaired_p2)
                    if _is_spl_rpt:
                        if structural + len(all_pairs) < 2:
                            continue
                    elif structural < 2:
                        continue
            # Positions in occs_out/transforms_out that are p2 of skip_p2=True pairs —
            # these are drawn as "(X2)" brackets only, not counted as separate occurrences.
            _skip_true_p2_pos = {pos2 for _, pos2, skip in repeat_pairs if skip}
            _n_p2_skip = len(_skip_true_p2_pos)   # repeat contribution (A section count)
            # Recompute three-way counts from ALL transforms (no skip exclusion).
            # For volta: halve even counts (same rule as _disp); keep odd counts as-is.
            if transforms_out is not transforms or _skip_true_p2_pos:
                _pos_inv = {}
                for _k, _t in enumerate(transforms_out):
                    _oq  = _t['onset_q']
                    _inv = _t.get('inversion', False)
                    if _oq not in _pos_inv:
                        _pos_inv[_oq] = set()
                    _pos_inv[_oq].add(_inv)
                _nd_r = sum(1 for _f in _pos_inv.values() if _f == {False})
                _ni_r = sum(1 for _f in _pos_inv.values() if _f == {True})
                _nb_r = sum(1 for _f in _pos_inv.values() if len(_f) == 2)
                if _is_volta_unfold:
                    _nd = _nd_r // 2 if _nd_r % 2 == 0 else _nd_r
                    _ni = _ni_r // 2 if _ni_r % 2 == 0 else _ni_r
                    _nb = _nb_r // 2 if _nb_r % 2 == 0 else _nb_r
                else:
                    _nd, _ni, _nb = _nd_r, _ni_r, _nb_r
            _dc = n_occ - _n_p2_skip
            # For simple repeat: count A occurrences twice → threshold against n_occ
            if (_is_spl_rpt and n_occ < 2) or (not _is_spl_rpt and _dc < 2):
                continue
            # Volta: halve even counts to remove trivial doubling from body playing twice
            if _is_volta_unfold:
                _disp = n_occ // 2 if n_occ % 2 == 0 else n_occ
            elif _is_spl_rpt:
                _disp = n_occ
            else:
                _disp = _dc
            result.append({
                'color':             _MOTIF_COLORS[i % len(_MOTIF_COLORS)],
                'occs':              occs_out,
                'count':             n_occ,
                'display_count':     _disp,
                'n_p2_skip':         _n_p2_skip if _is_spl_rpt else 0,
                'length':            L_pat + 1,
                'pattern':           steps,
                'phase_pfx':         phase_pfx,
                'transforms':        transforms_out,
                'n_direct_only':     _nd,
                'n_inv_only':        _ni,
                'n_both':            _nb,
                'queryStr':          _pattern_to_query(m['pattern'], phase) + (';inv' if (_ni + _nb) > 0 else ''),
                'profile':           profile,
                'repeat_pairs':      repeat_pairs,
                'is_volta':          _is_spl_rpt,
                'mdl':               _mdl_score(_disp, L_pat, transforms_out),
            })
        return result
    except Exception as e:
        print(f"[motif] {e}")
        return []


#!/usr/bin/env python3
"""
MIDI export with motif orchestration.

Background track: harpsichord plays every note of the score.
For each motif whose count is a smooth number (2^a*3^b >= 8; direct, inverted or union count,
same rule as the bold counts in the reader) its notes are doubled on a separate track with its
own instrument (up to 10 motifs, ordered like the reader's table: largest smooth count first).

Usage:
  python convert2midi/midi_export.py lilypond/musicxml/bwv678.xml
  python convert2midi/midi_export.py lilypond/musicxml/bwv678.xml --bpm 72 --out bwv678_motifs.mid --max-motifs 10
"""
import argparse, importlib.util, os, struct, sys

_here = os.path.dirname(os.path.abspath(__file__))          # .../convert2midi
_root = os.path.dirname(_here)                                # project root (reader/)
_reader_dir = os.path.join(_root, 'reader')
sys.path.insert(0, _reader_dir)
sys.path.insert(0, _root)
sys.path.insert(0, _here)

HARPSICHORD = 6
BACKGROUNDS = {'harpsichord': 6, 'organ': 19, 'reed-organ': 20, 'rock-organ': 18, 'piano': 0}
# GM programs (0-based) with clearly different timbres; order = assignment order
MOTIF_PROGRAMS = [
    (73, 'flute'), (68, 'oboe'), (71, 'clarinet'), (56, 'trumpet'), (40, 'violin'),
    (42, 'cello'), (11, 'vibraphone'), (60, 'french horn'), (46, 'harp'), (12, 'marimba'),
    (70, 'bassoon'), (8, 'celesta'), (57, 'trombone'), (13, 'xylophone'),
    # more than 14 motifs do not fit the 14 free MIDI channels: further groups go to extra files
    (75, 'pan flute'), (21, 'accordion'), (58, 'tuba'), (69, 'english horn'), (72, 'piccolo'),
    (74, 'recorder'), (64, 'soprano sax'), (66, 'tenor sax'), (59, 'muted trumpet'),
    (10, 'music box'), (9, 'glockenspiel'), (14, 'tubular bells'), (107, 'koto'), (105, 'banjo'),
]
GROUP = 14   # motifs per MIDI file (free channels: 16 - ch0 - drums ch9)
TPQ = 480
CARRY_ACROSS_STAVES = False  # accidental carry-over within a measure also across staves
# final ritardando defaults (see final_ritardando)
CHORALE_PROGRAM = 19  # church organ
RIT_BEATS = 4.0
RIT_FINAL = 0.65
RIT_Q = 2.0
HOLD = 1.0
PRE_STRETCH = 2.0


def is_smooth(k):
    if k <= 0:
        return False
    while k % 2 == 0:
        k //= 2
    while k % 3 == 0:
        k //= 3
    return k == 1


def smooth_counts(m):
    union = m.get('display_count', m['count'])
    n_both = m.get('n_both', 0)
    n_dir = m.get('n_direct_only', union) + n_both
    n_inv = m.get('n_inv_only', 0) + n_both
    counts = [union, n_dir, n_inv]
    if 'b_n_direct_only' in m:           # bounded counts (<...> in the reader table), tie tails included
        b_both = m['b_n_both']
        counts += [m['b_n_direct_only'] + b_both, m['b_n_inv_only'] + b_both,
                   m['b_n_direct_only'] + m['b_n_inv_only'] + b_both]
    return [k for k in counts if is_smooth(k) and k >= 8]


def load_core():
    spec = importlib.util.spec_from_file_location('_core', os.path.join(_reader_dir, 'app.py'))
    core = importlib.util.module_from_spec(spec)
    sys.modules['_core'] = core
    spec.loader.exec_module(core)
    return core


def analyse(path):
    """Run the reader's pipeline on `path`; return (nid_to_note, motifs)."""
    core = load_core()
    captured = {}
    orig = core.analyze_motifs

    def wrapper(*a, **kw):
        res = orig(*a, **kw)
        captured['motifs'] = res
        return res

    core.analyze_motifs = wrapper
    out = core.render_score(path, '1', 0)
    nid_to_note = out[7]
    seqs = out[3]
    mei = core._vtk.getMEI()
    return nid_to_note, captured.get('motifs', []), seqs, mei


_STEP_PC = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
_ACCID = {'s': 1, 'f': -1, 'ss': 2, 'x': 2, 'ff': -2, 'n': 0, 'su': 1, 'fd': -1}
_SHARP_ORDER = 'fcgdaeb'
_FLAT_ORDER = 'beadgcf'


def _key_alter(key_sig):
    """'3s' -> {'f':1,'c':1,'g':1}, '2f' -> {'b':-1,'e':-1}, '0' -> {}"""
    if not key_sig or key_sig[0] == '0':
        return {}
    n = int(''.join(ch for ch in key_sig if ch.isdigit()) or 0)
    if key_sig.endswith('s'):
        return {p: 1 for p in _SHARP_ORDER[:n]}
    if key_sig.endswith('f'):
        return {p: -1 for p in _FLAT_ORDER[:n]}
    return {}


def chord_siblings(mei_str, nid_to_note):
    """The reader keeps only the TOP note of every <chord> (it follows a melodic line), so inner
    chord notes are missing from nid_to_note. Returns {sibling_nid: top_nid} for the notes of
    each chord whose top note is known. Chords whose top note is absent (tied continuations)
    are skipped, which also prevents re-attacking tied chord notes."""
    import xml.etree.ElementTree as ET
    xid = '{http://www.w3.org/XML/1998/namespace}id'
    sib = {}
    for el in ET.fromstring(mei_str).iter():
        if el.tag.rsplit('}', 1)[-1] != 'chord':
            continue
        kids = [n for n in el if n.tag.rsplit('}', 1)[-1] == 'note' and n.get(xid)]
        tops = [n.get(xid) for n in kids if n.get(xid) in nid_to_note]
        if len(tops) != 1 or el.get('grace'):
            continue
        for n in kids:
            if n.get(xid) != tops[0] and n.get('grace') is None:
                sib[n.get(xid)] = tops[0]
    return sib


def sounding_midi(mei_str, nid_to_note):
    """{nid: midi} with key signature and in-measure accidental carry-over applied.
    The reader's own midi (nid_to_note) ignores carried accidentals, which is fine for diatonic
    analysis but wrong for sound."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(mei_str)

    def tag(e):
        return e.tag.rsplit('}', 1)[-1]

    onset_of = {nid: v[5] for nid, v in nid_to_note.items()}
    for sn, tn in chord_siblings(mei_str, nid_to_note).items():
        onset_of[sn] = nid_to_note[tn][5]
    result = {}
    key = {}

    def key_from(sd):
        ks = sd.get('key.sig')
        if ks is None:
            for st in sd.iter():
                if tag(st) == 'staffDef' and st.get('key.sig') is not None:
                    return st.get('key.sig')
                # MusicXML-sourced MEI: <staffDef><keySig sig="2f"/></staffDef>
                if tag(st) == 'keySig' and st.get('sig') is not None:
                    return st.get('sig')
        return ks

    def walk(el):
        nonlocal key
        for ch in el:
            t = tag(ch)
            if t == 'scoreDef':
                ks = key_from(ch)
                if ks is not None:
                    key = _key_alter(ks)
            elif t == 'measure':
                do_measure(ch)
            elif t in ('section', 'ending', 'score', 'mdiv', 'body', 'music'):
                walk(ch)

    def do_measure(msr):
        # accidentals carry over to the rest of the measure for the same pitch. Across staves too:
        # editions (and musedata) often print the sign only on the first occurrence in the
        # system, e.g. C# in the right hand and the same C# in a left-hand chord later.
        groups = []
        if CARRY_ACROSS_STAVES:
            groups = [[st for st in msr if tag(st) == 'staff']]
        else:
            groups = [[st] for st in msr if tag(st) == 'staff']
        for staves in groups:
            notes = []
            for staff in staves:
                for n in staff.iter():
                    if tag(n) == 'note':
                        nid = n.get('{http://www.w3.org/XML/1998/namespace}id')
                        notes.append((onset_of.get(nid, 1e9), nid, n))
            notes.sort(key=lambda x: x[0])
            carried = {}
            for _on, nid, n in notes:
                pname = (n.get('pname') or 'c').lower()
                octv = int(n.get('oct') or 4)
                acc = n.get('accid')
                ges = n.get('accid.ges')
                if acc is None:
                    # written accidental may be a child <accid>
                    for c in n:
                        if tag(c) == 'accid' and c.get('accid'):
                            acc = c.get('accid')
                if acc is not None:
                    alter = _ACCID.get(acc, 0)
                    carried[(pname, octv)] = alter
                elif ges is not None:
                    alter = _ACCID.get(ges, 0)
                elif (pname, octv) in carried:
                    alter = carried[(pname, octv)]
                else:
                    alter = key.get(pname, 0)
                if nid:
                    result[nid] = (octv + 1) * 12 + _STEP_PC[pname] + alter

    walk(root)
    # a tied-to note sounds like its tie start (accidental is not repeated after a barline)
    ties = []
    for e in root.iter():
        if tag(e) == 'tie' and e.get('startid') and e.get('endid'):
            ties.append((e.get('startid').lstrip('#'), e.get('endid').lstrip('#')))
    for _ in range(3):
        for a, b in ties:
            if a in result and b in result:
                result[b] = result[a]
    return result


def extend_parallel(m, seqs):
    """Return nids of `m` including copies in other voices: same body (or its inversion)
    starting at the same onset. The reader counts a simultaneous occurrence once; for sound
    every voice that carries it should get the motif's timbre."""
    # nid0 -> (voice, index)
    first = {}
    onset_idx = []
    for vi, (_vk, seq) in enumerate(seqs):
        d = {}
        for j, x in enumerate(seq):
            first[x[2]] = (vi, j)
            d.setdefault(round(x[4] * 16), []).append(j)
        onset_idx.append(d)
    nids = set()
    extra = 0
    occs = list(m.get('occs', [])) + list(m.get('b_occs', []))
    for occ in occs:
        occ = [n[:-4] if n.endswith('__p2') else n for n in occ]
        nids.update(occ)
        if len(occ) < 2 or occ[0] not in first:
            continue
        vi, j = first[occ[0]]
        seq = seqs[vi][1]
        L = len(occ) - 1
        if j + L > len(seq):
            continue
        body = tuple((seq[j + k][0], seq[j + k][1]) for k in range(L))
        inv = tuple((-a, b) for a, b in body)
        oq = round(seq[j][4] * 16)
        for vo, (_vk2, seq2) in enumerate(seqs):
            if vo == vi:
                continue
            for j2 in onset_idx[vo].get(oq, []):
                if j2 + L > len(seq2):
                    continue
                if not all(seq2[j2 + k][6] for k in range(L)):
                    continue
                b2 = tuple((seq2[j2 + k][0], seq2[j2 + k][1]) for k in range(L))
                if b2 == body or b2 == inv:
                    new = {seq2[j2][2]} | {seq2[j2 + k][3] for k in range(L)}
                    if not new <= nids:
                        extra += 1
                    nids |= new
    return nids, extra


def select_motifs(motifs, max_motifs, min_count=None):
    """Default: motifs with a smooth count (>= 8), largest smooth count first.
    min_count given: every motif whose occurrence count is >= min_count (smooth or not),
    largest count first."""
    if min_count is not None:
        sm = [m for m in motifs if m.get('display_count', m['count']) >= min_count]
        sm.sort(key=lambda m: m.get('display_count', m['count']), reverse=True)
        return sm[:max_motifs]
    sm = [m for m in motifs if smooth_counts(m)]
    sm.sort(key=lambda m: max(smooth_counts(m)), reverse=True)
    return sm[:max_motifs]


# ── minimal SMF writer ───────────────────────────────────────────────────────

def _vlq(v):
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def _track(events):
    """events: [(tick, order, bytes)] -> track chunk."""
    events.sort(key=lambda e: (e[0], e[1]))
    data = bytearray()
    prev = 0
    for tick, _o, b in events:
        data += _vlq(tick - prev) + b
        prev = tick
    data += _vlq(0) + b'\xff\x2f\x00'
    return b'MTrk' + struct.pack('>I', len(data)) + bytes(data)


def _tempo_meta(bpm):
    return b'\xff\x51\x03' + int(60_000_000 / bpm).to_bytes(3, 'big')


def final_ritardando(tracks, bpm, rit_beats, w, q, hold, pre_stretch=1.0, step_q=0.25):
    """Friberg-Sundberg final slowing (relative tempo as a function of position x in [0,1]):
        v(x) = [1 + (w^q - 1) * x]^(1/q)      (1 = nominal tempo, w = tempo at the end)
    applied over the `rit_beats` quarters before the onset of the final chord; the final chord
    keeps tempo w*bpm and is additionally held `hold` times its notated length.
    `pre_stretch` > 1 delays the chord: the last subdivision before it (the interval from the
    previous onset to the final chord, e.g. the last 16th) lasts `pre_stretch` times longer.
    Returns (tempo_events, tracks) with the final chord's notes lengthened."""
    final_on = max(n[0] for _nm, _c, _p, notes in tracks for n in notes)
    start = max(0.0, final_on - rit_beats)
    ev = []
    k = 0
    while start + k * step_q < final_on - 1e-9:
        pos = start + k * step_q
        x = (pos - start) / (final_on - start)
        rel = (1 + (w ** q - 1) * x) ** (1.0 / q)
        ev.append((int(round(pos * TPQ)), 0, _tempo_meta(bpm * rel)))
        k += 1
    if pre_stretch != 1.0:
        prev_on = max((n[0] for _nm, _c, _p, notes in tracks for n in notes
                       if n[0] < final_on - 1e-6), default=None)
        if prev_on is not None:
            t_prev = int(round(prev_on * TPQ))
            x = max(0.0, (prev_on - start) / (final_on - start))
            rel = (1 + (w ** q - 1) * x) ** (1.0 / q)
            ev = [e for e in ev if e[0] < t_prev]
            ev.append((t_prev, 0, _tempo_meta(bpm * rel / pre_stretch)))
    ev.append((int(round(final_on * TPQ)), 0, _tempo_meta(bpm * w)))
    new_tracks = []
    for name, ch, prog, notes in tracks:
        nn = [(o, d * hold, m, v) if abs(o - final_on) < 1e-6 else (o, d, m, v)
              for o, d, m, v in notes]
        new_tracks.append((name, ch, prog, nn))
    return ev, new_tracks


def write_midi(path, tracks, bpm, tempo_events=None):
    """tracks: [(name, channel, program, [(onset_q, dur_q, midi, vel)])]"""
    chunks = []
    meta = [(0, 0, _tempo_meta(bpm))] + list(tempo_events or [])
    chunks.append(_track(meta))
    for name, ch, prog, notes in tracks:
        ev = [(0, 0, b'\xff\x03' + _vlq(len(name.encode())) + name.encode()),
              (0, 1, bytes([0xC0 | ch, prog]))]
        for onset, dur, midi, vel in notes:
            t_on = int(round(onset * TPQ))
            t_off = max(t_on + 1, int(round((onset + dur) * TPQ)) - 4)
            ev.append((t_on, 3, bytes([0x90 | ch, midi, vel])))
            ev.append((t_off, 2, bytes([0x80 | ch, midi, 0])))
        chunks.append(_track(ev))
    header = b'MThd' + struct.pack('>IHHH', 6, 1, len(chunks), TPQ)
    with open(path, 'wb') as f:
        f.write(header + b''.join(chunks))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--bpm', type=float, default=72.0)
    ap.add_argument('--out', default=None)
    ap.add_argument('--max-motifs', type=int, default=10)
    ap.add_argument('--min-count', type=int, default=None,
                    help='experiment: take ALL motifs with at least this many occurrences '
                         '(smooth or not) instead of only smooth-count ones; max %d' % len(MOTIF_PROGRAMS))
    ap.add_argument('--bg', choices=sorted(BACKGROUNDS), default='harpsichord',
                    help='background instrument that plays all notes')
    ap.add_argument('--double-voices', default='',
                    help="voices (staff.layer, comma separated, e.g. '3.1' = organ pedal) to double on "
                         "an extra instrument shifted by --double-shift semitones")
    ap.add_argument('--double-program', type=int, default=43, help='GM program of the doubling track (43 = contrabass)')
    ap.add_argument('--double-shift', type=int, default=-12, help='semitone shift of the doubling track')
    ap.add_argument('--double-name', default='contrabass')
    ap.add_argument('--double-floor', type=int, default=28,
                    help='lowest MIDI note of the doubling track (28 = E1, lowest contrabass string); '
                         'notes that would fall below it are moved up an octave (0 = no floor)')
    ap.add_argument('--chorale-voices', default='',
                    help="voices (staff.layer, comma separated, e.g. '2.1,2.2') that carry a chorale "
                         "melody / cantus firmus: doubled with an organ track")
    ap.add_argument('--chorale-min-dur', type=float, default=1.0,
                    help='shortest note (quarters) taken as chorale melody; shorter notes in the '
                         'listed voices are ornament/accompaniment and are skipped')
    ap.add_argument('--chorale-program', type=int, default=CHORALE_PROGRAM,
                    help='GM program of the chorale organ track (default 19 = church organ)')
    ap.add_argument('--rit-beats', type=float, default=RIT_BEATS,
                    help='quarters before the final chord over which the tempo slows (0 = off)')
    ap.add_argument('--rit-final', type=float, default=RIT_FINAL,
                    help='tempo at the final chord relative to nominal (w)')
    ap.add_argument('--rit-q', type=float, default=RIT_Q, help='curve exponent q (2 = square)')
    ap.add_argument('--hold', type=float, default=HOLD,
                    help='extra lengthening factor of the final chord itself')
    ap.add_argument('--pre-stretch', type=float, default=PRE_STRETCH,
                    help='lengthening factor of the last subdivision before the final chord '
                         '(delays the chord onset)')
    args = ap.parse_args()

    path = os.path.abspath(args.path)
    base = os.path.splitext(os.path.basename(path))[0]
    out = args.out or os.path.join(_here, 'midi_out', base + '_motifs.mid')
    os.makedirs(os.path.dirname(out), exist_ok=True)

    nid_to_note, motifs, seqs, mei = analyse(path)
    chosen = select_motifs(motifs, min(args.max_motifs if args.min_count is None else len(MOTIF_PROGRAMS), len(MOTIF_PROGRAMS)),
                           args.min_count)

    fixed = sounding_midi(mei, nid_to_note)
    n_fix = sum(1 for nid, v in nid_to_note.items() if fixed.get(nid, v[4]) != v[4])
    print(f'pitch corrections (carried accidentals / key signature): {n_fix}')
    # nid -> (onset_q, dur_q, midi)
    all_notes = {nid: (v[5], v[3], fixed.get(nid, v[4])) for nid, v in nid_to_note.items()}
    sib = chord_siblings(mei, nid_to_note)
    n_sib = 0
    for sn, tn in sib.items():
        if sn in fixed:
            all_notes[sn] = (nid_to_note[tn][5], nid_to_note[tn][3], fixed[sn])
            n_sib += 1
    print(f'inner chord notes added to the background: {n_sib}')
    bg = sorted((o, d, m, 64) for o, d, m in all_notes.values())

    tracks = [(args.bg, 0, BACKGROUNDS[args.bg], bg)]
    group_of = [0]
    channels = [c for c in range(16) if c not in (0, 9)]
    print(f'{base}: {len(all_notes)} notes, {len(motifs)} motifs, {len(chosen)} smooth')
    for i, m in enumerate(chosen):
        prog, pname = MOTIF_PROGRAMS[i]
        nids, n_extra = extend_parallel(m, seqs)
        notes = sorted((*all_notes[n], 100) for n in nids if n in all_notes)
        label = f'M{i + 1} {pname}'
        tracks.append((label, channels[i % GROUP], prog, notes))
        group_of.append(i // GROUP)
        print(f'  M{i + 1}: {pname:12s} smooth counts {smooth_counts(m)} '
              f'(count {m.get("display_count", m["count"])}) notes {len(notes)} (+{n_extra} parallel) '
              f'query {m.get("queryStr", "")}')
    if args.chorale_voices:
        want = {tuple(int(x) for x in v.split('.')) for v in args.chorale_voices.split(',')}
        cn = set()
        for vk, seq in seqs:
            if tuple(vk) in want:
                for x in seq:
                    cn.add(x[2]); cn.add(x[3])
        cnotes = sorted((*all_notes[n], 100) for n in cn
                        if n in all_notes and all_notes[n][1] >= args.chorale_min_dur - 1e-9)
        free = [c for c in range(16) if c not in (0, 9) and c not in {t[1] for t in tracks}]
        tracks.append(('chorale organ', free[0], args.chorale_program, cnotes))
        group_of.append(0)
        print(f'  chorale: voices {sorted(want)} -> {len(cnotes)} notes, '
              f'first onset {min(n[0] for n in cnotes):g}, shortest {min(n[1] for n in cnotes):g} q')
    if args.double_voices:
        want = {tuple(int(x) for x in v.split('.')) for v in args.double_voices.split(',')}
        dn = set()
        for vk, seq in seqs:
            if tuple(vk) in want:
                for x in seq:
                    dn.add(x[2]); dn.add(x[3])
        def _shifted(m):
            m += args.double_shift
            while args.double_floor and m < args.double_floor:
                m += 12
            return m
        dnotes = sorted((o, d, _shifted(m), 100) for o, d, m in (all_notes[n] for n in dn if n in all_notes))
        free = [c for c in range(16) if c not in (0, 9) and c not in {t[1] for t in tracks}]
        tracks.append((args.double_name, free[0], args.double_program, dnotes))
        group_of.append(0)
        print(f'  doubling: voices {sorted(want)} -> {len(dnotes)} notes, shift {args.double_shift:+d} semitones, '
              f'range {min(n[2] for n in dnotes)}..{max(n[2] for n in dnotes)} (MIDI)')
    tempo_ev = None
    if args.rit_beats > 0:
        tempo_ev, tracks = final_ritardando(tracks, args.bpm, args.rit_beats,
                                            args.rit_final, args.rit_q, args.hold, args.pre_stretch)
        print(f'final ritardando: {args.rit_beats} quarters, end tempo {args.rit_final:.2f}x, '
              f'last chord held x{args.hold}, last subdivision before it x{args.pre_stretch}')
    # one MIDI file per group of GROUP motifs (group 0 also holds the background / chorale track);
    # all files share the tempo map, so rendered audio of the files can simply be summed
    stem, ext = os.path.splitext(out)
    for g in sorted(set(group_of)):
        part = [t for t, gg in zip(tracks, group_of) if gg == g]
        fn = out if g == 0 else f'{stem}_{chr(ord("A") + g)}{ext}'
        write_midi(fn, part, args.bpm, tempo_ev)
        print('written', fn)


if __name__ == '__main__':
    main()

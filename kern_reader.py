#!/usr/bin/env python3
"""
Kern Score Reader
- tkinter: file browser (main thread)
- HTTP server: serves rendered score HTML (background thread)
- Default browser: displays the score at http://localhost:PORT
"""

import json
import math
import multiprocessing
import os
import re
import threading
import warnings
import webbrowser
import xml.etree.ElementTree as ET
from collections import defaultdict
import tkinter as tk
from tkinter import ttk
from http.server import HTTPServer, BaseHTTPRequestHandler

warnings.filterwarnings("ignore")

import music21
import verovio

KERN_DIR     = os.path.join(os.path.dirname(__file__), "kern")
VEROVIO_DATA = os.path.join(os.path.dirname(verovio.__file__), "data")
SERVER_PORT  = 8765

# Only these subdirectories are shown in the file list
KERN_ALLOWED = (
    os.path.join("musedata", "bach", "keyboard", "wtc-1"),        # WTC preludes
    os.path.join("osu", "classical", "bach", "wtc-1"),             # WTC fugues
    os.path.join("osu", "classical", "bach", "inventions"),        # Inventions
    os.path.join("musedata", "bach", "chorales"),                   # Chorales
    os.path.join("users", "craig", "classical", "bach", "violin"), # Violin sonatas & partitas
    os.path.join("users", "craig", "classical", "bach", "cello"),  # Cello suites
    "permut",                                                       # Permuted files
)

_vtk = verovio.toolkit()
_vtk.setResourcePath(VEROVIO_DATA)

# ── shared state ──────────────────────────────────────────────────────────────

_state = {
    "html":    "<html><body style='font:16px sans-serif;padding:40px;color:#888'>"
               "Select a kern file in the browser panel.</body></html>",
    "version": "0",
}
_state_lock = threading.Lock()

# ── HTTP server ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # silence server logs

    def do_GET(self):
        with _state_lock:
            if self.path == "/version":
                body = _state["version"].encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
            else:
                body = _state["html"].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)


def start_server():
    srv = HTTPServer(("127.0.0.1", SERVER_PORT), Handler)
    srv.serve_forever()

# ── file discovery ────────────────────────────────────────────────────────────

def find_kern_files(root: str):
    files = []
    for dirpath, _, fnames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if not any(rel_dir.startswith(a) for a in KERN_ALLOWED):
            continue
        for fname in sorted(fnames):
            if fname.endswith(".krn"):
                full = os.path.join(dirpath, fname)
                rel  = os.path.relpath(full, root).replace("\\", "/")
                files.append((rel, full))
    files.sort(key=lambda x: x[0])
    return files

# ── validation ────────────────────────────────────────────────────────────────

def check_file(path: str):
    with open(path, "rb") as f:
        head = f.read(256)
    if not head.strip():
        raise RuntimeError("File is empty — not available in this collection")
    if b"<html" in head.lower() or b"Access Unsuccessful" in head:
        raise RuntimeError("Server returned an error page — file unavailable")

# ── render ────────────────────────────────────────────────────────────────────

_RELOAD_JS = """
<script>
var _ver = "{version}";
setInterval(function() {{
  fetch("/version").then(function(r){{return r.text();}}).then(function(v){{
    if(v !== _ver){{ _ver=v; location.reload(); }}
  }});
}}, 400);
</script>
"""

# ── motif analysis ────────────────────────────────────────────────────────────

_PITCH_CLASS   = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
_DIATONIC_STEP = {'c': 0, 'd': 1, 'e': 2, 'f': 3, 'g': 4, 'a': 5, 'b': 6}
_MOTIF_COLORS  = [
    '#e74c3c', '#2980b9', '#27ae60', '#e67e22',
    '#8e44ad', '#16a085', '#d81b60', '#f39c12',
]
_MEI_NS = 'http://www.music-encoding.org/ns/mei'
_XML_ID = '{http://www.w3.org/XML/1998/namespace}id'

_DUR_NAMES = {
    4.0: '&#119133;', 3.0: '&#119134;.', 2.0: '&#119134;',
    1.5: '&#9833;.',  1.0: '&#9833;',    0.75: '&#9834;.',
    0.5: '&#9834;',   0.375: '&#9835;.', 0.25: '&#9835;',
}
_DIATONIC_NAMES = ['0', '1', '2', '3', '4', '5', '6']


def _interval_label(dsteps, dur_q):
    """Human-readable label for one interval+duration step (diatonic)."""
    abs_d = abs(dsteps)
    octaves = abs_d // 7
    rem     = abs_d % 7
    iname = _DIATONIC_NAMES[rem] if rem < 7 else str(rem)
    if octaves:
        iname += f'+{octaves}о'
    arrow = '&uarr;' if dsteps > 0 else ('&darr;' if dsteps < 0 else '&mdash;')
    dname = _DUR_NAMES.get(dur_q, f'{dur_q}q')
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
    """
    if dur_q <= 0 or beat_dur_q <= 0:
        return 0
    n_per_beat = max(1, round(beat_dur_q / dur_q))
    if n_per_beat <= 1:
        return 0
    pos_in_beat = onset_q % beat_dur_q
    return int(round(pos_in_beat / dur_q)) % n_per_beat



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
        # Compound meter (9/8, 6/8, 12/8 …): beat = dotted note = 3 subdivisions
        bdq = (4.0 / mu * 3) if (mc % 3 == 0 and mc > 3 and mu >= 8) else (4.0 / mu)
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

    def proc_note(n, dur_override=None, dots_override=None, onset=0.0):
        nid   = n.get(_XML_ID)
        pname = n.get('pname', '')
        if not pname or not nid:
            return None
        tie = n.get('tie', '')
        if 'm' in tie or 't' in tie:   # skip tied continuation — but still counts time
            return None
        oct_str = n.get('oct', '4')
        dur     = dur_override if dur_override is not None else n.get('dur', '4')
        dots    = dots_override if dots_override is not None else int(n.get('dots', 0))
        accid   = n.get('accid') or n.get('accid.ges')
        return (nid, pname, int(oct_str), _to_quarters(dur, dots),
                _to_midi(pname, oct_str, accid), onset)

    def iter_events(el):
        """Yield all events in order, recursing into beam/tuplet containers."""
        for child in el:
            t = child.tag.split('}')[-1]
            if t in ('beam', 'tuplet', 'ligature', 'ftrem', 'btrem'):
                yield from iter_events(child)
            else:
                yield child

    voices        = defaultdict(list)
    measure_onset = 0.0

    for measure_el in tree.iter(tag_pfx + 'measure'):
        # Pick up meter changes inside the measure
        for ms in measure_el.iter(tag_pfx + 'meterSig'):
            c = ms.get('count'); u = ms.get('unit')
            if c and u:
                beats_per_measure, beat_dur_q = _parse_meter(c, u)
                break

        for staff_el in measure_el.findall(tag_pfx + 'staff'):
            sn = int(staff_el.get('n', 1))
            for layer_el in staff_el.findall(tag_pfx + 'layer'):
                ln  = int(layer_el.get('n', 1))
                key = (sn, ln)
                pos = 0.0   # position within measure

                for child in iter_events(layer_el):
                    t = child.tag.split('}')[-1]
                    onset = measure_onset + pos
                    if t == 'note':
                        dur = _to_quarters(child.get('dur', '4'), int(child.get('dots', 0)))
                        if child.get('grace'):   # grace note (q/Q in kern) — skip, no pos advance
                            pass
                        else:
                            e = proc_note(child, onset=onset)
                            if e:
                                voices[key].append(e)
                            pos += dur
                    elif t == 'chord':
                        dur = _to_quarters(child.get('dur', '4'), int(child.get('dots', 0)))
                        if child.get('grace'):   # grace chord — skip
                            pass
                        else:
                            cands = [proc_note(n,
                                               dur_override=child.get('dur', '4'),
                                               dots_override=int(child.get('dots', 0)),
                                               onset=onset)
                                     for n in child.findall(tag_pfx + 'note')]
                            cands = [c for c in cands if c]
                            if cands:
                                voices[key].append(max(cands, key=lambda x: x[4]))
                            pos += dur
                    elif t in ('rest', 'space'):
                        dur = _to_quarters(child.get('dur', '4'), int(child.get('dots', 0)))
                        pos += dur
                    elif t == 'mRest':
                        pos += beats_per_measure

        measure_onset += beats_per_measure

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
    result = {}
    for key, notes in voices.items():
        result[key] = _merge_ornamental_slurs(notes, slur_ends)
    return result, beat_dur_q


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


def _interval_seq(notes, beat_dur_q=1.0):
    """
    notes: [(nid, pname, oct, dur, midi, onset), ...]
    Returns [(diatonic_interval, dur_of_first_note, nid_first, nid_second, onset_quarters, phase), ...]
    phase: metric phase of the first note within its beat (0/1 for binary, 0/1/2 for triplets/compound).
    """
    result = []
    for i in range(len(notes) - 1):
        nid0, pname0, oct0, dur0, _, onset0 = notes[i]
        nid1, pname1, oct1, _,   _, _       = notes[i + 1]
        dp0 = oct0 * 7 + _DIATONIC_STEP.get(pname0.lower(), 0)
        dp1 = oct1 * 7 + _DIATONIC_STEP.get(pname1.lower(), 0)
        phase0 = _metric_phase(onset0, dur0, beat_dur_q)
        result.append((dp1 - dp0, dur0, nid0, nid1, onset0, phase0))
    return result


def _find_motifs(all_seqs, min_len=2, min_count=2, max_motifs=50, max_pat_len=16):
    """
    all_seqs: [(voice_key, interval_seq), ...]
    Returns list of {'pattern': tuple, 'occurrences': [[nid, ...], ...]}

    Pattern key = (body, start_phase) where:
      - body = tuple of (interval, dur) pairs — rhythm+pitch content
      - start_phase = metric phase of the first note (0/1 for binary, 0/1/2 for triplets)
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
            start_phase = seq[start][5]
            for ln in range(min_len, min(max_pat_len, n - start) + 1):
                body  = tuple((s[0], s[1]) for s in seq[start:start + ln])
                key   = (body, start_phase)
                nids  = [seq[start][2]] + [seq[start + k][3] for k in range(ln)]
                onset = seq[start][4]
                pat_voice_raw[key][vi].append((start, nids, onset))

    # Step 2: greedy non-overlapping selection per voice + cross-voice same-beat dedup
    pat_occs = defaultdict(list)
    for (body, phase), voice_dict in pat_voice_raw.items():
        ln = len(body)
        all_with_onset = []
        for _vi, positions in voice_dict.items():
            last_end = -1
            for start, nids, onset in positions:
                if start >= last_end:
                    all_with_onset.append((onset, nids))
                    last_end = start + ln + 1
        all_with_onset.sort(key=lambda x: x[0])
        seen_onsets = set()
        for onset, nids in all_with_onset:
            onset_q = round(onset * 16)
            if onset_q not in seen_onsets:
                pat_occs[(body, phase)].append(nids)
                seen_onsets.add(onset_q)

    candidates = [((body, phase), occs)
                  for (body, phase), occs in pat_occs.items()
                  if len(occs) >= min_count]
    if not candidates:
        return []

    candidates.sort(key=lambda x: (len(x[1]), len(x[0][0])), reverse=True)

    def _is_window_shift(p, q):
        """True if p and q (same length, plain body tuples) are overlapping windows."""
        if len(p) != len(q):
            return False
        return any(p[k:] == q[:-k] for k in range(1, len(p)))

    # Greedy: skip if body is a sub-pattern or window-shift of an already-selected body.
    # Bodies of different phases are NOT considered duplicates of each other.
    selected        = []
    selected_bodies = []
    for (body, phase), occs in candidates:
        if len(selected) >= max_motifs:
            break
        dominated = any(
            (len(sb) > len(body) and
             any(sb[i:i + len(body)] == body for i in range(len(sb) - len(body) + 1)))
            or _is_window_shift(sb, body)
            for sb in selected_bodies
        )
        if not dominated:
            selected.append({'pattern': body, 'occurrences': occs, 'phase': phase})
            selected_bodies.append(body)

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
    voices, _bdq = _voice_notes_from_mei(mei_str)
    labels = {}
    for _vk, notes in voices.items():
        for nid, _pname, _oct, dur, _midi, onset in notes:
            pos = round((onset % bpm) * 16) / 16
            phase = _metric_phase(onset, dur, _bdq)
            labels[nid] = f'{pos:g}|{phase}'
    return labels


def analyze_motifs(vtk, mei_str=None):
    """
    Run motif analysis on the currently-loaded verovio score.
    Returns list of:
      {'color': str, 'occs': [[nid, ...], ...], 'count': int, 'length': int}
    where each inner list is the note IDs of one occurrence of the motif.
    """
    try:
        if mei_str is None:
            mei_str = vtk.getMEI()
        voices, beat_dur_q = _voice_notes_from_mei(mei_str)
        all_seqs = [(vk, _interval_seq(notes, beat_dur_q))
                    for vk, notes in voices.items()
                    if len(notes) >= 4]
        motifs = _find_motifs(all_seqs)
        result = []
        for i, m in enumerate(motifs):
            steps = [_interval_label(iv, dur) for iv, dur in m['pattern']]
            phase = m.get('phase', 0)
            phase_pfx = {0: '', 1: '_|', 2: '_|_|'}.get(phase, '')
            result.append({
                'color':   _MOTIF_COLORS[i % len(_MOTIF_COLORS)],
                'occs':    m['occurrences'],
                'count':   len(m['occurrences']),
                'length':  len(m['pattern']) + 1,
                'pattern': steps,
                'phase_pfx': phase_pfx,
            })
        return result
    except Exception as e:
        print(f"[motif] {e}")
        return []


# ── grand staff preparation ───────────────────────────────────────────────────

# ── beam marker injection ─────────────────────────────────────────────────────

_BEAMABLE = frozenset({0.5, 0.25, 0.125, 0.0625})   # 8th, 16th, 32nd, 64th (in quarter notes)

def _kern_dur(tok):
    """Return (duration_in_quarters, is_rest) for a kern note/rest token, or (None, None)."""
    tok = tok.strip()
    if not tok or tok in ('.', '') or tok.startswith('*') or tok.startswith('!'):
        return None, None
    m = re.match(r'^(\d+)(\.*)[a-gA-Gr]', tok)
    if not m:
        return None, None
    dn = int(m.group(1))
    if dn == 0:
        return None, None
    base = 4.0 / dn
    total = base
    for _ in m.group(2):
        base /= 2
        total += base
    return round(total * 128) / 128, tok.strip().endswith('r') or 'r' in re.sub(r'^\d+\.*', '', tok)


def add_beam_markers(content: str) -> str:
    """
    Add L/J beam markers to kern files that have none.
    Groups beamable notes (8th–64th) within each beat per spine.
    8th notes → L/J,  16th → LL/JJ,  32nd → LLL/JJJ.
    """
    lines = content.splitlines(keepends=True)

    # Skip if beam markers already present
    for line in lines:
        if line.startswith(('!', '*', '=')) or not line.strip():
            continue
        if any('L' in t or 'J' in t for t in line.split()):
            return content

    # Beat duration in quarter notes (from time signature)
    beat_dur = 1.0
    for line in lines:
        for tok in line.strip().split('\t'):
            m = re.match(r'^\*M\d+/(\d+)$', tok)
            if m:
                beat_dur = 4.0 / int(m.group(1))
                break

    # Spine count from header
    header_idx = next((i for i, l in enumerate(lines) if l.startswith('**')), None)
    if header_idx is None:
        return content
    n_cols = len(lines[header_idx].rstrip('\n\r').split('\t'))

    # Collect note events per spine: (line_idx, dur, beat_pos_in_measure, measure_idx)
    spine_pos = [0.0] * n_cols
    events    = [[] for _ in range(n_cols)]
    measure   = 0

    for li, line in enumerate(lines):
        raw = line.rstrip('\n\r')
        if raw.startswith('='):
            spine_pos = [0.0] * n_cols
            measure  += 1
            continue
        if raw.startswith(('!', '*')) or not raw.strip():
            continue
        for col, tok in enumerate(raw.split('\t')[:n_cols]):
            dur, is_rest = _kern_dur(tok)
            if dur is None:
                continue
            events[col].append((li, dur, spine_pos[col], measure, is_rest))
            spine_pos[col] += dur

    # Build beam groups: consecutive beamable notes within same beat AND same measure
    markers = {}   # (li, col) -> suffix string

    for col, evts in enumerate(events):
        i = 0
        while i < len(evts):
            li, dur, pos, meas, is_rest = evts[i]
            if dur not in _BEAMABLE:
                i += 1
                continue
            beat_start = (pos // beat_dur) * beat_dur
            beat_end   = beat_start + beat_dur

            group = [(li, dur, is_rest)]
            j = i + 1
            while j < len(evts):
                lj, dj, posj, measj, restj = evts[j]
                if measj != meas or posj >= beat_end - 1e-9 or dj not in _BEAMABLE:
                    break
                group.append((lj, dj, restj))
                j += 1

            if len(group) >= 2:
                # Trim leading and trailing rests — beam markers go on actual notes only
                note_indices = [k for k, g in enumerate(group) if not g[2]]
                if len(note_indices) >= 2:
                    min_d = min(g[1] for g in group)
                    if min_d <= 4.0 / 32:
                        s, e = 'LLL', 'JJJ'
                    elif min_d <= 4.0 / 16:
                        s, e = 'LL', 'JJ'
                    else:
                        s, e = 'L', 'J'
                    k0 = (group[note_indices[0]][0],  col)
                    ke = (group[note_indices[-1]][0], col)
                    markers[k0] = markers.get(k0, '') + s
                    markers[ke] = markers.get(ke, '') + e

            i = j if len(group) >= 2 else i + 1

    if not markers:
        return content

    # Apply markers to tokens
    result = []
    for li, line in enumerate(lines):
        raw = line.rstrip('\n\r')
        tokens = raw.split('\t')
        changed = False
        for col in range(min(len(tokens), n_cols)):
            if (li, col) in markers:
                tokens[col] = tokens[col].strip() + markers[(li, col)]
                changed = True
        if changed:
            result.append('\t'.join(tokens) + line[len(raw):])
        else:
            result.append(line)
    return ''.join(result)


def prepare_grand_staff(content: str) -> str:
    """
    Ensure kern content will render as a grand staff (treble + bass staves).

    Multi-spine files (≥2 **kern columns): add *staff/*clef if absent.

    Single-spine files with *^ splits: convert to 2-spine grand-staff format.
      The first *^ split is absorbed into the 2-spine header; all subsequent
      splits stay in place as inner voice splits within the treble spine.
      The rightmost subspine (from the first *^ split) becomes the bass spine.
      Note data columns are unchanged — only the header is restructured.
    """
    lines = content.splitlines(keepends=True)

    header_idx = next(
        (i for i, l in enumerate(lines) if l.startswith("**kern")), None
    )
    if header_idx is None:
        return content

    n_initial = lines[header_idx].rstrip().split("\t").count("**kern")

    # ── multi-spine: just add *staff/*clef if missing ────────────────────────
    if n_initial >= 2:
        if any(l.startswith("*staff") for l in lines):
            return content
        # Build records that match the TOTAL column count (including non-**kern spines)
        header_tokens = lines[header_idx].rstrip().split("\t")
        n_total       = len(header_tokens)
        kern_idxs     = [i for i, t in enumerate(header_tokens) if t == "**kern"]
        n_kern        = len(kern_idxs)

        staff_row = ["*"] * n_total
        clef_row  = ["*"] * n_total
        for rank, col in enumerate(kern_idxs):
            staff_row[col] = "*staff1" if rank < n_kern - 1 else "*staff2"
            clef_row[col]  = "*clefG2" if rank < n_kern - 1 else "*clefF4"

        # Check if next non-empty line already has a *clef token
        has_clef = False
        for j in range(header_idx + 1, len(lines)):
            raw = lines[j].rstrip("\n\r")
            if raw:
                has_clef = any(t.startswith("*clef") for t in raw.split("\t"))
                break

        ins = ["\t".join(staff_row) + "\n"]
        if not has_clef:
            ins.append("\t".join(clef_row) + "\n")
        lines = lines[:header_idx + 1] + ins + lines[header_idx + 1:]
        return "".join(lines)

    # ── single spine: find *^ splits before data ─────────────────────────────
    if any(l.startswith("*staff") for l in lines):
        return content

    # If the file has non-kern spines (e.g. **dynam, **text), leave it unchanged —
    # duplicating rows would produce wrong column counts.
    header_tokens = lines[header_idx].rstrip().split("\t")
    if len(header_tokens) > n_initial:
        return content

    split_idxs = []
    spine_count = 1

    for i in range(header_idx + 1, len(lines)):
        raw = lines[i].rstrip("\n\r")
        if not raw or raw.startswith("!"):
            continue
        tokens = raw.split("\t")
        if all(t in ("*^", "*") for t in tokens):
            split_idxs.append(i)
            spine_count = sum(2 if t == "*^" else 1 for t in tokens)
        elif not raw.startswith("*") and not raw.startswith("=") and not raw.startswith("!"):
            break  # reached actual note data

    if not split_idxs or spine_count < 2:
        return content

    first_split = split_idxs[0]

    # ── build 2-spine grand-staff file ───────────────────────────────────────
    result = []

    # New header: 2 **kern spines + staff + clef
    result.append("**kern\t**kern\n")
    result.append("*staff1\t*staff2\n")
    result.append("*clefG2\t*clefF4\n")

    # Duplicate single-column header records before the first *^
    for i in range(header_idx + 1, first_split):
        raw = lines[i].rstrip("\n\r")
        if not raw:
            result.append("\n")
            continue
        if raw.startswith("!!"):
            result.append(lines[i])
            continue
        if raw.startswith("*clef"):
            continue  # already inserted above
        result.append(f"{raw}\t{raw}\n")

    # Drop first *^ (absorbed into the 2-spine header).
    # Keep all subsequent splits (inner voice splits within the treble spine).
    for k, idx in enumerate(split_idxs):
        if k == 0:
            continue
        result.append(lines[idx])

    # Copy everything from after the last split to end of file unchanged.
    for i in range(split_idxs[-1] + 1, len(lines)):
        result.append(lines[i])

    return "".join(result)


def render_score(path: str, version: str = "1") -> tuple:
    """Returns (html, n_pages, version). Raises RuntimeError on failure."""
    check_file(path)
    _vtk.setOptions({
        "pageWidth":        2200,
        "adjustPageHeight": True,
        "scale":            35,
        "font":             "Leipzig",
    })
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        content = prepare_grand_staff(content)
        content = add_beam_markers(content)
        ok = _vtk.loadData(content)
        if not ok:
            raise RuntimeError("verovio could not parse this file")
    except Exception as e:
        raise RuntimeError(f"Parse error: {e}")

    n_pages = _vtk.getPageCount()
    svgs = [_vtk.renderToSVG(p) for p in range(1, n_pages + 1)]
    pages = "\n".join(f'<div style="margin-bottom:24px">{s}</div>' for s in svgs)

    # ── motif analysis ────────────────────────────────────────────────────────
    mei_str = _vtk.getMEI()
    motifs = analyze_motifs(_vtk, mei_str=mei_str)
    motifs.sort(key=lambda m: m['count'], reverse=True)

    def _is_smooth(k):
        """True if k = 2^a * 3^b (a,b >= 0)."""
        if k <= 0:
            return False
        while k % 2 == 0:
            k //= 2
        while k % 3 == 0:
            k //= 3
        return k == 1

    reload_js = _RELOAD_JS.format(version=version)

    # Build legend + highlight script
    legend_html  = ""
    motif_script = ""
    if motifs:
        def _row(i, m):
            pfx = m['phase_pfx']
            phase_html = (f'<sub style="letter-spacing:-1px;color:#aaa">{pfx}</sub>'
                          if pfx else '')
            cnt = m['count']
            cnt_html = (f'<b>{cnt}</b>' if _is_smooth(cnt) and cnt >= 8 else str(cnt))
            return (
                f'<tr data-midx="{i}" style="border-bottom:1px solid #e8e8e8;cursor:pointer" '
                f'onmouseover="this.style.background=\'#f0f0f0\'" '
                f'onmouseout="if(this.getAttribute(\'data-active\')!==\'1\')this.style.background=\'\'">'
                f'<td style="padding:5px 10px 5px 0;white-space:nowrap">'
                f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
                f'background:{m["color"]};margin-right:5px;vertical-align:middle"></span>'
                f'<b>M{i+1}</b>{phase_html}</td>'
                f'<td style="padding:5px 16px 5px 0;font-family:monospace;font-size:11px">'
                f'{" &nbsp; ".join(m["pattern"])}</td>'
                f'<td style="padding:5px 10px 5px 0;text-align:center">&times;{cnt_html}</td>'
                f'<td style="padding:5px 0;text-align:center;color:#888">{m["length"]}</td>'
                f'</tr>'
            )
        rows = "".join(_row(i, m) for i, m in enumerate(motifs))
        legend_html = (
            f'<div style="font:12px sans-serif;color:#333;margin-bottom:12px;'
            f'padding:8px 14px 10px;background:#fafafa;border:1px solid #ddd;border-radius:5px">'
            f'<div style="font-weight:bold;font-size:13px;margin-bottom:4px">&#127925; Мотивы '
            f'<span style="font-weight:normal;font-size:10px;color:#999">'
            f'(кликни по строке чтобы выделить вхождения)</span></div>'
            f'<table id="motif-dict" style="border-collapse:collapse">'
            f'<thead><tr style="color:#888;font-size:10px;border-bottom:2px solid #ccc">'
            f'<th style="text-align:left;padding:0 10px 4px 0">Мотив</th>'
            f'<th style="text-align:left;padding:0 16px 4px 0">Паттерн (&uarr;&darr; интервал, длит.)</th>'
            f'<th style="padding:0 10px 4px 0">Вхожд.</th>'
            f'<th style="padding:0 0 4px 0">Нот</th>'
            f'</tr></thead>'
            f'<tbody>{rows}</tbody>'
            f'</table></div>'
        )
        motif_data  = [{"color": m["color"], "occs": m["occs"]} for m in motifs]
        motif_json  = json.dumps(motif_data)
        motif_script = f"""<script>
(function(){{
var motifs={motif_json};
var activeIdx=-1;
var drawnRects=[];

function clearRects(){{
  drawnRects.forEach(function(r){{if(r.parentNode)r.parentNode.removeChild(r);}});
  drawnRects=[];
}}

function clientToSVG(svg,cx,cy){{
  var pt=svg.createSVGPoint();
  pt.x=cx; pt.y=cy;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}}

function drawBoxes(mIdx){{
  clearRects();
  var m=motifs[mIdx];
  m.occs.forEach(function(occ,occIdx){{
    // Group note rects by (svg page, verovio <g class="system"> ancestor).
    // Pixel-gap heuristics are unreliable: verovio bounding rects include beams
    // so .height and .bottom can extend far, making threshold-based splits fail.
    var svgList=[]; var svgSysGroups=[];
    occ.forEach(function(id){{
      var el=document.getElementById(id); if(!el)return;
      try{{
        var svg=el.closest('svg');
        var cr=el.getBoundingClientRect();
        if(cr.width<=0&&cr.height<=0)return;
        var si=svgList.indexOf(svg);
        if(si===-1){{si=svgList.length; svgList.push(svg); svgSysGroups.push([]);}}
        // Walk up DOM to find <g class="system"> ancestor
        var sys=el.parentNode;
        while(sys&&sys!==svg){{
          if(sys.nodeType===1&&sys.getAttribute('class')==='system')break;
          sys=sys.parentNode;
        }}
        if(!sys||sys===svg)sys=null;
        var found=false;
        for(var gi=0;gi<svgSysGroups[si].length;gi++){{
          if(svgSysGroups[si][gi].sys===sys){{
            svgSysGroups[si][gi].rects.push(cr); found=true; break;
          }}
        }}
        if(!found)svgSysGroups[si].push({{sys:sys, rects:[cr]}});
      }}catch(e){{}}
    }});
    if(svgList.length===0)return;
    var totalSvgs=svgList.length;
    svgList.forEach(function(svg,si){{
      // Sort system groups top-to-bottom by min top of their rects
      svgSysGroups[si].sort(function(a,b){{
        var ta=Math.min.apply(null,a.rects.map(function(r){{return r.top;}}));
        var tb=Math.min.apply(null,b.rects.map(function(r){{return r.top;}}));
        return ta-tb;
      }});
      var groups=svgSysGroups[si].map(function(g){{return g.rects;}});
      var totalGroups=groups.length;
      groups.forEach(function(grp,gi){{
        var cl=Math.min.apply(null,grp.map(function(r){{return r.left;}}));
        var ct=Math.min.apply(null,grp.map(function(r){{return r.top;}}));
        var crr=Math.max.apply(null,grp.map(function(r){{return r.right;}}));
        var cb=Math.max.apply(null,grp.map(function(r){{return r.bottom;}}));
        var p1=clientToSVG(svg,cl,ct);
        var p2=clientToSVG(svg,crr,cb);
        var h=p2.y-p1.y; var xpad=h*0.1; var ypad=h*0.4;
        var x1=p1.x-xpad; var y1=p1.y-ypad;
        var x2=p2.x+xpad; var y2=p2.y+ypad;
        var isVeryFirst=(si===0&&gi===0);
        var isVeryLast=(si===totalSvgs-1&&gi===totalGroups-1);
        var isOnly=(totalSvgs===1&&totalGroups===1);
        var d;
        if(isOnly){{
          d='M'+x1+','+y1+'H'+x2+'V'+y2+'H'+x1+'Z';
        }}else if(isVeryFirst){{
          d='M'+x2+','+y1+'H'+x1+'V'+y2+'H'+x2;
        }}else if(isVeryLast){{
          d='M'+x1+','+y1+'H'+x2+'V'+y2+'H'+x1;
        }}else{{
          d='M'+x1+','+y1+'H'+x2+' M'+x1+','+y2+'H'+x2;
        }}
        var path=document.createElementNS('http://www.w3.org/2000/svg','path');
        path.setAttribute('d',d);
        path.setAttribute('fill','none');
        path.setAttribute('stroke',m.color);
        path.setAttribute('stroke-width','2');
        path.setAttribute('vector-effect','non-scaling-stroke');
        path.setAttribute('pointer-events','none');
        svg.appendChild(path);
        drawnRects.push(path);
        // Label: occurrence number above the first group of each occurrence
        if(isVeryFirst||isOnly){{
          var numSz=ypad*1.5;
          var txt=document.createElementNS('http://www.w3.org/2000/svg','text');
          txt.textContent=String(occIdx+1);
          txt.setAttribute('x', String(x1+numSz*0.1));
          txt.setAttribute('y', String(y1-numSz*0.15));
          txt.setAttribute('fill', m.color);
          txt.setAttribute('font-size', String(numSz));
          txt.setAttribute('font-family', 'sans-serif');
          txt.setAttribute('font-weight', 'bold');
          txt.setAttribute('pointer-events', 'none');
          svg.appendChild(txt);
          drawnRects.push(txt);
        }}
      }});
    }});
  }});
}}

function highlight(){{
  motifs.forEach(function(m){{
    m.occs.forEach(function(occ){{
      occ.forEach(function(id){{
        var el=document.getElementById(id);
        if(el)try{{el.setAttribute('fill',m.color);}}catch(e){{}}
      }});
    }});
  }});
  // attach click handlers
  document.querySelectorAll('#motif-dict tr[data-midx]').forEach(function(row){{
    row.addEventListener('click',function(){{
      var idx=parseInt(this.getAttribute('data-midx'));
      document.querySelectorAll('#motif-dict tr[data-midx]').forEach(function(r){{
        r.style.background=''; r.setAttribute('data-active','0');
      }});
      if(activeIdx===idx){{
        clearRects(); activeIdx=-1;
      }}else{{
        activeIdx=idx;
        this.style.background='#e8f0fe';
        this.setAttribute('data-active','1');
        drawBoxes(idx);
      }}
    }});
  }});
}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',highlight);
else highlight();
}})();
</script>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ background:#fff; margin:0; padding:16px 24px; overflow-x:auto; }}
  svg  {{ display:block; height:auto; }}
  .fn  {{ font:11px monospace; color:#999; margin-bottom:6px; }}
</style>
{reload_js}
{motif_script}
</head>
<body>
<div class="fn">{os.path.basename(path)}</div>
{legend_html}
{pages}
</body>
</html>"""
    return html, n_pages, version

# ── background render + update ────────────────────────────────────────────────

def _render_worker(path: str, version: str, queue):
    """Runs in a subprocess to isolate verovio segfaults from the main process."""
    try:
        html, n_pages, ver = render_score(path, version)
        queue.put(('ok', html, n_pages, ver))
    except Exception as e:
        queue.put(('error', str(e)))


def load_file_bg(path: str, status_cb):
    with _state_lock:
        next_ver = str(int(_state["version"]) + 1)

    ctx   = multiprocessing.get_context('spawn')
    queue = ctx.Queue()
    proc  = ctx.Process(target=_render_worker, args=(path, next_ver, queue), daemon=True)
    proc.start()

    # Read result BEFORE joining — large HTML payloads fill the pipe buffer
    # causing the child to block on queue.put(), creating a deadlock if we join first.
    try:
        result = queue.get(timeout=60)
    except Exception:
        proc.terminate()
        # Check if it crashed vs timed out
        proc.join(timeout=3)
        if proc.exitcode not in (None, 0):
            status_cb(f"ERROR: verovio crashed (exit {proc.exitcode})", error=True)
        else:
            status_cb("ERROR: render timed out", error=True)
        return

    proc.join(timeout=5)   # child should exit quickly now

    if result[0] == 'error':
        status_cb(f"ERROR: {result[1]}", error=True)
        return

    _, html, n_pages, ver = result
    with _state_lock:
        _state["html"]    = html
        _state["version"] = ver
    status_cb(f"{n_pages} page{'s' if n_pages != 1 else ''} — {os.path.basename(path)}")

# ── metadata ──────────────────────────────────────────────────────────────────

def get_metadata(path: str) -> dict:
    info = {}
    try:
        score = music21.converter.parse(path)
        md = score.metadata
        if md:
            info["title"]    = md.title or ""
            info["composer"] = md.composer or ""
        parts = list(score.parts) if hasattr(score, "parts") else []
        info["parts"]    = len(parts)
        info["duration"] = f"{score.highestTime:.1f} beats"
        ts = list(score.recurse().getElementsByClass(music21.meter.TimeSignature))
        info["time_sig"] = str(ts[0]) if ts else ""
        ks = list(score.recurse().getElementsByClass(music21.key.KeySignature))
        info["key"] = str(ks[0]) if ks else ""
    except Exception:
        pass
    return info

# ── tkinter browser ───────────────────────────────────────────────────────────

class FileBrowser(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Kern Files")
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        self.geometry(f"480x800+{sw-480}+0")   # right edge, top
        self.minsize(320, 400)
        self.resizable(True, True)
        self.configure(bg="#1e1e2e")

        self._files        = find_kern_files(KERN_DIR)
        self._current_path = None

        self._build_ui()
        self._populate_list()

    def _build_ui(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("S.TFrame",  background="#252535")
        s.configure("TLabel",    background="#252535", foreground="#cdd6f4",
                     font=("Segoe UI", 9))
        s.configure("H.TLabel",  background="#252535", foreground="#cba6f7",
                     font=("Segoe UI", 10, "bold"))
        s.configure("TEntry",    fieldbackground="#313244", foreground="#cdd6f4",
                     insertcolor="#cdd6f4")
        s.configure("Treeview",  background="#252535", foreground="#cdd6f4",
                     fieldbackground="#252535", rowheight=22,
                     font=("Segoe UI", 9))
        s.map("Treeview", background=[("selected", "#45475a")])

        # metadata strip (top)
        meta = tk.Frame(self, bg="#1a1a2a", pady=4)
        meta.pack(fill=tk.X, padx=6, pady=(6, 0))
        self._meta_labels = {}
        for key in ("title", "composer", "key", "time_sig", "parts", "duration"):
            f = tk.Frame(meta, bg="#1a1a2a")
            f.pack(side=tk.LEFT, padx=8)
            tk.Label(f, text=key.upper().replace("_", " "),
                     bg="#1a1a2a", fg="#6c7086",
                     font=("Segoe UI", 6, "bold")).pack(anchor="w")
            lbl = tk.Label(f, text="—", bg="#1a1a2a", fg="#89dceb",
                           font=("Segoe UI", 8))
            lbl.pack(anchor="w")
            self._meta_labels[key] = lbl

        # file list
        outer = ttk.Frame(self, style="S.TFrame")
        outer.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        ttk.Label(outer, text="KERN FILES", style="H.TLabel").pack(
            pady=(8, 4), padx=8, anchor="w")

        sv = tk.StringVar()
        sv.trace_add("write", lambda *_: self._filter(sv.get()))
        ttk.Entry(outer, textvariable=sv).pack(fill=tk.X, padx=8, pady=(0, 6))

        self._tree = ttk.Treeview(outer, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))
        sb.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._count_var = tk.StringVar()
        ttk.Label(outer, textvariable=self._count_var,
                  background="#252535", foreground="#6c7086",
                  font=("Segoe UI", 8)).pack(pady=(2, 0))

        # status
        self._status = tk.Text(outer, height=2, bg="#181825", fg="#89dceb",
                               font=("Consolas", 8), relief=tk.FLAT,
                               state=tk.DISABLED, wrap=tk.WORD)
        self._status.pack(fill=tk.X, padx=8, pady=(4, 6))

    def _populate_list(self, files=None):
        self._tree.delete(*self._tree.get_children())
        for rel, full in (files or self._files):
            self._tree.insert("", tk.END, text=rel, values=(full,))
        n = len(files) if files is not None else len(self._files)
        self._count_var.set(f"{n} file{'s' if n != 1 else ''}")

    def _filter(self, q: str):
        q = q.lower()
        self._populate_list([(r, f) for r, f in self._files if q in r.lower()])

    def _on_select(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        path = self._tree.item(sel[0], "values")[0]
        if path == self._current_path:
            return
        self._current_path = path
        self._set_status("Rendering…")
        self._update_meta(path)
        threading.Thread(
            target=load_file_bg,
            args=(path, self._status_from_thread),
            daemon=True,
        ).start()

    def _status_from_thread(self, msg, error=False):
        self.after(0, lambda: self._set_status(msg, error=error))

    def _set_status(self, msg, error=False):
        color = "#f38ba8" if error else "#89dceb"
        self._status.config(state=tk.NORMAL, fg=color)
        self._status.delete("1.0", tk.END)
        self._status.insert(tk.END, msg)
        self._status.config(state=tk.DISABLED)

    def _update_meta(self, path):
        try:
            info = get_metadata(path)
        except Exception:
            info = {}
        for k, lbl in self._meta_labels.items():
            lbl.config(text=str(info.get(k, "")) or "—")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    multiprocessing.freeze_support()   # needed for Windows spawn

    if not os.path.isdir(KERN_DIR):
        print(f"kern/ directory not found: {KERN_DIR}")
        raise SystemExit(1)

    # start HTTP server
    threading.Thread(target=start_server, daemon=True).start()

    # Create browser window first (needs screen size from tkinter)
    _app = FileBrowser()
    _sw  = _app.winfo_screenwidth()
    _sh  = _app.winfo_screenheight()
    _bw  = _sw - 480   # browser fills the left part

    _url = f"http://127.0.0.1:{SERVER_PORT}/"
    _browser_opened = False
    for _exe in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]:
        if os.path.exists(_exe):
            import subprocess
            subprocess.Popen([_exe, "--new-window",
                              "--window-position=0,0",
                              f"--window-size={_bw},{_sh}", _url])
            _browser_opened = True
            break
    if not _browser_opened:
        webbrowser.open(_url)

    _app.mainloop()

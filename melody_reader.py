#!/usr/bin/env python3
"""
Melody Reader — click start/end notes in one voice, see inertia-based continuations.
Score window: port 8767.  Prediction window: port 8768.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer
import warnings

warnings.filterwarnings("ignore")

# ── paths ──────────────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
_READER = os.path.join(_HERE, "reader")
sys.path.insert(0, _READER)

import verovio
from motif_analysis import (
    _MEI_NS, _XML_ID, _DIATONIC_STEP, _PITCH_CLASS,
    _voice_notes_from_mei, _to_quarters, _to_midi,
)
from app import (
    KERN_DIR, find_kern_files, find_lilypond_files, find_xml_files,
    _mini_staff_svg, _beam_groups_from_mei, check_file,
)

VEROVIO_DATA = os.path.join(os.path.dirname(verovio.__file__), "data")
_vtk = verovio.toolkit()
_vtk.setResourcePath(VEROVIO_DATA)

SCORE_PORT = 8767
PRED_PORT  = 8768


# ── static HTML helpers (defined before _state) ────────────────────────────────

def _welcome_html(ver):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script>(function(){{var c="{ver}";var es=new EventSource('/events');
es.onmessage=function(e){{if(e.data!==c){{es.close();
window.location.replace('/?t='+Date.now());}}}};
}})();</script></head>
<body style='font:16px sans-serif;padding:40px;color:#888'>
Выберите файл в панели слева.</body></html>"""


def _pred_placeholder(ver="0"):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script>(function(){{
  var c="{ver}";
  var es=new EventSource('/events');
  es.onmessage=function(e){{if(e.data!==c){{es.close();window.location.replace('/?t='+Date.now());}}}};
}})();</script>
</head>
<body style='font:16px sans-serif;padding:40px;color:#888'>
Выделите фрагмент мелодии в окне нот — здесь появятся варианты продолжения.</body></html>"""


# ── shared state ───────────────────────────────────────────────────────────────

_START_VER = str(int(time.time()))

_state = {
    "score_html":   _welcome_html(_START_VER),
    "score_ver":    _START_VER,
    "pred_html":    _pred_placeholder(_START_VER),
    "pred_ver":     _START_VER,
    "nid_to_voice": {},
    "nid_to_note":  {},
    "voices":       {},
    "beat_dur_q":   1.0,
    "pickup_dur_q": 0.0,
    "sel_start":      None,
    "sel_voice":      None,
    "beam_of":        {},
    "measure_dur_q":  4.0,
}
_state_lock = threading.Lock()

_score_sse: list = []
_pred_sse:  list = []
_sse_lock = threading.Lock()


# ── SSE helper ─────────────────────────────────────────────────────────────────

def _notify(clients, version):
    msg = f"data: {version}\n\n".encode()
    with _sse_lock:
        dead = []
        for q in clients:
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(q)
        for q in dead:
            clients.remove(q)


def _sse_loop(clients, state_key, wfile):
    q = queue.Queue()
    with _sse_lock:
        clients.append(q)
    try:
        with _state_lock:
            cur = _state[state_key]
        wfile.write(f"data: {cur}\n\n".encode())
        wfile.flush()
        while True:
            try:
                wfile.write(q.get(timeout=20))
                wfile.flush()
            except queue.Empty:
                wfile.write(b": keepalive\n\n")
                wfile.flush()
    except Exception:
        pass
    finally:
        with _sse_lock:
            try:
                clients.remove(q)
            except ValueError:
                pass


# ── HTTP handlers ──────────────────────────────────────────────────────────────

class _ScoreHandler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def do_GET(self):
        if self.path.split('?')[0] == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            _sse_loop(_score_sse, 'score_ver', self.wfile)
            return
        with _state_lock:
            body = _state['score_html'].encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)
        if self.path == '/select':
            result = _handle_select(json.loads(raw))
            body = json.dumps(result).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/reset':
            _reset_selection()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'ok')
        else:
            self.send_response(405)
            self.end_headers()


class _PredHandler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def do_GET(self):
        if self.path.split('?')[0] == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            _sse_loop(_pred_sse, 'pred_ver', self.wfile)
            return
        with _state_lock:
            body = _state['pred_html'].encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)


class _TServer(ThreadingTCPServer):
    allow_reuse_address = True


def start_servers():
    for port, handler in ((SCORE_PORT, _ScoreHandler), (PRED_PORT, _PredHandler)):
        threading.Thread(
            target=lambda p=port, h=handler: _TServer(('127.0.0.1', p), h).serve_forever(),
            daemon=True,
        ).start()


# ── file loading (subprocess-isolated rendering) ───────────────────────────────

def _load_and_render(path, result_q, here, reader_path):
    """Subprocess worker: loads, preprocesses, renders, puts result on queue."""
    import sys as _sys, os as _os
    _sys.path.insert(0, reader_path)
    import verovio as _vr
    from app import (
        prepare_grand_staff, add_beam_markers,
        _fix_missing_divisions, _fix_beam_groups, _fix_missing_tuplet_markers,
        _strip_new_system_hints, _fix_implicit_pickup_measures,
        _fix_musicxml_voice_order, _fix_backward_repeat_on_left,
        _fix_section_pickup_bars, _strip_redundant_time_sigs,
        _renumber_measures_from_one, _fix_missing_initial_clefs,
    )
    _vd = _os.path.join(_os.path.dirname(_vr.__file__), 'data')
    vtk = _vr.toolkit()
    vtk.setResourcePath(_vd)
    vtk.setOptions({'pageWidth': 2800, 'adjustPageHeight': True,
                    'scale': 35, 'font': 'Leipzig', 'spacingSystem': 8})

    ext = path.rsplit('.', 1)[-1].lower()
    try:
        if ext == 'mxl':
            import zipfile as _zf
            with _zf.ZipFile(path) as z:
                xml_name = next(n for n in z.namelist()
                                if n.lower().endswith(('.xml', '.musicxml'))
                                and 'META' not in n)
                raw = z.read(xml_name)
                content = raw.decode('utf-8', errors='replace')
        else:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
    except Exception as e:
        result_q.put(('error', str(e)))
        return

    try:
        if ext == 'krn':
            content = prepare_grand_staff(content)
            content = add_beam_markers(content)
        elif ext in ('xml', 'musicxml', 'mxl'):
            for fn in (_fix_missing_divisions, _fix_beam_groups,
                       _fix_missing_tuplet_markers, _strip_new_system_hints,
                       _fix_implicit_pickup_measures, _fix_musicxml_voice_order,
                       _fix_backward_repeat_on_left, _fix_section_pickup_bars,
                       _strip_redundant_time_sigs, _renumber_measures_from_one,
                       _fix_missing_initial_clefs):
                content = fn(content)

        if not vtk.loadData(content):
            result_q.put(('error', 'verovio не может разобрать файл'))
            return

        n_pages = vtk.getPageCount()
        svgs    = [vtk.renderToSVG(p) for p in range(1, n_pages + 1)]
        mei_str = vtk.getMEI()
        result_q.put(('ok', svgs, mei_str))
    except Exception as e:
        result_q.put(('error', str(e)))


def load_file_bg(path, status_cb):
    def _run():
        status_cb('Загрузка…')
        try:
            check_file(path)
        except RuntimeError as e:
            status_cb(f'Ошибка: {e}')
            return
        import multiprocessing as _mp
        ctx = _mp.get_context('spawn')
        q   = ctx.Queue()
        p   = ctx.Process(target=_load_and_render, args=(path, q, _HERE, _READER), daemon=True)
        p.start()
        try:
            result = q.get(timeout=90)
        except Exception:
            p.terminate()
            status_cb('Ошибка: таймаут')
            return
        p.join(timeout=5)
        if result[0] == 'error':
            status_cb(f'Ошибка: {result[1]}')
            return
        _, svgs, mei_str = result
        _on_file_loaded(path, svgs, mei_str, status_cb)

    threading.Thread(target=_run, daemon=True).start()


def _on_file_loaded(path, svgs, mei_str, status_cb):
    try:
        voices, beat_dur_q, pickup_dur_q, _, _ = _voice_notes_from_mei(mei_str)
    except Exception:
        voices, beat_dur_q, pickup_dur_q = {}, 1.0, 0.0

    try:
        beam_of = _beam_groups_from_mei(mei_str)
    except Exception:
        beam_of = {}

    try:
        import xml.etree.ElementTree as _ET
        _tree = _ET.fromstring(mei_str)
        _pfx  = '{%s}' % 'http://www.music-encoding.org/ns/mei'
        measure_dur_q = 4.0
        for _sd in _tree.iter(_pfx + 'scoreDef'):
            _c = _sd.get('meter.count'); _u = _sd.get('meter.unit')
            if not (_c and _u):
                for _ms in _sd.iter(_pfx + 'meterSig'):
                    _c = _ms.get('count'); _u = _ms.get('unit')
                    if _c and _u:
                        break
            if _c and _u:
                measure_dur_q = int(_c) * 4.0 / int(_u)
                break
    except Exception:
        measure_dur_q = 4.0

    nid_to_voice = {}
    nid_to_note  = {}
    for vk, notes in voices.items():
        for note in notes:
            nid_to_voice[note[0]] = vk
            nid_to_note[note[0]]  = note

    ver = str(int(time.time()))
    pages = "\n".join(f'<div style="margin-bottom:24px">{s}</div>' for s in svgs)
    html  = _build_score_html(pages, ver)

    with _state_lock:
        _state['score_html']   = html
        _state['score_ver']    = ver
        _state['nid_to_voice'] = nid_to_voice
        _state['nid_to_note']  = nid_to_note
        _state['voices']       = voices
        _state['beat_dur_q']   = beat_dur_q
        _state['pickup_dur_q'] = pickup_dur_q
        _state['sel_start']      = None
        _state['sel_voice']      = None
        _state['beam_of']        = beam_of
        _state['measure_dur_q']  = measure_dur_q

    _notify(_score_sse, ver)
    status_cb(os.path.basename(path))


# ── score HTML ─────────────────────────────────────────────────────────────────

def _build_score_html(pages_html, version):
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body{{margin:0;padding:16px;font-family:sans-serif;background:#fff}}
#status{{font-size:13px;color:#555;margin-bottom:8px}}
</style>
<script>(function(){{
  var c="{version}";
  var es=new EventSource('/events');
  es.onmessage=function(e){{if(e.data!==c){{es.close();window.location.replace('/?t='+Date.now());}}}};
}})();</script>
</head>
<body>
<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
  <span id="status">Кликни первую ноту фрагмента.</span>
  <button onclick="resetSel()"
    style="font:12px sans-serif;padding:3px 10px;border:1px solid #bbb;border-radius:4px;background:#f5f5f5;cursor:pointer">
    Сбросить</button>
</div>
<div id="score">{pages_html}</div>
<script>
var selStart=null, selVoice=null;

function setStatus(s){{document.getElementById('status').textContent=s;}}

var _hlNids=[];

function clearHL(){{
  _hlNids.forEach(function(id){{
    var el=document.getElementById(id);
    if(el) el.removeAttribute('fill');
  }});
  _hlNids=[];
}}

function addHL(nid,color){{
  var el=document.getElementById(nid);
  if(el){{el.setAttribute('fill',color);_hlNids.push(nid);}}
}}

function resetSel(){{
  selStart=null; selVoice=null;
  clearHL();
  setStatus('Кликни первую ноту фрагмента.');
  fetch('/reset',{{method:'POST',headers:{{'Content-Length':'0'}},body:''}});
}}

var SEL_START_COLOR='#27ae60';
var SEL_END_COLOR='#e74c3c';
var SEL_RANGE_COLOR='#2980b9';

document.getElementById('score').addEventListener('click',function(ev){{
  var el=ev.target;
  while(el && el !== document.body && !(el.id && el.id.startsWith('note-'))) el=el.parentElement;
  if(!el || el === document.body || !el.id || !el.id.startsWith('note-')) return;
  handleClick(el.id);
  ev.stopPropagation();
}});

function handleClick(nid){{
  if(!selStart){{
    selStart=nid;
    addHL(nid,SEL_START_COLOR);
    setStatus('Первая нота выбрана. Кликни последнюю ноту того же голоса.');
    fetch('/select',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{action:'start',nid:nid}})}})
    .then(function(r){{return r.json();}})
    .then(function(d){{
      if(d.error){{setStatus('Ошибка: '+d.error);selStart=null;clearHL();return;}}
      selVoice=d.voice_key;
      setStatus('Голос staff'+d.voice_key[0]+'-layer'+d.voice_key[1]+'. Кликни последнюю ноту.');
    }});
  }} else {{
    fetch('/select',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{action:'end',nid:nid,voice_key:selVoice}})}})
    .then(function(r){{return r.json();}})
    .then(function(d){{
      if(d.error){{
        setStatus('Ошибка: '+d.error);
        clearHL(); addHL(selStart,SEL_START_COLOR);
        return;
      }}
      addHL(nid,SEL_END_COLOR);
      if(d.range_nids) d.range_nids.forEach(function(id){{
        if(id!==selStart && id!==nid) addHL(id,SEL_RANGE_COLOR);
      }});
      setStatus('Выбрано '+d.n_notes+' нот. Открываю продолжения…');
      selStart=null; selVoice=null;
    }});
  }}
}}
</script>
</body></html>"""


# ── selection logic ─────────────────────────────────────────────────────────────

def _handle_select(data):
    action = data.get('action')

    with _state_lock:
        nid_to_voice = _state['nid_to_voice']
        nid_to_note  = _state['nid_to_note']
        voices       = _state['voices']
        beat_dur_q   = _state['beat_dur_q']
        pickup_dur_q = _state['pickup_dur_q']
        sel_start    = _state['sel_start']
        sel_voice     = _state['sel_voice']
        beam_of       = _state['beam_of']
        measure_dur_q = _state['measure_dur_q']

    if action == 'start':
        nid = data['nid']
        if nid not in nid_to_voice:
            return {'error': 'нота не найдена'}
        vk = nid_to_voice[nid]
        with _state_lock:
            _state['sel_start'] = nid
            _state['sel_voice'] = vk
        return {'voice_key': list(vk)}

    if action == 'end':
        nid_end = data['nid']
        if nid_end not in nid_to_voice:
            return {'error': 'нота не найдена'}

        vk_end = nid_to_voice[nid_end]
        if vk_end != sel_voice:
            return {'error': (f'разные голоса (нач.: staff{sel_voice[0]}-layer{sel_voice[1]}, '
                              f'кон.: staff{vk_end[0]}-layer{vk_end[1]})')}

        all_notes = voices.get(sel_voice, [])
        nid_list  = [n[0] for n in all_notes]
        try:
            i0 = nid_list.index(sel_start)
            i1 = nid_list.index(nid_end)
        except ValueError:
            return {'error': 'нота не найдена в голосе'}

        if i1 < i0:
            i0, i1 = i1, i0

        melody = all_notes[i0:i1 + 1]
        if len(melody) < 2:
            return {'error': 'нужно минимум 2 ноты'}

        preds = _compute_inertia(melody)
        pred_html = _build_pred_html(melody, preds, beam_of, measure_dur_q,
                                     pickup_dur_q)
        pred_ver  = str(int(time.time()))

        with _state_lock:
            _state['pred_html'] = pred_html
            _state['pred_ver']  = pred_ver
            _state['sel_start'] = None
            _state['sel_voice'] = None

        _notify(_pred_sse, pred_ver)

        return {'n_notes': len(melody), 'range_nids': [n[0] for n in melody]}

    return {'error': 'неизвестное действие'}


def _reset_selection():
    with _state_lock:
        _state['sel_start'] = None
        _state['sel_voice'] = None


# ── inertia algorithms ─────────────────────────────────────────────────────────

def _dp(pname, oct_int):
    return oct_int * 7 + _DIATONIC_STEP.get(pname.lower(), 0)


_STEP_NAMES = ['c', 'd', 'e', 'f', 'g', 'a', 'b']


def _note_label(note):
    _, pname, oct_int, _, midi, _ = note
    base = _PITCH_CLASS.get(pname.lower(), 0) + (oct_int + 1) * 12
    acc  = {0: '', 1: '#', -1: 'b', 2: '##', -2: 'bb'}.get(midi - base, '')
    return pname.upper() + acc + str(oct_int)


def _compute_inertia(melody):
    """
    Scan every position in melody for inertia events.
    Returns list sorted by end_pos:
      {method, ctx_start, end_pos, notes [(pname,oct,dur_q,midi),...], actual_match}
    actual_match: True/False if end_pos+1 exists; None at the tail.
    """
    results = []
    seen = set()  # (end_pos, pred_key) to deduplicate

    def _pred_key(notes_out):
        return tuple((n[0].lower(), n[1], round(n[2] * 16)) for n in notes_out)

    def _add(method, ctx_start, end_pos, notes_out):
        key = (end_pos, _pred_key(notes_out))
        if key in seen:
            return
        seen.add(key)
        actual_match = None
        if end_pos + 1 < len(melody):
            actual = melody[end_pos + 1]
            pred   = notes_out[0]
            actual_match = (
                _dp(actual[1], actual[2]) == _dp(pred[0], pred[1])
                and round(actual[3] * 16) == round(pred[2] * 16)
            )
        results.append({
            'method': method, 'ctx_start': ctx_start,
            'end_pos': end_pos, 'notes': notes_out, 'actual_match': actual_match,
        })

    n = len(melody)

    # ── A: Repetition ──────────────────────────────────────────────────────────
    for ep in range(1, n):
        dp_val = _dp(melody[ep][1], melody[ep][2])
        run = 1
        for i in range(ep - 1, -1, -1):
            if _dp(melody[i][1], melody[i][2]) == dp_val:
                run += 1
            else:
                break
        if run >= 2:
            m = melody[ep]
            _add('Повтор', ep - run + 1, ep, [(m[1], m[2], m[3], m[4])])

    # ── B: Scale ───────────────────────────────────────────────────────────────
    for ep in range(2, n):
        last_d = (_dp(melody[ep][1], melody[ep][2])
                  - _dp(melody[ep - 1][1], melody[ep - 1][2]))
        if last_d == 0:
            continue
        scale_run = 1
        for i in range(ep - 1, 0, -1):
            d = (_dp(melody[i][1], melody[i][2])
                 - _dp(melody[i - 1][1], melody[i - 1][2]))
            if d == last_d:
                scale_run += 1
            else:
                break
        if scale_run >= 2:
            m = melody[ep]
            next_dp    = _dp(m[1], m[2]) + last_d
            next_oct   = next_dp // 7
            next_pname = _STEP_NAMES[next_dp % 7]
            next_midi  = _to_midi(next_pname, str(next_oct))
            _add('Гамма', ep - scale_run, ep,
                 [(next_pname, next_oct, m[3], next_midi)])

    # ── C: Substring ───────────────────────────────────────────────────────────
    if n >= 4:
        def _sig(note):
            return (_dp(note[1], note[2]), round(note[3] * 16))
        sigs = [_sig(m) for m in melody]
        for ep in range(3, n):
            for slen in range((ep + 1) // 2, 1, -1):
                sfx_s  = ep - slen + 1
                suffix = tuple(sigs[sfx_s:ep + 1])
                for start in range(0, ep - 2 * slen + 1):
                    if tuple(sigs[start:start + slen]) == suffix:
                        fn = melody[start + slen]
                        _add('Паттерн', sfx_s, ep,
                             [(fn[1], fn[2], fn[3], fn[4])])
                        break

    results.sort(key=lambda x: x['end_pos'])
    return results


# ── SVG helpers for prediction rows ──────────────────────────────────────────

# _mini_staff_svg constants (must match app.py)
_NSP    = 16
_CLEF_W = 14
_PL     = 3
_LS     = 4
_HLS    = 2.0


def _note_xs(n_notes):
    return [_PL + _CLEF_W + j * _NSP + _NSP // 2 for j in range(n_notes)]


def _svg_dim(notes_ni):
    """Return (W, H, SBOT) matching _mini_staff_svg for given notes_info list."""
    _DS = {'c': 0, 'd': 1, 'e': 2, 'f': 3, 'g': 4, 'a': 5, 'b': 6}
    def dp(p, o):
        return o * 7 + _DS.get(p, 0)
    all_d  = [dp(p, o) for p, o, *_ in notes_ni]
    avg    = sum(all_d) / len(all_d)
    treble = avg >= 26
    bot_d  = 30 if treble else 18
    top_d  = bot_d + 8
    PR     = 5
    extra_top = max(0, int((max(all_d) - top_d) * _HLS) + 6) if max(all_d) > top_d else 0
    extra_bot = max(0, int((bot_d - min(all_d)) * _HLS) + 5) if min(all_d) < bot_d else 0
    PT   = 10 + extra_top
    PB   = 5  + extra_bot
    SBOT = PT + 4 * _LS
    W    = _PL + _CLEF_W + len(notes_ni) * _NSP + PR
    H    = PT + 4 * _LS + PB
    return W, H, SBOT


def _bar_before(melody_slice, slice_onset_offset, measure_dur_q, pickup_dur_q):
    """Return set of note indices where a bar line should be drawn before that note."""
    adj_pickup = pickup_dur_q - slice_onset_offset
    return _bar_before_mixed(melody_slice, slice_onset_offset,
                             measure_dur_q, adj_pickup, 0.0)


def _inject_bar_lines(svg, bar_indices, n_notes, SBOT, H):
    """Inject vertical bar-line SVG elements before note at each index in bar_indices."""
    xs = _note_xs(n_notes)
    lines = []
    for j in bar_indices:
        x = xs[j] - _NSP // 2
        y1 = SBOT - 4 * _LS
        y2 = SBOT
        lines.append(f'<line x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}" '
                     f'stroke="#555" stroke-width="0.8"/>')
    if not lines:
        return svg
    # insert just before </svg>
    return svg.replace('</svg>', ''.join(lines) + '</svg>', 1)


def _erase_notes(svg, indices, n_notes):
    """Cover note heads and stems at given indices with white rectangles painted last."""
    xs = _note_xs(n_notes)
    masks = []
    for j in indices:
        x = xs[j]
        masks.append(
            f'<rect x="{x - 6:.1f}" y="0" width="13" height="200" '
            f'fill="white" stroke="none"/>'
        )
    if not masks:
        return svg
    return svg.replace('</svg>', ''.join(masks) + '</svg>', 1)


def _draw_rests(svg, indices, n_notes, SBOT):
    """Draw a whole-rest rectangle above the middle staff line for each index in indices."""
    xs = _note_xs(n_notes)
    rects = []
    mid_y = SBOT - 2 * _LS   # middle line y
    for j in indices:
        x = xs[j]
        rects.append(
            f'<rect x="{x - 4:.1f}" y="{mid_y - 2:.1f}" width="8" height="3" '
            f'fill="#bbb" stroke="none"/>'
        )
    if not rects:
        return svg
    return svg.replace('</svg>', ''.join(rects) + '</svg>', 1)


# ── prediction HTML ────────────────────────────────────────────────────────────

def _build_pred_html(melody, predictions, beam_of=None,
                     measure_dur_q=4.0, pickup_dur_q=0.0):
    ver = str(int(time.time()))

    def _ni(pname, oct_int, dur_q, midi_val, nid=None):
        return (pname.lower(), int(oct_int), float(dur_q), int(midi_val), nid or '')

    mel_ni = [_ni(n[1], n[2], n[3], n[4], n[0]) for n in melody]

    # Row 0: full melody
    bar0 = _bar_before(melody, melody[0][5], measure_dur_q, pickup_dur_q)
    _, _, SBOT0 = _svg_dim(mel_ni)
    svg0 = _mini_staff_svg(mel_ni, beam_of)
    svg0 = _inject_bar_lines(svg0, bar0, len(mel_ni), SBOT0, 0)
    rows = [
        f'<tr style="border-bottom:1px solid #e8e8e8">'
        f'<td style="padding:6px 14px 6px 0;color:#888;font-size:12px;white-space:nowrap">'
        f'(фрагмент)</td>'
        f'<td>{svg0}</td>'
        f'</tr>'
    ]

    n_added = 0
    for p in predictions:
        ep           = p['end_pos']
        cs           = p['ctx_start']
        pred_note    = p['notes'][0]
        actual_match = p['actual_match']

        if actual_match is True:
            continue

        pred_ni_item = _ni(pred_note[0], pred_note[1], pred_note[2], pred_note[3])

        onset_off  = melody[cs][5]
        adj_pickup = pickup_dur_q - onset_off

        if actual_match is None:
            ctx_slice = melody[cs:]
            row_ni    = ([_ni(n[1], n[2], n[3], n[4], n[0]) for n in ctx_slice]
                         + [pred_ni_item])
            rest_idx  = set()
            pred_idx  = len(row_ni) - 1
            bar_mel   = list(ctx_slice) + [None]
            bar_set   = _bar_before_mixed(bar_mel, onset_off, measure_dur_q,
                                          adj_pickup, pred_ni_item[2])
        else:
            ctx_slice = melody[cs:ep + 1]
            after     = melody[ep + 2:]
            n_after   = len(after)
            row_ni    = ([_ni(n[1], n[2], n[3], n[4], n[0]) for n in ctx_slice]
                         + [pred_ni_item]
                         + [_ni(n[1], n[2], n[3], n[4], n[0]) for n in after])
            pred_idx  = len(ctx_slice)
            rest_idx  = set(range(pred_idx + 1, pred_idx + 1 + n_after))
            bar_mel   = list(ctx_slice) + [None] + list(after)
            bar_set   = _bar_before_mixed(bar_mel, onset_off, measure_dur_q,
                                          adj_pickup, pred_ni_item[2])

        svg_p = _mini_staff_svg(row_ni, beam_of)
        _, _, SBOT = _svg_dim(row_ni)
        svg_p = _inject_bar_lines(svg_p, bar_set, len(row_ni), SBOT, 0)
        if rest_idx:
            svg_p = _erase_notes(svg_p, rest_idx, len(row_ni))
            svg_p = _draw_rests(svg_p, rest_idx, len(row_ni), SBOT)

        pred_color = '#e67e22' if actual_match is None else '#e74c3c'
        svg_p = _color_note_at(svg_p, pred_idx, len(row_ni), pred_color)

        tick   = '→' if actual_match is None else '✗'
        tcolor = '#888' if actual_match is None else '#e74c3c'
        label  = (
            f'<span style="color:{tcolor};font-weight:bold">{tick}</span>'
            f'&nbsp;<span style="font-size:11px;color:#555">({ep + 1})&nbsp;{p["method"]}</span>'
        )
        rows.append(
            f'<tr style="border-bottom:1px solid #f0f0f0">'
            f'<td style="padding:4px 14px 4px 0;white-space:nowrap">{label}</td>'
            f'<td><span style="display:inline-block;margin-left:{cs * _NSP}px">{svg_p}</span></td>'
            f'</tr>'
        )
        n_added += 1

    if not n_added:
        rows.append(
            '<tr><td colspan="2" style="color:#888;font-size:12px;padding:8px 0">'
            'Нет предсказаний.</td></tr>'
        )

    body = (
        f'<p style="font-size:12px;color:#777;margin:0 0 8px">'
        f'{" ".join(_note_label(n) for n in melody)}</p>'
        f'<table style="border-collapse:collapse">{"".join(rows)}</table>'
    )
    return _pred_page(body, ver)


def _bar_before_mixed(mel_with_none, onset_off, measure_dur_q, adj_pickup, pred_dur_q):
    """Like _bar_before but mel_with_none may contain None (predicted note placeholder).
    adj_pickup: adjusted pickup_dur_q for this slice.
    pred_dur_q: duration of the predicted note (for computing onset of notes after it)."""
    bars = set()
    eps  = 1e-6
    # Build (onset_relative, dur) pairs
    onsets = []
    pos = 0.0
    for item in mel_with_none:
        if item is None:
            onsets.append((pos, pred_dur_q))
            pos += pred_dur_q
        else:
            onsets.append((item[5] - onset_off, item[3]))
    for j in range(1, len(onsets)):
        prev_end = onsets[j - 1][0] + onsets[j - 1][1]
        cur      = onsets[j][0]
        k0 = int((prev_end - adj_pickup) / measure_dur_q)
        for k in range(max(0, k0), k0 + 3):
            bl = adj_pickup + k * measure_dur_q
            if prev_end - eps <= bl <= cur + eps and bl > eps:
                bars.add(j)
                break
    return bars


def _color_note_at(svg, idx, n_notes, color):
    """Color the ellipse at note index idx (0-based)."""
    parts = svg.split('<ellipse')
    if idx + 1 >= len(parts):
        return svg
    chunk = parts[idx + 1]
    chunk = chunk.replace('fill="#555"', f'fill="{color}"', 1)
    chunk = chunk.replace("fill='#555'", f"fill='{color}'", 1)
    chunk = chunk.replace('fill="white"', f'fill="{color}"', 1)
    chunk = chunk.replace("fill='white'", f"fill='{color}'", 1)
    parts[idx + 1] = chunk
    return '<ellipse'.join(parts)


def _color_nth_from_end(svg, n, color):
    """Color the n-th ellipse from the end (1=last, 2=second-to-last)."""
    parts = svg.rsplit('<ellipse', n)
    if len(parts) < n + 1:
        return svg
    target = parts[1]
    target = target.replace('fill="#555"', f'fill="{color}"', 1)
    target = target.replace("fill='#555'", f"fill='{color}'", 1)
    return parts[0] + '<ellipse' + target + '<ellipse'.join(parts[2:])


def _color_last_n(svg, n, color='#e67e22'):
    """Color the last n note-head ellipses with the given color."""
    parts = svg.rsplit('<ellipse', n)
    if len(parts) <= n:
        return svg
    out = parts[0]
    for i, chunk in enumerate(parts[1:], 1):
        if i <= n:
            chunk = chunk.replace('fill="#555"', f'fill="{color}"', 1)
            chunk = chunk.replace("fill='#555'", f"fill='{color}'", 1)
        out += '<ellipse' + chunk
    return out


def _pred_page(body, ver):
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body{{margin:0;padding:20px;font-family:sans-serif;background:#fff}}</style>
<script>(function(){{
  var c="{ver}";
  var es=new EventSource('/events');
  es.onmessage=function(e){{if(e.data!==c){{es.close();window.location.replace('/?t='+Date.now());}}}};
}})();</script>
</head><body>
<h3 style="margin:0 0 12px;font-size:15px;color:#333">Продолжения по инерции</h3>
{body}
</body></html>"""


# ── tkinter file browser ───────────────────────────────────────────────────────

class FileBrowser:
    def __init__(self, root_win):
        self.root = root_win
        root_win.title('Melody Reader')
        root_win.resizable(True, True)
        sw = root_win.winfo_screenwidth()
        root_win.geometry(f'480x800+{sw - 480}+0')

        frm_top = tk.Frame(root_win)
        frm_top.pack(fill='x', padx=6, pady=4)
        self.search_var = tk.StringVar()
        self.search_var.trace_add('write', lambda *_: self._filter())
        tk.Entry(frm_top, textvariable=self.search_var,
                 font=('sans-serif', 12)).pack(fill='x')

        frm = tk.Frame(root_win)
        frm.pack(fill='both', expand=True, padx=6)
        self.lb = tk.Listbox(frm, font=('sans-serif', 11), activestyle='dotbox',
                             selectbackground='#3498db', selectforeground='white')
        sb = ttk.Scrollbar(frm, orient='vertical', command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.lb.pack(fill='both', expand=True)
        self.lb.bind('<<ListboxSelect>>', self._on_select)

        self.status_var = tk.StringVar(value='Ready')
        tk.Label(root_win, textvariable=self.status_var, font=('sans-serif', 10),
                 anchor='w', fg='#555').pack(fill='x', padx=6, pady=2)

        self._all_files: list = []
        self._filtered:  list = []
        self._load_files()
        root_win.after(200, lambda: (root_win.focus_force(), self.search_var.set('')))

    def _load_files(self):
        files = find_kern_files(KERN_DIR)
        lp    = find_lilypond_files()
        xml_d = os.path.join(_HERE, 'musicxml')
        xf    = find_xml_files(xml_d)
        self._all_files = files + lp + xf
        self._filter()

    def _filter(self):
        q = self.search_var.get().lower()
        self._filtered = [(r, f) for r, f in self._all_files if q in r.lower()]
        self.lb.delete(0, 'end')
        for rel, _ in self._filtered:
            self.lb.insert('end', os.path.basename(rel))

    def _on_select(self, _):
        sel = self.lb.curselection()
        if not sel:
            return
        _, full = self._filtered[sel[0]]
        self.status_var.set('Загрузка…')
        load_file_bg(full,
                     lambda s: self.root.after(0, self.status_var.set, s))


# ── browser launch ─────────────────────────────────────────────────────────────

def _find_browser():
    for p in [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ]:
        if os.path.isfile(p):
            return p
    return None


def _launch_browsers():
    browser = _find_browser()
    time.sleep(0.3)
    if not browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{SCORE_PORT}/')
        webbrowser.open(f'http://127.0.0.1:{PRED_PORT}/')
        return
    try:
        r = tk.Tk(); sw = r.winfo_screenwidth(); sh = r.winfo_screenheight(); r.destroy()
    except Exception:
        sw, sh = 1920, 1080
    w = max(400, sw - 480)
    subprocess.Popen([browser, f'--app=http://127.0.0.1:{SCORE_PORT}/',
                      '--window-position=0,0', f'--window-size={w},{sh}'])
    time.sleep(0.4)
    subprocess.Popen([browser, f'--app=http://127.0.0.1:{PRED_PORT}/'])


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    start_servers()
    root = tk.Tk()
    FileBrowser(root)
    threading.Thread(target=_launch_browsers, daemon=True).start()
    root.mainloop()


if __name__ == '__main__':
    main()

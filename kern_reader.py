#!/usr/bin/env python3
# version: 2026-03-29
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
import queue
import re
import threading
import warnings
import webbrowser
import xml.etree.ElementTree as ET
from collections import defaultdict
import tkinter as tk
from tkinter import ttk
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer, TCPServer

warnings.filterwarnings("ignore")

import music21
import verovio

KERN_DIR     = os.path.join(os.path.dirname(__file__), "kern")
VEROVIO_DATA = os.path.join(os.path.dirname(verovio.__file__), "data")
SERVER_PORT  = 8765

# Only these subdirectories are shown in the file list
KERN_ALLOWED = (
    os.path.join("musedata", "bach", "keyboard", "wtc-1"),        # WTC1 preludes
    os.path.join("musedata", "bach", "keyboard", "wtc-2"),        # WTC2 preludes
    os.path.join("osu", "classical", "bach", "wtc-1"),             # WTC1 fugues
    os.path.join("osu", "classical", "bach", "wtc-2"),             # WTC2 fugues
    os.path.join("osu", "classical", "bach", "inventions"),        # Inventions
    os.path.join("musedata", "bach", "chorales"),                   # Chorales
    os.path.join("users", "craig", "classical", "bach", "violin"), # Violin sonatas & partitas
    os.path.join("users", "craig", "classical", "bach", "cello"),  # Cello suites
    "permut",                                                       # Permuted files
    # Baroque (non-Bach)
    os.path.join("musedata", "corelli"),                            # Corelli Op.1,3,4,5,6
    os.path.join("musedata", "vivaldi"),                            # Vivaldi Op.1,2
    os.path.join("ccarh", "vivaldi"),                               # Vivaldi Op.8
    os.path.join("users", "craig", "classical", "scarlatti"),      # D. Scarlatti sonatas
    os.path.join("users", "craig", "classical", "buxtehude"),      # Buxtehude
    os.path.join("users", "craig", "classical", "frescobaldi"),    # Frescobaldi
    os.path.join("users", "craig", "classical", "handel"),         # Handel
    os.path.join("users", "craig", "classical", "monteverdi"),     # Monteverdi
)

_vtk = verovio.toolkit()
_vtk.setResourcePath(VEROVIO_DATA)

# ── shared state ──────────────────────────────────────────────────────────────

_state = {
    "html":       """<!DOCTYPE html><html><head><meta charset="utf-8">
<script>
(function(){
  var cur="0";
  var es=new EventSource('/events');
  es.onmessage=function(e){
    if(e.data!==cur){ es.close(); window.location.replace('/?t='+Date.now()); }
  };
})();
</script>
</head><body style='font:16px sans-serif;padding:40px;color:#888'>
Select a kern file in the panel.</body></html>""",
    "version":    "0",
    "seqs":       [],   # [(voice_key, interval_seq), ...] for current file
    "beat_dur_q": 1.0,
}
_state_lock = threading.Lock()

# ── SSE clients ───────────────────────────────────────────────────────────────

_sse_clients = []
_sse_lock    = threading.Lock()

def _notify_sse(version):
    """Push new version to all connected SSE clients."""
    msg = f"data: {version}\n\n".encode()
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)

# ── HTTP server ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # silence server logs

    def do_GET_events(self):
        """Server-Sent Events: push version number whenever score changes."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = queue.Queue()
        with _sse_lock:
            _sse_clients.append(q)
        try:
            # send current version immediately so the client can compare
            with _state_lock:
                cur = _state["version"]
            self.wfile.write(f"data: {cur}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=20)
                    self.wfile.write(msg)
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")  # prevent proxy timeout
                    self.wfile.flush()
        except Exception:
            pass
        finally:
            with _sse_lock:
                try:
                    _sse_clients.remove(q)
                except ValueError:
                    pass

    def do_POST(self):
        if self.path == "/search":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8").strip()
            try:
                result = _search_motif(body)
                resp = json.dumps(result).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(resp))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                msg = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(msg))
                self.end_headers()
                self.wfile.write(msg)
        else:
            self.send_response(405)
            self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == "/events":
            self.do_GET_events()
            return
        with _state_lock:
            if path == "/version":
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
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)


class _ThreadingHTTPServer(ThreadingTCPServer):
    allow_reuse_address = True

def start_server():
    srv = _ThreadingHTTPServer(("127.0.0.1", SERVER_PORT), Handler)
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
    import re as _re
    def _sort_key(rel):
        fname = os.path.basename(rel)
        m = _re.match(r'wtc([12])([pf])(\d+)\.krn', fname)
        if m:
            wtc_set = int(m.group(1))
            pf = 0 if m.group(2) == 'p' else 1
            num = int(m.group(3))
            return (0, wtc_set, num, pf, '')
        return (1, 0, 0, 0, rel)
    files.sort(key=lambda x: _sort_key(x[0]))
    return files


XML_DIR = os.path.join(os.path.dirname(__file__), "musicxml")


def find_xml_files(root: str):
    """Return [(rel, full), ...] for all .xml files under root."""
    files = []
    if not os.path.isdir(root):
        return files
    for dirpath, _, fnames in os.walk(root):
        for fname in sorted(fnames):
            if fname.lower().endswith('.xml'):
                full = os.path.join(dirpath, fname)
                rel  = 'musicxml/' + os.path.relpath(full, root).replace('\\', '/')
                files.append((rel, full))
    return files


_COMPOSER_MAP = {
    'bach':           'Bach',
    'palestrina':     'Palestrina',
    'beethoven':      'Beethoven',
    'mozart':         'Mozart',
    'haydn':          'Haydn',
    'monteverdi':     'Monteverdi',
    'josquin':        'Josquin',
    'schumann_robert':'Schumann R.',
    'schumann_clara': 'Schumann C.',
    'chopin':         'Chopin',
    'corelli':        'Corelli',
    'handel':         'Handel',
    'schubert':       'Schubert',
    'webern':         'Webern',
    'weber':          'Weber',
    'schoenberg':     'Schoenberg',
    'verdi':          'Verdi',
    'joplin':         'Joplin',
    'cpebach':        'C.P.E. Bach',
    'trecento':       'Trecento',
    'ciconia':        'Ciconia',
    'beach':          'Beach',
    'luca':           'Luca',
    'lusitano':       'Lusitano',
    'liliuokalani':   'Liliuokalani',
    'johnson_j_r':    'Johnson J.R.',
}


_KERN_COMPOSER = {
    'corelli':     'Corelli',
    'vivaldi':     'Vivaldi',
    'scarlatti':   'Scarlatti D.',
    'buxtehude':   'Buxtehude',
    'frescobaldi': 'Frescobaldi',
    'handel':      'Handel',
    'monteverdi':  'Monteverdi',
}

# ── Bach cycle grouping ────────────────────────────────────────────────────────

_BACH_CYCLE_ORDER = [
    'WTC, Book I',
    'WTC, Book II',
    'Inventions',
    'Sinfonias',
    'English Suites',
    'French Suites',
    'Keyboard Partitas',
    'Goldberg Variations',
    'Art of Fugue',
    'Violin Sonatas & Partitas',
    'Cello Suites',
    'Flute Sonatas',
    'Violin Sonatas with Keyboard',
    'Brandenburg Concertos',
    'Concertos',
    'Organ Sonatas',
    'Orgelbüchlein',
    'Organ Mass (Clavier-Übung III)',
    'Chorale Preludes',
    'Chorale Harmonizations',
    'Cantatas',
    'Motets & Masses',
    'Notebook for A.M. Bach',
    'Toccatas & Preludes',
    'Small Keyboard Works',
    'Other Bach',
]

_BACH_CYCLE_IDX = {c: i for i, c in enumerate(_BACH_CYCLE_ORDER)}


def _bach_cycle(rel: str) -> str:
    """Return cycle/collection name for a Bach file (kern or lilypond XML)."""
    import re as _re
    r = rel.replace('\\', '/').lower()
    fname = r.split('/')[-1]
    stem  = fname.rsplit('.', 1)[0]

    # ── kern files: use directory context ─────────────────────────────────────
    if fname.endswith('.krn'):
        # WTC
        m = _re.match(r'wtc([12])([pf])(\d+)', stem)
        if m:
            return 'WTC, Book I' if m.group(1) == '1' else 'WTC, Book II'
        # Inventions
        if _re.match(r'inven\d+', stem):
            return 'Inventions'
        # Cello suites by directory
        if '/cello/' in r:
            return 'Cello Suites'
        # Violin by directory or filename
        if '/violin/' in r or _re.match(r'(partita|sonata)\d', stem):
            return 'Violin Sonatas & Partitas'
        # Brandenburg by directory
        if '/brandenburg/' in r or _re.match(r'bwv104[6-9][a-z]?|bwv105[01][a-z]?', stem):
            return 'Brandenburg Concertos'
        # Chorales
        if '/chorale' in r or _re.match(r'bwv0[23]\d\d|bwv04[0-3]\d', stem) or _re.match(r'chor\d+', stem):
            return 'Chorale Harmonizations'
        if '/organ' in r:
            return 'Chorale Preludes'
        if 'bwv0565' in stem:
            return 'Toccatas & Preludes'
        if _re.match(r'bwv\d+', stem):
            n = int(_re.search(r'\d+', stem).group())
            return _bwv_to_cycle(n)

    # ── lilypond XML / MXL files ───────────────────────────────────────────────
    # Named non-BWV files
    if 'contrapunctus' in stem or stem.startswith('f9') or 'duetto' in stem:
        return 'Art of Fugue'
    if 'passacag' in stem or 'toccatafugue' in stem.replace(' ', '') or 'bwv0565' in stem:
        return 'Toccatas & Preludes'
    if stem.startswith('french_suite') or 'french_suite' in stem:
        return 'French Suites'
    if 'cellosuite' in stem:
        return 'Cello Suites'
    if stem.startswith('concerto_in') or 'concerto_in' in stem:
        return 'Concertos'
    if stem.startswith('brandenbur'):
        return 'Brandenburg Concertos'
    if stem in ('air', 'air_tromb'):
        return 'Concertos'
    if 'sonataiv' in stem.replace('_', ''):
        return 'Violin Sonatas with Keyboard'
    if 'cantata' in stem:
        return 'Cantatas'
    if stem in ('bistdubeimiir', 'bistdubeimiir') or 'bistdu' in stem:
        return 'Notebook for A.M. Bach'
    if stem in ('prelude_et_fugue_en_la_majeur', 'prelude_et_fugue'):
        return 'Toccatas & Preludes'
    # Organ chorales by name
    if any(s in stem for s in ('christ_lag', 'christlag', 'da_jesus', 'das_alte',
                                'durch_adams', 'ich_ruf', 'in_dich', 'in_dulci',
                                'o_haupt', 'puer_natus', 'sheep', 'vom_himmel',
                                'von_gott', 'lobt', 'nun_komm', 'womut',
                                'bach_brich', 'bach_christ', 'minuet_')):
        return 'Chorale Preludes'
    if any(s in stem for s in ('bistdu', 'bist_du')):
        return 'Notebook for A.M. Bach'

    # Notebook Anna Magdalena
    notebook_bwvs = set(range(508, 519)) | {690, 691, 515, 516, 510, 511, 512}

    # Extract BWV number
    m = _re.search(r'bwv[-_]?(\d+)', stem)
    if m:
        n = int(m.group(1))
        if n in notebook_bwvs or 508 <= n <= 518:
            return 'Notebook for A.M. Bach'
        # bwv_117.4 style → cantata movement/chorale; skip keyboard-work override
        if _re.search(r'bwv[-_]?\d+\.\d', stem):
            return 'Cantatas'
        return _bwv_to_cycle(n)

    return 'Other Bach'


def _bwv_to_cycle(n: int) -> str:
    """Map BWV number to cycle name."""
    if 846 <= n <= 869:  return 'WTC, Book I'
    if 870 <= n <= 893:  return 'WTC, Book II'
    # WTC early versions (847a, 848a etc — parsed as 847,848 from regex)
    if n in (847, 848, 849, 850, 851, 852, 853, 854, 855, 856, 857, 858,
             859, 860, 861, 862, 863, 864, 865, 866, 867, 868, 869,
             875, 878, 881, 882, 884, 885, 886, 887, 889, 891, 893, 895):
        # overlap with above ranges; 895 is near WTC
        if n <= 893: return 'WTC, Book I' if n <= 869 else 'WTC, Book II'
    if 772 <= n <= 786:  return 'Inventions'
    if 787 <= n <= 801:  return 'Sinfonias'
    if 806 <= n <= 811:  return 'English Suites'
    if 812 <= n <= 817:  return 'French Suites'
    if 825 <= n <= 830:  return 'Keyboard Partitas'
    if n == 988:         return 'Goldberg Variations'
    if n == 1080:        return 'Art of Fugue'
    if 1001 <= n <= 1006: return 'Violin Sonatas & Partitas'
    if 1007 <= n <= 1012: return 'Cello Suites'
    if n == 1013:        return 'Flute Sonatas'
    if 1014 <= n <= 1019: return 'Violin Sonatas with Keyboard'
    if 1041 <= n <= 1045: return 'Concertos'
    if 1046 <= n <= 1051: return 'Brandenburg Concertos'
    if 1052 <= n <= 1065: return 'Concertos'
    # Organ
    if 525 <= n <= 530:  return 'Organ Sonatas'
    if 531 <= n <= 598:  return 'Toccatas & Preludes'
    if 599 <= n <= 644:  return 'Orgelbüchlein'
    if 645 <= n <= 650:  return 'Chorale Preludes'   # Schübler chorales
    if 651 <= n <= 689:  return 'Organ Mass (Clavier-Übung III)'
    if 690 <= n <= 771:  return 'Chorale Preludes'
    # Chorales (harmonized, from cantatas)
    if 250 <= n <= 438:  return 'Chorale Harmonizations'
    # Small keyboard works
    if 772 <= n <= 805:  return 'Small Keyboard Works'   # already covered above
    if 894 <= n <= 987:  return 'Small Keyboard Works'
    if 989 <= n <= 1000: return 'Small Keyboard Works'
    # Keyboard arrangements sharing BWV numbers with cantatas
    if n in (117, 118, 119, 120, 121, 127, 128): return 'Small Keyboard Works'
    # Cantatas
    if 1 <= n <= 200:    return 'Cantatas'
    if 225 <= n <= 249:  return 'Motets & Masses'
    return 'Other Bach'


def _composer_from_rel(rel: str) -> str:
    parts = rel.replace('\\', '/').split('/')
    if parts[0] == 'music21' and len(parts) > 1:
        return _COMPOSER_MAP.get(parts[1].lower(), parts[1].capitalize())
    # kern/ files — check for non-Bach composers by path segment
    for part in parts:
        if part.lower() in _KERN_COMPOSER:
            return _KERN_COMPOSER[part.lower()]
    return 'Bach'


def _palestrina_sort_key(rel):
    """Sort key for Palestrina files: (mass_number, filename) so mass 0 groups together."""
    import re
    fname = rel.split('/')[-1]
    stem  = fname.rsplit('.', 1)[0]
    nums  = re.findall(r'\d+', stem)
    mass  = int(nums[-1]) if nums else 9999
    return (mass, fname.lower())


def find_generated_files():
    """Return [(rel, full), ...] for .krn files in the generated/ folder."""
    gen_dir = os.path.join(os.path.dirname(__file__), 'generated')
    if not os.path.isdir(gen_dir):
        return []
    files = []
    for fname in sorted(os.listdir(gen_dir)):
        if fname.endswith('.krn'):
            full = os.path.join(gen_dir, fname)
            files.append((f'generated/{fname}', full))
    return files


def find_lilypond_files():
    """Return [(rel, full), ...] for MusicXML files in lilypond/musicxml/."""
    xml_dir = os.path.join(os.path.dirname(__file__), 'lilypond', 'musicxml')
    if not os.path.isdir(xml_dir):
        return []
    files = []
    for fname in sorted(os.listdir(xml_dir)):
        if fname.endswith('.xml'):
            full = os.path.join(xml_dir, fname)
            files.append((f'lilypond/{fname}', full))
    return files


def find_imslp_files():
    """Return [(rel, full), ...] for .mxl files in musicxml/imslp_bach/, using manifest.json."""
    imslp_dir = os.path.join(os.path.dirname(__file__), 'musicxml', 'imslp_bach')
    if not os.path.isdir(imslp_dir):
        return []
    manifest_path = os.path.join(imslp_dir, 'manifest.json')
    try:
        import json as _json
        with open(manifest_path, encoding='utf-8') as f:
            manifest = _json.load(f)
        page_xml = manifest.get('page_xml_files', {})
    except Exception:
        page_xml = {}

    # Build file→title map (first title that lists this file)
    file_title: dict = {}
    for title, files in page_xml.items():
        for fname in files:
            if fname not in file_title:
                file_title[fname] = title

    result = []
    all_files = manifest.get('all_files', []) if 'manifest_path' in dir() else []
    try:
        all_files = manifest.get('all_files', sorted(
            f for f in os.listdir(imslp_dir) if f.endswith('.mxl')))
    except Exception:
        all_files = sorted(f for f in os.listdir(imslp_dir) if f.endswith('.mxl'))

    for fname in all_files:
        full = os.path.join(imslp_dir, fname)
        if not os.path.isfile(full):
            continue
        title = file_title.get(fname, fname)
        # If multiple files share same title, append filename suffix
        same = [f for f in all_files if file_title.get(f, f) == title]
        if len(same) > 1:
            rel = f'imslp/{title} [{fname}]'
        else:
            rel = f'imslp/{title}'
        result.append((rel, full))
    return result


def find_music21_files():
    """Return [(rel, full), ...] for music21 corpus files verovio can render (.krn, .mxl, .xml)."""
    try:
        from music21 import corpus as m21corpus
        paths = m21corpus.getCorePaths()
    except Exception:
        return []
    files = []
    for p in sorted(paths, key=lambda x: str(x).lower()):
        s = str(p)
        ext = s.rsplit('.', 1)[-1].lower()
        if ext not in ('krn', 'mxl', 'xml'):
            continue
        norm = s.replace('\\', '/')
        parts = norm.split('/')
        try:
            idx = next(i for i, part in enumerate(parts) if part == 'corpus')
            rel = 'music21/' + '/'.join(parts[idx + 1:])
        except StopIteration:
            rel = 'music21/' + os.path.basename(s)
        files.append((rel, s))
    # re-sort Palestrina by mass number first, then movement name
    pal   = [(r, f) for r, f in files if '/palestrina/' in r]
    other = [(r, f) for r, f in files if '/palestrina/' not in r]
    pal.sort(key=lambda x: _palestrina_sort_key(x[0]))
    return other + pal


# ── validation ────────────────────────────────────────────────────────────────

def check_file(path: str):
    if path.lower().endswith('.mxl'):
        import zipfile as _zf
        if not _zf.is_zipfile(path):
            raise RuntimeError("Invalid .mxl file")
        return
    with open(path, "rb") as f:
        head = f.read(256)
    if not head.strip():
        raise RuntimeError("File is empty — not available in this collection")
    if b"<html" in head.lower() or b"Access Unsuccessful" in head:
        raise RuntimeError("Server returned an error page — file unavailable")

# ── render ────────────────────────────────────────────────────────────────────

_RELOAD_JS = """
<script>
(function(){{
  var _cur="{version}";
  var es=new EventSource('/events');
  es.onmessage=function(e){{
    if(e.data!==_cur){{ es.close(); window.location.replace('/?t='+Date.now()); }}
  }};
}})();
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

# Per-file beat_dur_q overrides (filename substring → beat_dur_q in quarter notes).
# Use to force a specific metric feel when the time signature is ambiguous.
_BEAT_DUR_OVERRIDES: dict[str, float] = {
    'bwv_988_v27': 1.0,   # 6/8 felt as 2+2+2 (3 quarter beats), not 3+3
}

# ── MusicXML voice-order fix ──────────────────────────────────────────────────
_STEP_MIDI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

def _fix_implicit_pickup_measures(content: str) -> str:
    """Fix MusicXML implicit measures (number='-1') from LilyPond repeat pickups.
    Voices 2+ have print-object=no mRests with full-measure duration (e.g. 40320)
    while voice 1 has only a short pickup (e.g. 10080).  Verovio renders the measure
    as full-width with an extra barline.  Fix: set hidden-rest and backup durations
    to match the real voice content so verovio sees a short pickup bar."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return content
    changed = False
    for part in root.iter('part'):
        for measure in part.findall('measure'):
            if measure.get('implicit') != 'yes' or measure.get('number') != '-1':
                continue
            real_dur = sum(
                int(n.findtext('duration', '0'))
                for n in measure.findall('note')
                if n.get('print-object') != 'no'
            )
            if real_dur == 0:
                continue
            for note in measure.findall('note'):
                if note.get('print-object') != 'no':
                    continue
                rest = note.find('rest')
                if rest is not None:
                    rest.attrib.pop('measure', None)
                dur_el = note.find('duration')
                if dur_el is not None and int(dur_el.text) != real_dur:
                    dur_el.text = str(real_dur)
                    changed = True
            for backup in measure.findall('backup'):
                dur_el = backup.find('duration')
                if dur_el is not None and int(dur_el.text) > real_dur:
                    dur_el.text = str(real_dur)
                    changed = True
    if not changed:
        return content
    result = ET.tostring(root, encoding='unicode')
    if content.lstrip().startswith('<?xml'):
        decl = content[:content.index('?>') + 2]
        result = decl + '\n' + result
    return result


def _fix_musicxml_voice_order(content: str) -> str:
    """
    For each part with multiple voices, re-number voices so that voice 1 has
    the highest average MIDI pitch (→ stems up) and voice 2 the next, etc.
    Also inserts explicit <stem>up/down</stem> on every note.
    Only modifies parts that have 2+ voices and need reordering.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(content.encode())
    except ET.ParseError:
        return content

    changed = False
    for part in root.findall('.//part'):
        # Collect average MIDI pitch per voice (non-chord notes only)
        voice_midis: dict = {}
        for note in part.findall('.//note'):
            if note.find('chord') is not None:
                continue
            v_el = note.find('voice')
            p_el = note.find('pitch')
            if v_el is None or p_el is None:
                continue
            step  = (p_el.findtext('step') or 'C').strip()
            oct_  = int(p_el.findtext('octave') or '4')
            alter = float(p_el.findtext('alter') or '0')
            midi  = (oct_ + 1) * 12 + _STEP_MIDI.get(step, 0) + round(alter)
            voice_midis.setdefault(v_el.text, []).append(midi)

        if len(voice_midis) < 2:
            continue

        voice_avg  = {v: sum(ms) / len(ms) for v, ms in voice_midis.items() if ms}
        sorted_vox = sorted(voice_avg, key=lambda v: -voice_avg[v])  # highest first
        voice_remap = {v: str(i + 1) for i, v in enumerate(sorted_vox)}

        if all(voice_remap[v] == v for v in voice_remap):
            # Add stem elements even if order is already correct
            pass

        for note in part.findall('.//note'):
            v_el = note.find('voice')
            if v_el is None:
                continue
            old_v       = v_el.text
            new_v       = voice_remap.get(old_v, old_v)
            v_el.text   = new_v
            stem_dir    = 'up' if new_v == '1' else 'down'
            stem_el     = note.find('stem')
            if stem_el is None:
                dur_el = note.find('duration')
                stem_el = ET.Element('stem')
                if dur_el is not None:
                    list(note).index(dur_el)   # ensure dur_el in note
                    note.insert(list(note).index(dur_el) + 1, stem_el)
                else:
                    note.append(stem_el)
            stem_el.text = stem_dir

        changed = True

    if not changed:
        return content
    return ET.tostring(root, encoding='unicode')


# ── TSD harmony labels ────────────────────────────────────────────────────────
# Loaded once from TSD.txt: filename → (beat_dur_q, [label, ...])
# label: 'T', 'S', or 'D'

def _load_tsd_file() -> dict:
    path = os.path.join(os.path.dirname(__file__), 'TSD.txt')
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            filenames_field, metre, tsd_str = parts[0], parts[1], parts[2]
            num, den = metre.split('/')
            beat_dur_q = int(num) * 4.0 / int(den)   # bar duration in quarter notes
            labels = [c for c in tsd_str if c in 'TSD']
            if labels:
                for filename in filenames_field.split(','):
                    data[filename.strip()] = (beat_dur_q, labels)
    return data

_TSD_DATA: dict = _load_tsd_file()   # filename → (beat_dur_q, ['T','S','D',...])

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
      32nd in 3/4 (beat=1.0): n_per_beat=8 → capped to 4 → phase 0-3 (same as 16th)
    """
    if dur_q <= 0 or beat_dur_q <= 0:
        return 0
    n_per_beat = max(1, round(beat_dur_q / dur_q))
    if n_per_beat <= 1:
        return 0
    # For triplet notes (n_per_beat divisible by 3), phase within the triplet
    # group is what matters rhythmically: phase 0 and phase 3 are both
    # "first of triplet group" → collapse to phase % 3.
    if n_per_beat % 3 == 0:
        n_per_beat = 3
    # Cap binary subdivisions at 4 phases (same resolution as 16th notes).
    # Prevents 32nd/64th notes from generating excessive phase slots.
    elif n_per_beat > 4:
        n_per_beat = 4
    pos_in_beat = onset_q % beat_dur_q
    phase = int(round(pos_in_beat / dur_q)) % n_per_beat
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

    def proc_note(n, dur_override=None, dots_override=None, onset=0.0, scale=1.0):
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
        return (nid, pname, int(oct_str), _to_quarters(dur, dots) * scale,
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

    voices        = defaultdict(list)
    measure_onset = 0.0

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
                        dur = _to_quarters(child.get('dur', '4'), int(child.get('dots', 0))) * scale
                        if child.get('grace'):   # grace note (q/Q in kern) — skip, no pos advance
                            pass
                        else:
                            e = proc_note(child, onset=onset, scale=scale)
                            if e:
                                voices[key].append(e)
                            pos += dur
                            pos_real = pos
                    elif t == 'chord':
                        dur = _to_quarters(child.get('dur', '4'), int(child.get('dots', 0))) * scale
                        if child.get('grace'):   # grace chord — skip
                            pass
                        else:
                            cands = [proc_note(n,
                                               dur_override=child.get('dur', '4'),
                                               dots_override=int(child.get('dots', 0)),
                                               onset=onset, scale=scale)
                                     for n in child.findall(tag_pfx + 'note')]
                            cands = [c for c in cands if c]
                            if cands:
                                voices[key].append(max(cands, key=lambda x: x[4]))
                            pos += dur
                            pos_real = pos
                    elif t in ('rest', 'space'):
                        dur = _to_quarters(child.get('dur', '4'), int(child.get('dots', 0))) * scale
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
        if max_pos > 0 and (measure_el.get('metcon') == 'false' or
                            max_pos < beats_per_measure - 1e-9):
            measure_onset += max_pos
        else:
            measure_onset += beats_per_measure

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
                    while cur in tie_start_to_end:
                        eid = tie_start_to_end[cur]
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
    Returns [(diatonic_interval, dur_of_first_note, nid_first, nid_second, onset_quarters, phase,
              contiguous, dp0), ...]
    dp0: absolute diatonic pitch of the first note (oct*7 + step) — used for transposition tracking.
    """
    result = []
    for i in range(len(notes) - 1):
        nid0, pname0, oct0, dur0, _, onset0 = notes[i]
        nid1, pname1, oct1, _,   _, onset1  = notes[i + 1]
        dp0 = oct0 * 7 + _DIATONIC_STEP.get(pname0.lower(), 0)
        dp1 = oct1 * 7 + _DIATONIC_STEP.get(pname1.lower(), 0)
        phase0 = _metric_phase(onset0, dur0, beat_dur_q)
        contiguous = round((onset0 + dur0) * 16) == round(onset1 * 16)
        result.append((dp1 - dp0, dur0, nid0, nid1, onset0, phase0, contiguous, dp0))
    return result


def _find_motifs(all_seqs, min_len=2, min_count=2, max_motifs=50, max_pat_len=None):
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
            dp0_first   = seq[start][7]
            max_ln = (n - start) if max_pat_len is None else min(max_pat_len, n - start)
            for ln in range(min_len, max_ln + 1):
                if not all(seq[start + k][6] for k in range(ln)):
                    break
                body  = tuple((s[0], s[1]) for s in seq[start:start + ln])
                key   = (body, start_phase)
                nids  = [seq[start][2]] + [seq[start + k][3] for k in range(ln)]
                onset = seq[start][4]
                pat_voice_raw[key][vi].append((start, nids, onset, dp0_first))

    # Step 2: greedy non-overlapping selection per voice + cross-voice same-beat dedup
    pat_occs = defaultdict(list)   # key -> [(nids, dp0_first), ...]
    for (body, phase), voice_dict in pat_voice_raw.items():
        ln = len(body)
        all_with_onset = []
        for _vi, positions in voice_dict.items():
            last_end = -1
            for start, nids, onset, dp0_first in positions:
                if start >= last_end:
                    all_with_onset.append((onset, nids, dp0_first))
                    last_end = start + ln + 1
        all_with_onset.sort(key=lambda x: x[0])
        seen_onsets = set()
        for onset, nids, dp0_first in all_with_onset:
            onset_q = round(onset * 16)
            if onset_q not in seen_onsets:
                pat_occs[(body, phase)].append((nids, dp0_first, onset_q))
                seen_onsets.add(onset_q)

    # Step 3: merge inversions
    # body_inv = tuple((-iv, dur) for iv, dur in body) — absorb into body as inversion=True.
    # Entries are 4-tuples: (nids, dp0, is_inv, onset_q).
    # After merging, remove same-voice overlaps (shared nids) greedily by onset.
    def _deoverlap(occs):
        kept = []
        used_nids = set()
        for occ in sorted(occs, key=lambda x: x[3]):
            nset = set(occ[0])
            if not nset & used_nids:
                kept.append(occ)
                used_nids |= nset
        return kept

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
            absorbed.add(inv_key)
            direct = [(n, d, False, oq) for n, d, oq in pat_occs[key]]
            inv    = [(n, d, True,  oq) for n, d, oq in pat_occs[inv_key]]
            pat_occs[key] = _deoverlap(direct + inv)

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

    candidates.sort(key=lambda x: (len(x[1]), len(x[0][0])), reverse=True)

    def _is_window_shift(p, q):
        if len(p) != len(q):
            return False
        return any(p[k:] == q[:-k] for k in range(1, len(p)))

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


def _search_motif(query):
    """
    Parse query "dur[,dur...];phase;+iv-iv..." (phase optional, default 0).
    Rhythm-only mode: "dur[,dur...];phase" or "dur[,dur...]" — no intervals,
    N durations = N notes, any interval accepted.
    Durations may have operators: >1/16, <=1/8, etc. (default = exact match).
    N+1 durations accepted for N intervals; last one checks last note's duration.
    Returns {"occs": [[nid,...], ...], "count": N}, sorted by onset.
    """
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

    durs = [_parse_dur(s) for s in dur_str.split(',')]

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
        n = len(durs) - 1
        last_dur = durs[n]
        durs = durs[:n]
        intervals = None   # any interval accepted
        pattern = None
    else:
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
        seqs = list(_state.get("seqs", []))
        beat_dur_q = _state.get("beat_dur_q", 1.0)

    # compute phase using the smallest note duration in the pattern as unit
    # rhythm_only: durs elements are (op, val) → s[1] = val
    # interval:    pattern elements are (interval, (op, val)) → s[1][1] = val
    if rhythm_only:
        all_dur_vals = [s[1] for s in durs] + ([last_dur[1]] if last_dur is not None else [])
    else:
        # pattern elements are (contour_char_or_interval, dur_spec); dur_spec = (op, val)
        all_dur_vals = [s[1][1] for s in pattern] + ([last_dur[1]] if last_dur is not None else [])
    min_dur_q = min(all_dur_vals) if all_dur_vals else None

    occs_with_onset = []
    seen_onsets = set()
    for _vk, seq in seqs:
        if len(seq) < n:
            continue
        last_end = -1  # greedy non-overlapping per voice
        for i in range(len(seq) - n + 1):
            if i < last_end:
                continue
            # phase of first note, measured in units of the smallest pattern duration
            if min_dur_q is not None:
                ph = _metric_phase(seq[i][4], min_dur_q, beat_dur_q)
            else:
                ph = seq[i][5]
            if ph != start_phase:
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
                if not (_match_pat(pattern) or
                        (pattern_inv is not None and _match_pat(pattern_inv))):
                    continue
            else:
                def _match_pat(pat):
                    return all((seq[i + k][0] in pat[k][0] if isinstance(pat[k][0], list)
                                else seq[i + k][0] == pat[k][0]) and
                               _dur_matches(seq[i + k][1], pat[k][1])
                               for k in range(n))
                if not (_match_pat(pattern) or
                        (pattern_inv is not None and _match_pat(pattern_inv))):
                    continue
            # check last note's duration: seq[i+n][1] is its duration as first note of next interval
            if last_dur is not None and i + n < len(seq):
                if not _dur_matches(seq[i + n][1], last_dur):
                    continue
            # exclude matches with rests between notes (use precomputed contiguous flag)
            if not all(seq[i + k][6] for k in range(n)):
                continue
            onset_q = round(seq[i][4] * 16)
            if onset_q not in seen_onsets:
                nids = [seq[i][2]] + [seq[i + k][3] for k in range(n)]
                occs_with_onset.append((seq[i][4], nids))
                seen_onsets.add(onset_q)
            last_end = i + n + 1  # greedy: skip overlapping positions in this voice

    occs_with_onset.sort(key=lambda x: x[0])
    occs = [nids for _, nids in occs_with_onset]
    return {"occs": occs, "count": len(occs)}


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
        voices, beat_dur_q = _voice_notes_from_mei(mei_str)
        if beat_dur_q_override is not None:
            beat_dur_q = beat_dur_q_override
        all_seqs = [(vk, _interval_seq(notes, beat_dur_q))
                    for vk, notes in voices.items()
                    if len(notes) >= 4]
        motifs = _find_motifs(all_seqs)
        result = []
        for i, m in enumerate(motifs):
            steps = [_interval_label(iv, dur) for iv, dur in m['pattern']]
            phase = m.get('phase', 0)
            phase_pfx = {0: '', 1: '_|', 2: '_|_|'}.get(phase, '')
            # build transposition profile: (transp, dist) per occurrence
            # dist expressed in units of the motif's minimum note duration
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
            result.append({
                'color':          _MOTIF_COLORS[i % len(_MOTIF_COLORS)],
                'occs':           m['occurrences'],
                'count':          n_occ,
                'length':         L_pat + 1,
                'pattern':        steps,
                'phase_pfx':      phase_pfx,
                'transforms':     transforms,
                'n_direct_only':  m.get('n_direct_only', n_occ),
                'n_inv_only':     m.get('n_inv_only', 0),
                'n_both':         m.get('n_both', 0),
                'queryStr':       _pattern_to_query(m['pattern'], phase),
                'profile':        profile,
                'mdl':            _mdl_score(n_occ, L_pat, transforms),
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


def _beam_groups_from_mei(mei_str):
    """
    Parse MEI and return {nid: beam_group_id (int)} for every note inside a <beam>.
    Notes in the same <beam> element share the same beam_group_id.
    Nested beams (e.g. inside tuplets) are treated independently.
    """
    import xml.etree.ElementTree as _ET
    _PFX = '{%s}' % _MEI_NS
    tree = _ET.fromstring(mei_str)
    beam_of = {}
    bid = 0
    for beam_el in tree.iter(_PFX + 'beam'):
        nids = [n.get(_XML_ID) for n in beam_el
                if n.tag.split('}')[-1] == 'note' and n.get(_XML_ID)
                and not n.get('grace')]
        if len(nids) >= 2:
            for nid in nids:
                if nid:
                    beam_of[nid] = bid
            bid += 1
    return beam_of


def _mini_staff_svg(notes_info, beam_of=None):
    """
    Draw a tiny SVG staff with proper durations: beams, flags, dots, stems.
    notes_info: [(pname_lower, oct_int, dur_q, midi_val, nid), ...]
    beam_of: optional {nid: beam_group_id} from _beam_groups_from_mei
    """
    if not notes_info:
        return ''
    _DS = {'c': 0, 'd': 1, 'e': 2, 'f': 3, 'g': 4, 'a': 5, 'b': 6}
    _CH = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}

    def dp(p, o):
        return o * 7 + _DS.get(p, 0)

    def flag_count(dq):
        """Number of flags/beams: 0=quarter+, 1=eighth, 2=sixteenth, 3=32nd.
        Triplets are unnormalised: triplet-8th → 1 flag, triplet-16th → 2 flags."""
        # Detect triplet: dq*3 is a power of 2
        x = dq * 3
        d = x / 2 if any(abs(x - 2**p) < 0.02 for p in range(-4, 5)) else dq
        if d >= 1.0:   return 0
        if d >= 0.5:   return 1
        if d >= 0.25:  return 2
        return 3

    def is_dotted(dq):
        return abs(dq / 1.5 * 8 - round(dq / 1.5 * 8)) < 0.02 and abs(dq - round(dq)) > 0.1

    def is_triplet(dq):
        x = dq * 3
        return any(abs(x - 2**p) < 0.02 for p in range(-3, 4))

    avg   = sum(dp(p, o) for p, o, *_ in notes_info) / len(notes_info)
    treble = avg >= 26
    bot_d  = 30 if treble else 18   # E4 / G2
    top_d  = bot_d + 8
    mid_d  = bot_d + 4              # middle line

    LS    = 4;    HLS   = 2.0
    HR    = 3.0;  VR    = 2.0
    STEM  = 14
    CLEF_W = 14;  NSP = 16
    PL = 3;       PR  = 5
    BEAM_W = 2.2; BEAM_GAP = 3.0
    FLAG_W = 5;   FLAG_H = 4

    n      = len(notes_info)
    all_d  = [dp(p, o) for p, o, *_ in notes_info]
    flags  = [flag_count(t[2]) for t in notes_info]

    extra_top = max(0, int((max(all_d) - top_d) * HLS) + 6) if max(all_d) > top_d else 0
    extra_bot = max(0, int((bot_d - min(all_d)) * HLS) + 5) if min(all_d) < bot_d else 0
    PT   = 10 + extra_top
    PB   = 5  + extra_bot
    SBOT = PT + 4 * LS
    W    = PL + CLEF_W + n * NSP + PR
    H    = PT + 4 * LS + PB

    # ── note y positions ──────────────────────────────────────────────────────
    note_ys = [SBOT - (dp(p, o) - bot_d) * HLS for p, o, *_ in notes_info]
    note_xs = [PL + CLEF_W + j * NSP + NSP // 2 for j in range(n)]
    mid_y   = SBOT - (mid_d - bot_d) * HLS

    # ── beam groups ───────────────────────────────────────────────────────────
    # Each group: {'j0': int, 'j1': int, 'fc': int, 'dir': str}
    beam_groups = []
    if beam_of is not None and len(notes_info[0]) >= 5:
        # Build groups from MEI beam membership of consecutive notes
        j = 0
        while j < n:
            nid = notes_info[j][4]
            bid = beam_of.get(nid)
            if bid is not None:
                k = j + 1
                while k < n and len(notes_info[k]) >= 5 and beam_of.get(notes_info[k][4]) == bid:
                    k += 1
                if k - j >= 2:
                    fc = min(flag_count(notes_info[i][2]) for i in range(j, k))
                    if fc >= 1:
                        beam_groups.append({'j0': j, 'j1': k - 1, 'fc': fc})
                        j = k
                        continue
            j += 1
    # Fallback: beam all if same flag count ≥ 1
    if not beam_groups and n >= 2 and min(flags) >= 1 and len(set(flags)) == 1:
        beam_groups.append({'j0': 0, 'j1': n - 1, 'fc': flags[0]})

    beamed = [False] * n
    for bg in beam_groups:
        for j in range(bg['j0'], bg['j1'] + 1):
            beamed[j] = True

    # ── stem directions ───────────────────────────────────────────────────────
    dirs = [None] * n
    for bg in beam_groups:
        ys_g = [note_ys[j] for j in range(bg['j0'], bg['j1'] + 1)]
        bdir = 'up' if sum(1 for y in ys_g if y >= mid_y) >= len(ys_g) / 2 else 'down'
        bg['dir'] = bdir
        for j in range(bg['j0'], bg['j1'] + 1):
            dirs[j] = bdir
    for j in range(n):
        if dirs[j] is None:
            dirs[j] = 'up' if note_ys[j] >= mid_y else 'down'

    # stem x and raw tip y
    stem_xs = [(note_xs[j] + HR - 0.5 if dirs[j] == 'up' else note_xs[j] - HR + 0.5)
               for j in range(n)]
    stem_ys = [(note_ys[j] - STEM if dirs[j] == 'up' else note_ys[j] + STEM)
               for j in range(n)]

    # Level/slant each beam group
    for bg in beam_groups:
        j0, j1, bdir = bg['j0'], bg['j1'], bg['dir']
        y0, yn = stem_ys[j0], stem_ys[j1]
        x0, xn = stem_xs[j0], stem_xs[j1]
        for j in range(j0, j1 + 1):
            t = (stem_xs[j] - x0) / (xn - x0) if xn != x0 else 0
            target = y0 + t * (yn - y0)
            if bdir == 'up':
                stem_ys[j] = min(target, note_ys[j] - STEM)
            else:
                stem_ys[j] = max(target, note_ys[j] + STEM)

    # ── SVG output ────────────────────────────────────────────────────────────
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'style="display:inline-block;vertical-align:middle;flex-shrink:0">']

    # staff lines
    x1 = PL + CLEF_W - 2;  x2 = W - PR
    for i in range(5):
        y = SBOT - i * LS
        out.append(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" '
                   f'stroke="#666" stroke-width="0.6"/>')

    # clef
    cc  = '\U0001D11E' if treble else '\U0001D122'
    cfs = LS * 5 if treble else LS * 3
    cy0 = SBOT + (1 if treble else 0)
    out.append(f'<text x="{PL}" y="{cy0}" font-size="{cfs}" '
               f'font-family="serif" fill="#555">{cc}</text>')

    # ── beams (drawn before note heads) ──────────────────────────────────────
    # Beams pack from stem tip TOWARD the note head:
    #   stems UP   → beams go DOWN from tip (y increases)  → offset = +bl*BEAM_GAP
    #   stems DOWN → beams go UP from tip  (y decreases)   → offset = -bl*BEAM_GAP
    # In both cases offset = bl * BEAM_GAP * sign  (sign=+1 UP, -1 DOWN),
    # and beam_y = stem_tip + offset.

    def _beam_line(xs, ys, xe, ye):
        return (f'<line x1="{xs:.1f}" y1="{ys:.1f}" x2="{xe:.1f}" y2="{ye:.1f}" '
                f'stroke="#555" stroke-width="{BEAM_W:.1f}"/>')

    for bg in beam_groups:
        j0, j1, fc, bdir = bg['j0'], bg['j1'], bg['fc'], bg['dir']
        sign = 1 if bdir == 'up' else -1   # +1 = beams go downward from tip

        def _by(tip_y, bl):
            return tip_y + bl * BEAM_GAP * sign

        # Full beams at levels 0..fc-1 (span whole group)
        for bl in range(fc):
            out.append(_beam_line(stem_xs[j0], _by(stem_ys[j0], bl),
                                  stem_xs[j1], _by(stem_ys[j1], bl)))

        # Partial / extra beams for notes with more flags than group minimum
        max_fc = max(flags[jj] for jj in range(j0, j1 + 1))
        for bl in range(fc, max_fc):
            jj = j0
            while jj <= j1:
                if flags[jj] > bl:
                    kk = jj + 1
                    while kk <= j1 and flags[kk] > bl:
                        kk += 1
                    if kk - jj >= 2:
                        out.append(_beam_line(stem_xs[jj], _by(stem_ys[jj], bl),
                                              stem_xs[kk - 1], _by(stem_ys[kk - 1], bl)))
                    else:
                        # partial beam toward adjacent note
                        pdir = 1 if jj == j0 else -1   # right for first, left otherwise
                        xe = stem_xs[jj] + pdir * NSP * 0.4
                        # y on the slope of the beam
                        if stem_xs[j1] != stem_xs[j0]:
                            t  = (stem_xs[jj] - stem_xs[j0]) / (stem_xs[j1] - stem_xs[j0])
                            ty = stem_ys[j0] + t * (stem_ys[j1] - stem_ys[j0])
                        else:
                            ty = stem_ys[jj]
                        out.append(_beam_line(stem_xs[jj], _by(ty, bl), xe, _by(ty, bl)))
                    jj = kk
                else:
                    jj += 1

        # triplet "3" label — placed outside the beam group (away from note heads)
        if is_triplet(notes_info[j0][2]):
            # for UP: above stem tip (y smaller); for DOWN: below stem tip (y larger)
            br_y = stem_ys[j0] - sign * 5
            mid_x = (stem_xs[j0] + stem_xs[j1]) / 2
            out.append(f'<text x="{mid_x:.1f}" y="{br_y:.1f}" font-size="6" '
                       f'text-anchor="middle" font-family="sans-serif" fill="#666">3</text>')

    # ── notes ─────────────────────────────────────────────────────────────────
    for j, note_t in enumerate(notes_info):
        pn, oi, dq, mv = note_t[0], note_t[1], note_t[2], note_t[3]
        cx  = note_xs[j]
        cy  = note_ys[j]
        d_v = dp(pn, oi)

        # accidental
        nat = (oi + 1) * 12 + _CH.get(pn, 0)
        acc = mv - nat
        if acc:
            ac = '\u266f' if acc > 0 else '\u266d'
            out.append(f'<text x="{cx - 5}" y="{cy + 2:.1f}" font-size="7" '
                       f'font-family="serif" fill="#555">{ac}</text>')

        # note head
        filled = dq < 2.0
        fill   = '#555' if filled else 'white'
        out.append(f'<ellipse cx="{cx}" cy="{cy:.1f}" rx="{HR}" ry="{VR}" '
                   f'fill="{fill}" stroke="#555" stroke-width="0.7" '
                   f'transform="rotate(-15,{cx},{cy:.1f})"/>')

        # augmentation dot
        if is_dotted(dq):
            out.append(f'<circle cx="{cx + HR + 2:.1f}" cy="{cy - 0.5:.1f}" '
                       f'r="1" fill="#555"/>')

        # stem
        if dq < 4.0:
            sx = stem_xs[j]; sy = stem_ys[j]
            out.append(f'<line x1="{sx:.1f}" y1="{cy:.1f}" x2="{sx:.1f}" y2="{sy:.1f}" '
                       f'stroke="#555" stroke-width="0.7"/>')

            # individual flags (when not beamed)
            if not beamed[j] and flags[j] >= 1:
                for fi in range(flags[j]):
                    fy = sy + fi * (FLAG_H + 1) * (1 if dirs[j] == 'up' else -1)
                    if dirs[j] == 'up':
                        out.append(f'<path d="M{sx:.1f},{fy:.1f} '
                                   f'C{sx+FLAG_W*0.7:.1f},{fy:.1f} '
                                   f'{sx+FLAG_W:.1f},{fy+FLAG_H*0.5:.1f} '
                                   f'{sx+FLAG_W*0.8:.1f},{fy+FLAG_H:.1f}" '
                                   f'stroke="#555" stroke-width="0.8" fill="none"/>')
                    else:
                        out.append(f'<path d="M{sx:.1f},{fy:.1f} '
                                   f'C{sx+FLAG_W*0.7:.1f},{fy:.1f} '
                                   f'{sx+FLAG_W:.1f},{fy-FLAG_H*0.5:.1f} '
                                   f'{sx+FLAG_W*0.8:.1f},{fy-FLAG_H:.1f}" '
                                   f'stroke="#555" stroke-width="0.8" fill="none"/>')

        # ledger lines below staff
        if d_v < bot_d:
            for ld in range(bot_d - 2, d_v - 1, -2):
                ly = SBOT + (bot_d - ld) * HLS
                out.append(f'<line x1="{cx-HR-1:.1f}" y1="{ly:.1f}" '
                           f'x2="{cx+HR+1:.1f}" y2="{ly:.1f}" '
                           f'stroke="#555" stroke-width="0.6"/>')

        # ledger lines above staff
        if d_v > top_d:
            for ld in range(top_d + 2, d_v + 2, 2):
                ly = SBOT - (ld - bot_d) * HLS
                out.append(f'<line x1="{cx-HR-1:.1f}" y1="{ly:.1f}" '
                           f'x2="{cx+HR+1:.1f}" y2="{ly:.1f}" '
                           f'stroke="#555" stroke-width="0.6"/>')

    out.append('</svg>')
    return ''.join(out)


def render_score(path: str, version: str = "1") -> tuple:
    """Returns (html, n_pages, version). Raises RuntimeError on failure."""
    check_file(path)
    _has_tsd = os.path.basename(path) in _TSD_DATA
    _vtk.setOptions({
        "pageWidth":        2200,
        "adjustPageHeight": True,
        "scale":            35,
        "font":             "Leipzig",
        "spacingSystem":    16 if _has_tsd else 8,
    })
    ext = path.rsplit('.', 1)[-1].lower()
    try:
        if ext == 'mxl':
            import zipfile as _zf
            with _zf.ZipFile(path) as z:
                xml_name = next(n for n in z.namelist()
                                if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n)
                raw = z.read(xml_name)
                if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                    content = raw.decode('utf-16')
                elif raw[:3] == b'\xef\xbb\xbf':
                    content = raw.decode('utf-8-sig')
                else:
                    content = raw.decode('utf-8', errors='replace')
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        if ext == 'krn':
            content = prepare_grand_staff(content)
            content = add_beam_markers(content)
        elif ext in ('xml', 'musicxml'):
            content = _fix_implicit_pickup_measures(content)
            content = _fix_musicxml_voice_order(content)
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
    # Per-file beat_dur_q override
    _path_lower = str(path).lower().replace('\\', '/')
    _beat_override = next(
        (v for k, v in _BEAT_DUR_OVERRIDES.items() if k in _path_lower), None)
    motifs = analyze_motifs(_vtk, mei_str=mei_str, beat_dur_q_override=_beat_override)

    # compute interval sequences for the /search endpoint + build note label map
    try:
        _voices_s, _beat_dur_q_s = _voice_notes_from_mei(mei_str)
        if _beat_override is not None:
            _beat_dur_q_s = _beat_override
        all_seqs = [(vk, _interval_seq(notes, _beat_dur_q_s))
                    for vk, notes in _voices_s.items() if len(notes) >= 4]
        _ACC_SFX = {0: '', 1: '#', -1: 'b', 2: '##', -2: 'bb'}
        nid_labels = {}
        for _notes in _voices_s.values():
            for nid, pname, oct_int, _dur, midi_val, _onset in _notes:
                base = _PITCH_CLASS.get(pname.lower(), 0) + (oct_int + 1) * 12
                acc = _ACC_SFX.get(midi_val - base, '')
                nid_labels[nid] = pname.upper() + acc
        # nid → (nid, pname, oct_int, dur_q, midi_val, onset) for mini-staff SVG
        nid_to_note = {n[0]: n for _ns in _voices_s.values() for n in _ns}
        # beam group membership: nid → beam_group_id
        beam_of = _beam_groups_from_mei(mei_str)
    except Exception:
        all_seqs = []
        _beat_dur_q_s = 1.0
        _voices_s = {}
        nid_labels = {}
        nid_to_note = {}
        beam_of = {}

    def _is_smooth(k):
        """True if k = 2^a * 3^b (a,b >= 0)."""
        if k <= 0:
            return False
        while k % 2 == 0:
            k //= 2
        while k % 3 == 0:
            k //= 3
        return k == 1

    motifs.sort(key=lambda m: (_is_smooth(m['count']) and m['count'] >= 8, m['count']), reverse=True)

    reload_js = _RELOAD_JS.format(version=version)

    # ── build motif table rows (auto-detected motifs) ─────────────────────────
    def _row(i, m):
        pfx = m['phase_pfx']
        phase_html = (f'<sub style="letter-spacing:-1px;color:#aaa">{pfx}</sub>'
                      if pfx else '')
        cnt    = m['count']
        n_dir  = m.get('n_direct_only', cnt)
        n_inv  = m.get('n_inv_only', 0)
        n_both = m.get('n_both', 0)
        def _bold(n):
            return f'<b>{n}</b>' if _is_smooth(n) and n >= 8 else str(n)
        if n_inv > 0 or n_both > 0:
            n_dir_total = n_dir + n_both
            n_inv_total = n_inv + n_both
            total       = n_dir + n_inv + n_both
            cnt_html = (
                f'<span style="font-size:11px">'
                f'<span class="cnt-f" data-fi="{i}" data-ff="direct" '
                f'style="cursor:pointer;color:#555" title="только прямые">'
                f'&times;{_bold(n_dir_total)}</span>'
                f'&nbsp;<span class="cnt-f" data-fi="{i}" data-ff="inv" '
                f'style="cursor:pointer;color:#888" title="только инверсии">'
                f'&#x21C5;{_bold(n_inv_total)}</span>'
                f'&nbsp;<span class="cnt-f" data-fi="{i}" data-ff="all" '
                f'style="cursor:pointer;color:#888" title="все">'
                f'&#x2295;{_bold(total)}</span>'
                f'</span>'
            )
        else:
            cnt_html = _bold(cnt)
        mdl = m.get('mdl', 0)
        mdl_html = f'<b>{mdl}</b>' if mdl > 0 else f'<span style="color:#bbb">{mdl}</span>'
        first_nids = m.get('occs', [[]])[0] if m.get('occs') else []
        notes_info = []
        for nid in first_nids:
            if nid in nid_to_note:
                _, pn, oi, dq, mv, _ = nid_to_note[nid]
                notes_info.append((pn.lower(), oi, dq, mv, nid))
        staff_svg = _mini_staff_svg(notes_info, beam_of)
        return (
            f'<tr data-midx="{i}" data-count="{m["count"]}" data-mdl="{mdl}" data-length="{m["length"]}" '
            f'style="border-bottom:1px solid #e8e8e8;cursor:pointer" '
            f'onmouseover="this.style.background=\'#f0f0f0\'" '
            f'onmouseout="if(this.getAttribute(\'data-active\')!==\'1\')this.style.background=\'\'">'
            f'<td style="padding:5px 10px 5px 0;white-space:nowrap">'
            f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
            f'background:{m["color"]};margin-right:5px;vertical-align:middle"></span>'
            f'<b>M{i+1}</b>{phase_html}</td>'
            f'<td style="padding:3px 16px 3px 0">'
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="font-family:monospace;font-size:11px;white-space:nowrap">'
            f'{" &nbsp; ".join(m["pattern"])}</span>'
            f'{staff_svg}</div></td>'
            f'<td style="padding:5px 10px 5px 0;text-align:center">&times;{cnt_html}</td>'
            f'<td style="padding:5px 8px 5px 0;text-align:center;color:#888">{m["length"]}</td>'
            f'<td style="padding:5px 0;text-align:right;font-size:11px;color:#557">{mdl_html}</td>'
            f'</tr>'
        )

    auto_rows = "".join(_row(i, m) for i, m in enumerate(motifs))
    motif_data = [{"color": m["color"], "occs": m["occs"],
                   "transforms": m.get("transforms", []),
                   "queryStr": m.get("queryStr", ""),
                   "profile": m.get("profile", []),
                   "mdl": m.get("mdl", 0)}
                  for m in motifs]
    motif_json = json.dumps(motif_data)
    note_labels_json = json.dumps(nid_labels)

    # ── TSD harmony labels ────────────────────────────────────────────────────
    _basename = os.path.basename(path)
    _tsd_labels_out = []
    _tsd_nids_out = []
    if _basename in _TSD_DATA:
        _bar_dur_q_tsd, _tsd_labels_out = _TSD_DATA[_basename]
        # flat list of (onset_q, nid) from all voices, sorted by onset
        _flat = sorted(
            (onset_q, nid)
            for note_list in _voices_s.values()
            for nid, _p, _o, _d, _m, onset_q in note_list
        )
        for _i in range(len(_tsd_labels_out)):
            _t0 = _i * _bar_dur_q_tsd
            _t1 = _t0 + _bar_dur_q_tsd
            # First choice: any note starting in [t0, t1)
            _anchor = next(
                (nid for onset_q, nid in _flat if _t0 <= onset_q < _t1), None
            )
            # Fallback: nearest note within ±one window width (inclusive)
            if _anchor is None:
                _nearby = [(abs(onset_q - _t0), onset_q, nid) for onset_q, nid in _flat
                           if abs(onset_q - _t0) <= _bar_dur_q_tsd]
                if _nearby:
                    _anchor = min(_nearby)[2]
            _tsd_nids_out.append(_anchor)
    tsd_json      = json.dumps(_tsd_labels_out)
    tsd_nids_json = json.dumps(_tsd_nids_out)

    # ── legend panel (always shown — contains search input + table) ───────────
    legend_html = (
        f'<div style="font:12px sans-serif;color:#333;margin-bottom:12px;'
        f'padding:8px 14px 10px;background:#fafafa;border:1px solid #ddd;border-radius:5px">'
        f'<div style="font-weight:bold;font-size:13px;margin-bottom:6px">&#127925; Мотивы '
        f'<span style="font-weight:normal;font-size:10px;color:#999">'
        f'(кликни по строке чтобы выделить вхождения)</span></div>'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">'
        f'<input id="motif-search-input" type="text" placeholder="1/16;0;+2-1  или  1/16;0;+2|3-1|2" '
        f'style="font:12px monospace;padding:4px 8px;border:1px solid #ccc;border-radius:4px;width:200px" '
        f'onkeydown="if(event.key===\'Enter\')window.searchMotif()">'
        f'<button onclick="window.searchMotif()" '
        f'style="font:12px sans-serif;padding:4px 10px;border:1px solid #bbb;'
        f'border-radius:4px;background:#f5f5f5;cursor:pointer">Найти</button>'
        + (f'<button id="tsd-btn" onclick="window.toggleTSD()" '
           f'style="font:12px sans-serif;padding:4px 10px;border:1px solid #bbb;'
           f'border-radius:4px;background:#f5f5f5;cursor:pointer">TSD</button>'
           if _tsd_labels_out else '')
        + f'<span id="motif-search-status" style="font:11px sans-serif;color:#888"></span>'
        f'</div>'
        f'<table id="motif-dict" style="border-collapse:collapse">'
        f'<thead><tr style="color:#888;font-size:10px;border-bottom:2px solid #ccc">'
        f'<th style="text-align:left;padding:0 10px 4px 0">Мотив</th>'
        f'<th style="text-align:left;padding:0 16px 4px 0">Паттерн (&uarr;&darr; интервал, длит.)</th>'
        f'<th id="sort-count-hdr" style="padding:0 10px 4px 0;cursor:pointer" '
        f'title="Сортировать по числу вхождений">Вхожд.&#9660;</th>'
        f'<th id="sort-length-hdr" style="padding:0 8px 4px 0;text-align:center;cursor:pointer" '
        f'title="Сортировать по числу нот">Нот</th>'
        f'<th id="sort-mdl-hdr" style="padding:0 0 4px 0;cursor:pointer;text-align:right" '
        f'title="Сортировать по MDL-оценке">MDL</th>'
        f'</tr></thead>'
        f'<tbody>{auto_rows}</tbody>'
        f'</table></div>'
    )

    # ── combined script (highlight + search) ─────────────────────────────────
    motif_script = f"""<script>
(function(){{
var motifs={motif_json};
var noteLabels={note_labels_json};
var customMotifs=[];
var CUSTOM_COLORS=['#ff6b35','#c77dff','#06d6a0','#ffd166'];
var activeKey=null;
var activeFilter='all';
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

function drawBoxes(m){{
  clearRects();
  m.occs.forEach(function(occ,occIdx){{
    var svgList=[]; var svgSysGroups=[];
    occ.forEach(function(id){{
      var el=document.getElementById(id); if(!el)return;
      try{{
        var svg=el.closest('svg');
        var cr=el.getBoundingClientRect();
        if(cr.width<=0&&cr.height<=0)return;
        var si=svgList.indexOf(svg);
        if(si===-1){{si=svgList.length; svgList.push(svg); svgSysGroups.push([]);}}
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
          txt.setAttribute('cursor', 'default');
          (function(occNids){{
            var tip=document.getElementById('motif-tooltip');
            txt.addEventListener('mouseenter',function(e){{
              var names=occNids.map(function(id){{return noteLabels[id]||'?';}}).join(' ');
              tip.textContent=names;
              tip.style.display='block';
              tip.style.left=(e.clientX+12)+'px';
              tip.style.top=(e.clientY-8)+'px';
            }});
            txt.addEventListener('mousemove',function(e){{
              tip.style.left=(e.clientX+12)+'px';
              tip.style.top=(e.clientY-8)+'px';
            }});
            txt.addEventListener('mouseleave',function(){{
              tip.style.display='none';
            }});
          }})(occ);
          svg.appendChild(txt);
          drawnRects.push(txt);
        }}
      }});
    }});
  }});
}}

document.addEventListener('keydown',function(e){{
  if(e.key==='Backspace'&&e.target.tagName!=='INPUT'&&e.target.tagName!=='TEXTAREA'){{
    e.preventDefault();
    var d=document.getElementById('motif-dict');
    if(d)d.scrollIntoView({{behavior:'smooth',block:'start'}});
  }}
}});

var _dictSortKey='count';
var _dictSortAsc=false;
var _sortLabels={{count:'Вхожд.',length:'Нот',mdl:'MDL'}};
var _sortHdrs={{count:'sort-count-hdr',length:'sort-length-hdr',mdl:'sort-mdl-hdr'}};
function sortDict(key){{
  if(_dictSortKey===key){{_dictSortAsc=!_dictSortAsc;}}
  else{{_dictSortKey=key;_dictSortAsc=false;}}
  var tbody=document.querySelector('#motif-dict tbody');
  if(!tbody)return;
  tbody.querySelectorAll('tr[id^="motif-profile-"]').forEach(function(r){{r.remove();}});
  var rows=Array.from(tbody.querySelectorAll('tr[data-midx]'));
  var asc=_dictSortAsc;
  rows.sort(function(a,b){{
    var diff=parseFloat(b.getAttribute('data-'+key))-parseFloat(a.getAttribute('data-'+key));
    return asc?-diff:diff;
  }});
  rows.forEach(function(r){{tbody.appendChild(r);}});
  Object.keys(_sortHdrs).forEach(function(k){{
    var el=document.getElementById(_sortHdrs[k]);
    if(!el)return;
    var arrow=(k===_dictSortKey?(asc?'&#9650;':'&#9660;'):'');
    el.innerHTML=_sortLabels[k]+arrow;
  }});
}}
document.addEventListener('DOMContentLoaded',function(){{
  Object.keys(_sortHdrs).forEach(function(k){{
    var el=document.getElementById(_sortHdrs[k]);
    if(el)el.addEventListener('click',function(){{sortDict(k);}});
  }});
}});

function clearActiveRows(){{
  document.querySelectorAll('#motif-dict tr[data-midx],#motif-dict tr[data-cidx]').forEach(function(r){{
    r.style.background=''; r.setAttribute('data-active','0');
  }});
  document.querySelectorAll('.cnt-f').forEach(function(s){{
    s.style.textDecoration=''; s.style.fontWeight='';
  }});
}}

function _filteredOccs(idx,filter){{
  var m=motifs[idx];
  if(filter==='direct') return m.occs.filter(function(_,i){{return !m.transforms[i].inversion;}});
  if(filter==='inv')    return m.occs.filter(function(_,i){{return  m.transforms[i].inversion;}});
  return m.occs;
}}

function _highlightFilter(idx,filter){{
  document.querySelectorAll('.cnt-f[data-fi="'+idx+'"]').forEach(function(s){{
    var active=(s.getAttribute('data-ff')===filter);
    s.style.textDecoration=active?'underline':'';
    s.style.fontWeight=active?'bold':'';
    s.style.fontStyle=active?'italic':'';
    s.style.background=active?'rgba(255,210,60,0.45)':'';
    s.style.borderRadius=active?'3px':'';
    s.style.padding=active?'1px 3px':'';
  }});
}}

function isSmooth(k){{
  if(k<=0)return false;
  while(k%2===0)k/=2;
  while(k%3===0)k/=3;
  return k===1;
}}

function scrollToFirst(m){{
  if(!m.occs||!m.occs[0]||!m.occs[0][0])return;
  var el=document.getElementById(m.occs[0][0]);
  if(el)el.scrollIntoView({{behavior:'smooth',block:'center'}});
}}

function colorMotif(m){{
  m.occs.forEach(function(occ){{
    occ.forEach(function(id){{
      var el=document.getElementById(id);
      if(el)try{{el.setAttribute('fill',m.color);}}catch(e){{}}
    }});
  }});
}}

function highlight(){{
  document.querySelectorAll('.cnt-f').forEach(function(sp){{
    sp.addEventListener('click',function(e){{
      e.stopPropagation();
      var idx=parseInt(this.getAttribute('data-fi'));
      var filter=this.getAttribute('data-ff');
      var key='auto:'+idx;
      var sameActive=(activeKey===key && activeFilter===filter);
      var detailId='motif-profile-'+idx;
      var existingDetail=document.getElementById(detailId);
      if(existingDetail) existingDetail.remove();
      clearRects(); clearActiveRows();
      var st2=document.getElementById('motif-search-status');
      if(sameActive){{
        activeKey=null; activeFilter='all';
        if(st2){{st2.innerHTML='';}}
      }}else{{
        activeKey=key; activeFilter=filter;
        var row=document.querySelector('#motif-dict tr[data-midx="'+idx+'"]');
        if(row){{row.style.background='#e8f0fe';row.setAttribute('data-active','1');}}
        colorMotif(motifs[idx]);
        var occs=_filteredOccs(idx,filter);
        drawBoxes({{occs:occs,color:motifs[idx].color}});
        scrollToFirst({{occs:occs}});
        _highlightFilter(idx,filter);
        if(st2){{
          var badge2='';
          if(filter==='direct')badge2='<span style="background:#1a7f37;color:#fff;border-radius:3px;padding:1px 5px;font-size:10px">\u00d7direct</span> ';
          else if(filter==='inv')badge2='<span style="background:#c05a00;color:#fff;border-radius:3px;padding:1px 5px;font-size:10px">\u21c5inv</span> ';
          st2.innerHTML=badge2+'<b>M'+(idx+1)+'</b>';
        }}
      }}
    }});
  }});
  document.querySelectorAll('#motif-dict tr[data-midx]').forEach(function(row){{
    row.addEventListener('click',function(){{
      var idx=parseInt(this.getAttribute('data-midx'));
      var key='auto:'+idx;
      var wasActive=(activeKey===key && activeFilter==='all');
      var detailId='motif-profile-'+idx;
      var existingDetail=document.getElementById(detailId);
      clearActiveRows();
      if(existingDetail) existingDetail.remove();
      activeFilter='all';
      var st=document.getElementById('motif-search-status');
      if(wasActive){{
        clearRects(); activeKey=null;
        if(st){{st.textContent='';st.innerHTML='';}}
      }}else{{
        activeKey=key;
        this.style.background='#e8f0fe';
        this.setAttribute('data-active','1');
        colorMotif(motifs[idx]);
        drawBoxes(motifs[idx]);
        scrollToFirst(motifs[idx]);
        if(st){{st.innerHTML='<b>M'+(idx+1)+'</b>';}}
        var qs=motifs[idx].queryStr;
        if(qs){{
          var inp=document.getElementById('motif-search-input');
          if(inp){{inp.value=qs;}}
        }}
        var prof=motifs[idx].profile;
        if(prof && prof.length>0){{
          var dtr=document.createElement('tr');
          dtr.id=detailId;
          dtr.style.background='#f4f4ff';
          var dtd=document.createElement('td');
          dtd.colSpan=5;
          dtd.style.cssText='padding:3px 10px 5px 20px;font:10px monospace;color:#555;line-height:1.6';
          var html='';
          for(var pi=0;pi<prof.length;pi++){{
            var p=prof[pi];
            var ts=p.transp>=0?'+'+p.transp:String(p.transp);
            var iv=p.inv?'<span style="color:#888">&#x21C5;</span>':'';
            var ds=pi===0?'0':String(p.dist);
            html+='('+iv+'<b>'+ts+'</b>&thinsp;·&thinsp;'+ds+')&ensp;';
          }}
          dtd.innerHTML=html;
          dtr.appendChild(dtd);
          this.parentNode.insertBefore(dtr,this.nextSibling);
        }}
      }}
    }});
  }});
}}

function addCustomMotif(occs,queryStr){{
  var cidx=customMotifs.length;
  var color=CUSTOM_COLORS[cidx%CUSTOM_COLORS.length];
  customMotifs.push({{color:color,occs:occs}});
  occs.forEach(function(occ){{
    occ.forEach(function(id){{
      var el=document.getElementById(id);
      if(el)try{{el.setAttribute('fill',color);}}catch(e){{}}
    }});
  }});
  var tbody=document.querySelector('#motif-dict tbody');
  var tr=document.createElement('tr');
  tr.setAttribute('data-cidx',String(cidx));
  tr.style.borderBottom='1px solid #e8e8e8';
  tr.style.cursor='pointer';
  tr.style.background='#fff8f0';
  var nNotes=occs[0]?occs[0].length:'?';
  var esc=queryStr.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  tr.innerHTML=
    '<td style="padding:5px 10px 5px 0;white-space:nowrap">'+
    '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'+
    'background:'+color+';margin-right:5px;vertical-align:middle"></span>'+
    '<b>M_'+(cidx+1)+'</b></td>'+
    '<td style="padding:5px 16px 5px 0;font-family:monospace;font-size:11px">'+esc+'</td>'+
    '<td style="padding:5px 10px 5px 0;text-align:center">\xd7'+(isSmooth(occs.length)&&occs.length>=8?'<b>'+occs.length+'</b>':occs.length)+'</td>'+
    '<td style="padding:5px 0;text-align:center;color:#888">'+nNotes+'</td>';
  tbody.insertBefore(tr,tbody.firstChild);
  tr.addEventListener('click',function(){{
    var key='custom:'+cidx;
    var wasActive=(activeKey===key);
    clearActiveRows();
    if(wasActive){{
      clearRects(); activeKey=null;
    }}else{{
      activeKey=key;
      tr.style.background='#e8f0fe';
      tr.setAttribute('data-active','1');
      drawBoxes(customMotifs[cidx]);
      scrollToFirst(customMotifs[cidx]);
    }}
  }});
  clearActiveRows();
  activeKey='custom:'+cidx;
  tr.style.background='#e8f0fe';
  tr.setAttribute('data-active','1');
  drawBoxes({{color:color,occs:occs}});
  scrollToFirst({{occs:occs}});
}}

function _invertQueryStr(q){{
  // Invert the intervals part of a query string "dur;phase;ivs" → "dur;phase;-ivs"
  var parts=q.split(';');
  if(parts.length<3)return null;
  var ivPart=parts[2];
  // Check it's an interval/contour pattern (not empty)
  if(!ivPart)return null;
  var invIv=ivPart.replace(/([+\\-])(\\d*)/g,function(m,sign,num){{
    return(sign==='+' ? '-' : '+')+num;
  }});
  if(invIv===ivPart)return null; // nothing changed (no + or -)
  return parts[0]+';'+parts[1]+';'+invIv;
}}

function _findDictMatch(query){{
  // Returns {{idx, filter}} if query matches an existing auto-detected motif, else null.
  // filter: 'direct' | 'inv' | 'all'
  var hasInv=/;inv\\s*$/.test(query);
  var base=query.replace(/;inv\\s*$/,'').trim();
  var invBase=_invertQueryStr(base);
  for(var i=0;i<motifs.length;i++){{
    var mq=motifs[i].queryStr;
    if(!mq)continue;
    if(base===mq){{
      // Direct match: user typed the motif's own query (±;inv suffix)
      // ;inv means "show me the inverted variant of this motif"
      var filter=hasInv?'inv':'direct';
      var variant=hasInv?'inv':'direct';
      return{{idx:i,filter:filter,variant:variant}};
    }}
    if(invBase&&invBase===mq){{
      // User typed the inverted form of this motif's query (±;inv suffix)
      var filter2=hasInv?'direct':'inv';
      var variant2=hasInv?'direct':'inv';
      return{{idx:i,filter:filter2,variant:variant2}};
    }}
  }}
  return null;
}}

function _activateDictRow(match, st){{
  var idx=match.idx; var filter=match.filter; var variant=match.variant;
  var row=document.querySelector('#motif-dict tr[data-midx="'+idx+'"]');
  if(!row)return;
  clearActiveRows(); clearRects();
  activeKey='auto:'+idx; activeFilter=filter;
  row.style.background='#e8f0fe';
  row.setAttribute('data-active','1');
  row.scrollIntoView({{behavior:'smooth',block:'nearest'}});
  colorMotif(motifs[idx]);
  var occs=_filteredOccs(idx,filter);
  drawBoxes({{occs:occs,color:motifs[idx].color}});
  scrollToFirst({{occs:occs}});
  _highlightFilter(idx,filter);
  // Status badge
  var label=motifs[idx].queryStr;
  var n=idx+1;
  var badge,bcolor;
  if(variant==='direct'){{badge='\u00d7direct';bcolor='#1a7f37';}}
  else if(variant==='inv'){{badge='\u21c5inv';bcolor='#c05a00';}}
  else{{badge='\u2295all';bcolor='#1a55a0';}}
  st.innerHTML='<span style="background:'+bcolor+';color:#fff;border-radius:3px;padding:1px 5px;font-size:10px">'+badge+'</span>'
    +' <b>M'+n+'</b>';
}}

window.searchMotif=function(){{
  var inp=document.getElementById('motif-search-input');
  var st=document.getElementById('motif-search-status');
  var query=inp.value.trim();
  if(!query)return;
  // Check if query matches an existing dictionary motif
  var match=_findDictMatch(query);
  if(match){{_activateDictRow(match,st);return;}}
  st.style.color='#888'; st.textContent='\u2026';
  fetch('/search',{{method:'POST',headers:{{'Content-Type':'text/plain'}},body:query}})
  .then(function(r){{return r.json();}})
  .then(function(data){{
    if(data.error){{st.style.color='#c0392b';st.textContent=data.error;return;}}
    st.style.color='#888';
    if(data.count===0){{st.textContent='\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e';return;}}
    st.textContent='';
    addCustomMotif(data.occs,query);
  }})
  .catch(function(e){{st.style.color='#c0392b';st.textContent=String(e);}});
}};

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',highlight);
else highlight();

// ── TSD harmony labels ──────────────────────────────────────────────────────
var tsdLabels={tsd_json};
var tsdNids={tsd_nids_json};
var TSD_COLOR={{'T':'#2ecc40','S':'#0074d9','D':'#e74c3c'}};
var _tsdElems=[];
var _tsdVisible=false;

function _buildTsdOverlay(){{
  if(_tsdElems.length)return;
  // RLE: collapse consecutive same labels → T2, D3, etc.
  var _runs=[];
  var _ri=0;
  while(_ri<tsdLabels.length){{
    var _rj=_ri+1;
    while(_rj<tsdLabels.length&&tsdLabels[_rj]===tsdLabels[_ri])_rj++;
    _runs.push({{lbl:tsdLabels[_ri],cnt:_rj-_ri,idx:_ri}});
    _ri=_rj;
  }}
  for(var _ti=0;_ti<_runs.length;_ti++){{
    var nid=tsdNids[_runs[_ti].idx];
    var lbl=_runs[_ti].lbl;
    var txt=_runs[_ti].cnt>1?lbl+_runs[_ti].cnt:lbl;
    if(!nid||!lbl)continue;
    var el=document.getElementById(nid);
    if(!el)continue;
    // Find parent SVG
    var svg=el;
    while(svg&&svg.tagName&&svg.tagName.toLowerCase()!=='svg')svg=svg.parentNode;
    if(!svg)continue;
    // Find ancestor system <g class="system">
    var sys=el;
    while(sys&&sys!==svg){{
      if(sys.getAttribute&&sys.getAttribute('class')==='system')break;
      sys=sys.parentNode;
    }}
    if(!sys||sys===svg)sys=null;
    var noteBB=el.getBBox();
    var _sr=svg.getBoundingClientRect(),_vb=svg.viewBox.baseVal;
    var _px=(_sr.width&&_vb&&_vb.width)?_vb.width/_sr.width:0;
    var x=noteBB.x+15*_px;
    var sysBB=sys?sys.getBBox():null;
    var fs=sysBB?sysBB.height*0.12:noteBB.height*4.5;
    var y=sysBB?(sysBB.y+sysBB.height+fs*1.8):(noteBB.y+noteBB.height+fs*2.0);
    var t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x',x);
    t.setAttribute('y',y);
    t.setAttribute('text-anchor','start');
    t.setAttribute('font-size',String(fs));
    t.setAttribute('font-family','sans-serif');
    t.setAttribute('font-weight','bold');
    t.setAttribute('fill',TSD_COLOR[lbl]||'#333');
    t.setAttribute('pointer-events','none');
    t.setAttribute('display','none');
    t.textContent=txt;
    svg.appendChild(t);
    _tsdElems.push(t);
  }}
}}

window.toggleTSD=function(){{
  _buildTsdOverlay();
  _tsdVisible=!_tsdVisible;
  for(var _i=0;_i<_tsdElems.length;_i++){{
    _tsdElems[_i].setAttribute('display',_tsdVisible?'inline':'none');
  }}
  var btn=document.getElementById('tsd-btn');
  if(btn){{
    btn.style.background=_tsdVisible?'#fffde7':'#f5f5f5';
    btn.style.borderColor=_tsdVisible?'#e0a800':'#bbb';
    btn.style.fontWeight=_tsdVisible?'bold':'normal';
  }}
  if(_tsdVisible){{var sp=document.getElementById('score-pages');if(sp)sp.scrollIntoView({{behavior:'smooth'}});}}
}};

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
<div id="motif-tooltip" style="display:none;position:fixed;background:rgba(0,0,0,0.78);color:#fff;font:12px monospace;padding:4px 8px;border-radius:4px;pointer-events:none;z-index:9999;white-space:nowrap"></div>
<div class="fn">{os.path.basename(path)}</div>
{legend_html}
<div id="score-pages">{pages}</div>
</body>
</html>"""
    return html, n_pages, version, all_seqs, _beat_dur_q_s

# ── background render + update ────────────────────────────────────────────────

def _render_worker(path: str, version: str, queue):
    """Runs in a subprocess to isolate verovio segfaults from the main process."""
    try:
        html, n_pages, ver, seqs, beat_dur_q = render_score(path, version)
        queue.put(('ok', html, n_pages, ver, seqs, beat_dur_q))
    except Exception as e:
        queue.put(('error', str(e)))


def load_file_bg(path: str, status_cb):
    with _state_lock:
        next_ver = str(int(_state["version"]) + 1)
        _state["version"] = next_ver  # claim version immediately; prevents two concurrent renders getting same ver

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

    _, html, n_pages, ver, seqs, beat_dur_q = result
    with _state_lock:
        _state["html"]       = html
        _state["version"]    = ver
        _state["seqs"]       = seqs
        _state["beat_dur_q"] = beat_dur_q
    _notify_sse(ver)
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

        self._files        = find_generated_files() + find_lilypond_files() + find_kern_files(KERN_DIR) + find_music21_files()
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
        s.configure("TCombobox", fieldbackground="#313244", foreground="#cdd6f4",
                     selectbackground="#45475a", selectforeground="#cdd6f4")
        s.map("TCombobox", fieldbackground=[("readonly", "#313244")],
              foreground=[("readonly", "#cdd6f4")])
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

        ttk.Label(outer, text="SCORES", style="H.TLabel").pack(
            pady=(8, 4), padx=8, anchor="w")

        # composer selector
        composers = ['All'] + sorted({_composer_from_rel(r) for r, _ in self._files})
        self._composer_var = tk.StringVar(value='All')
        composer_box = ttk.Combobox(outer, textvariable=self._composer_var,
                                    values=composers, state='readonly')
        composer_box.pack(fill=tk.X, padx=8, pady=(0, 4))
        composer_box.bind('<<ComboboxSelected>>', lambda *_: self._apply_filter())

        # text search
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        search_entry = ttk.Entry(outer, textvariable=self._search_var)
        search_entry.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.after(100, search_entry.focus_set)
        search_entry.bind("<Tab>", self._focus_tree)

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
        self._tree.tag_configure('group', foreground='#cba6f7',
                                  font=('Segoe UI', 9, 'bold'))
        file_list = files if files is not None else self._files

        # Group by (composer, cycle)
        groups: dict = {}
        order: list = []
        for rel, full in file_list:
            composer = _composer_from_rel(rel)
            cycle = _bach_cycle(rel) if composer == 'Bach' else None
            key = (composer, cycle)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((rel, full))

        def _group_sort_key(key):
            composer, cycle = key
            if composer == 'Bach':
                return (0, _BACH_CYCLE_IDX.get(cycle or '', 99), cycle or '')
            return (1, 0, composer or '')

        sorted_order = sorted(order, key=_group_sort_key)
        total = 0
        use_headers = len(sorted_order) > 1 or (
            sorted_order and sorted_order[0][1] is not None)
        for key in sorted_order:
            composer, cycle = key
            group_files = groups[key]
            if use_headers:
                label = cycle if cycle else (composer or 'Other')
                header = f'{label}  ({len(group_files)})'
                parent = self._tree.insert('', tk.END, text=header,
                                           values=(), tags=('group',))
                self._tree.item(parent, open=False)
            else:
                parent = ''
            for rel, full in group_files:
                self._tree.insert(parent, tk.END,
                                  text=os.path.basename(rel), values=(full,))
            total += len(group_files)
        self._count_var.set(f"{total} file{'s' if total != 1 else ''}")

    def _focus_tree(self, _=None):
        self._tree.focus_set()
        children = self._tree.get_children()
        if children:
            # find first selectable item (not a group header)
            for item in children:
                sub = self._tree.get_children(item)
                if sub:
                    self._tree.selection_set(sub[0])
                    self._tree.focus(sub[0])
                    break
                else:
                    self._tree.selection_set(item)
                    self._tree.focus(item)
                    break
        return "break"  # prevent default Tab behaviour

    def _apply_filter(self):
        q = self._search_var.get().lower()
        composer = self._composer_var.get()
        result = self._files
        if composer and composer != 'All':
            result = [(r, f) for r, f in result if _composer_from_rel(r) == composer]
        if q:
            result = [(r, f) for r, f in result if q in r.lower()]
        self._populate_list(result)

    def _on_select(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        vals = self._tree.item(sel[0], "values")
        if not vals:
            return  # group header clicked
        path = vals[0]
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
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
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

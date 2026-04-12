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
import time
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
    os.path.join("craigsapp", "bach", "chorales-370"),             # 370 Chorales (craigsapp)
    os.path.join("craigsapp", "bach", "musical-offering"),         # Musical Offering BWV 1079
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

_START_VERSION = str(int(time.time()))  # unique per server start → browser always reloads on restart
_state = {
    "html":       f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script>
(function(){{
  var cur="{_START_VERSION}";
  var es=new EventSource('/events');
  es.onmessage=function(e){{
    if(e.data!==cur){{ es.close(); window.location.replace('/?t='+Date.now()); }}
  }};
}})();
</script>
</head><body style='font:16px sans-serif;padding:40px;color:#888'>
Select a kern file in the panel.</body></html>""",
    "version":    _START_VERSION,
    "seqs":             [],    # [(voice_key, interval_seq), ...] for current file
    "beat_dur_q":       1.0,
    "pickup_dur_q":     0.0,
    "repeat_ranges":    [],
    "volta_search_info": None,
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
        if self.path == "/load":
            try:
                length = int(self.headers.get("Content-Length", 0))
                fname = self.rfile.read(length).decode("utf-8").strip()
                match = None
                for root, _dirs, files in os.walk(os.path.dirname(os.path.abspath(__file__))):
                    if fname in files:
                        match = os.path.join(root, fname)
                        break
                if match is None:
                    try:
                        import music21.corpus as _c
                        for p in _c.getCorePaths():
                            if os.path.basename(str(p)) == fname:
                                match = str(p); break
                    except Exception:
                        pass
                if match:
                    import threading
                    threading.Thread(target=load_file_bg, args=(match, lambda s: None), daemon=True).start()
                    body = match.encode()
                    self.send_response(200)
                else:
                    body = b"not found"
                    self.send_response(404)
                self.send_header("Content-Type","text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as _e:
                body = str(_e).encode()
                self.send_response(500)
                self.send_header("Content-Type","text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
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
        if path == "/shutdown":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"bye")
            print("[kern_reader] shutdown requested — new instance starting", flush=True)
            threading.Thread(target=lambda: os._exit(0), daemon=True).start()
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
    'telemann':    'Telemann',
    'monteverdi':  'Monteverdi',
    'mozart':      'Mozart',
    'beethoven':   'Beethoven',
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
    'Orchestral Suites',
    'Organ Sonatas',
    'Orgelbüchlein',
    'Organ Mass (Clavier-Übung III)',
    'Chorale Preludes',
    'Chorale Harmonizations',
    'Cantatas',
    'Passions & Oratorios',
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
    # musedata pattern: musedata_{section}_BWV_{N}[_{mvt}]
    mm = _re.match(r'musedata_(\w+)_bwv_(\d+\w*)', stem, _re.I)
    if mm:
        section, bwv_str = mm.group(1), mm.group(2)
        try:
            n = int(_re.match(r'\d+', bwv_str).group())
        except Exception:
            return 'Other Bach'
        if section == 'cant':   return f'Cantata BWV {n}'
        if section == 'organ':  return _bwv_to_cycle(n)
        if section == 'orch':   return _bwv_to_cycle(n)
        if section == 'vocal':  return _bwv_to_cycle(n)
        if section == 'chamb':  return _bwv_to_cycle(n)
        if section == 'canon':  return 'Art of Fugue'
        return _bwv_to_cycle(n)

    # IMSLP pattern: bach-42-src_bach-42-score → BWV 42
    mb_src = _re.match(r'bach-(\d+)-', stem)
    if mb_src:
        return _bwv_to_cycle(int(mb_src.group(1)))

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
    if stem.startswith('brandenbur') or _re.match(r'brand\d', stem):
        return 'Brandenburg Concertos'
    if stem in ('air', 'air_tromb'):
        return 'Concertos'
    if 'sonataiv' in stem.replace('_', ''):
        return 'Violin Sonatas with Keyboard'
    if 'cantata' in stem:
        mcan = _re.match(r'cantata[_\s](\d+)', stem)
        if mcan:
            return f'Cantata BWV {int(mcan.group(1))}'
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
    if 'anna_magdalena' in stem or 'anna magdalena' in stem:
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
            mb = _re.search(r'bwv[-_]?(\d+)', stem)
            if mb:
                return f'Cantata BWV {int(mb.group(1))}'
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
    # Orchestral suites
    if 1066 <= n <= 1071: return 'Orchestral Suites'
    # Passions & large choral works
    if n in (244, 245, 247, 248): return 'Passions & Oratorios'
    # Cantatas
    if 1 <= n <= 224:    return f'Cantata BWV {n}'
    if 225 <= n <= 249:  return 'Motets & Masses'
    return 'Other Bach'


_DANCE_SHORT = {
    'allemande': 'Allem.', 'courante': 'Cour.', 'sarabande': 'Sarab.',
    'gigue': 'Gigue', 'menuet': 'Men.', 'minuet': 'Men.',
    'gavotte': 'Gav.', 'bourree': 'Bourr.', 'loure': 'Loure',
    'polonaise': 'Pol.', 'prelude': 'Prél.', 'preludio': 'Prél.',
    'praeludium': 'Präl.', 'praeludien': 'Präl.',
    'fugue': 'Fuga', 'fuga': 'Fuga', 'aria': 'Aria',
    'andante': 'And.', 'adagio': 'Adagio', 'sicilian': 'Sic.',
    'chaconne': 'Chac.', 'passacag': 'Passac.', 'ricercar': 'Ricer.',
    'invention': 'Inv.', 'sinfonia': 'Sinf.', 'trio': 'Trio',
}


def _dance_short(s: str) -> str:
    """Return abbreviated dance/movement label found in string s, or ''."""
    for key, val in _DANCE_SHORT.items():
        if key in s:
            return val
    return ''


def _display_title(rel: str) -> str:
    """Return a clean human-readable title for a music file path."""
    import re as _re
    fname = os.path.basename(rel)
    stem  = fname.rsplit('.', 1)[0]
    s     = stem.lower()

    # ── Goldberg Variations ───────────────────────────────────────────────────
    if 'bwv_988' in s or 'bwv988' in s:
        mv = _re.search(r'_v(\d+)', s)
        if mv:  return f"Var. {int(mv.group(1))}"
        if 'aria' in s:  return 'Aria'
        return 'BWV 988'

    # ── Art of Fugue ──────────────────────────────────────────────────────────
    mc = _re.match(r'contrapunctus([ivxlcdm]+)', s)
    if mc:  return f"Ctrp. {mc.group(1).upper()}"
    if s in ('rectus', 'inversus', 'duetto', 'ricercare', 'ricercare6'):
        return stem[0].upper() + stem[1:]

    # ── musedata_{section}_BWV_{N}[_{mvt}] ───────────────────────────────────
    mm = _re.match(r'musedata_\w+_bwv_(\d+\w?)(?:_(\d+))?$', s)
    if mm:
        bwv = mm.group(1).lstrip('0') or '0'
        mvt = mm.group(2)
        return f"BWV {bwv}/{mvt}" if mvt else f"BWV {bwv}"

    # ── IMSLP bach-N-src cantata/ensemble ────────────────────────────────────
    mb_src = _re.match(r'bach-(\d+)-', s)
    if mb_src:  return f"BWV {mb_src.group(1)}"

    # ── Brandenburg Concertos ─────────────────────────────────────────────────
    mb1 = _re.match(r'brandenbur(?:g)?(\d)[_-](\d+)', s)
    if mb1:
        return f"Brandenb. {mb1.group(1)}/{mb1.group(2)}"
    mb2 = _re.match(r'brand(\d)[_-](\d+)', s)
    if mb2:
        return f"Brandenb. {mb2.group(1)}/{mb2.group(2)}"

    # ── Cantata_16_no_5 pattern ───────────────────────────────────────────────
    mcan = _re.match(r'cantata[_\s](\d+)[_\s]no[_\s](\d+)', s)
    if mcan:  return f"Cant. {mcan.group(1)}/No.{mcan.group(2)}"

    # ── Anna Magdalena ────────────────────────────────────────────────────────
    mam = _re.match(r'anna_magdalena_(\w+)', s)
    if mam:  return f"A.M. {mam.group(1).lstrip('0') or '0'}"

    # ── Inventions ────────────────────────────────────────────────────────────
    mi = _re.match(r'bach_invention_?0*(\d+)', s)
    if mi:  return f"Inv. {mi.group(1)}"

    # ── French / English Suite ────────────────────────────────────────────────
    mf = _re.search(r'french_suite[_\s](\d)', s)
    if mf:
        dance = _dance_short(s)
        return f"Fr. Suite {mf.group(1)}" + (f" {dance}" if dance else '')
    me = _re.search(r'english_suite[_\s](\d)', s)
    if me:
        dance = _dance_short(s)
        return f"En. Suite {me.group(1)}" + (f" {dance}" if dance else '')

    # ── Cello suite by name ───────────────────────────────────────────────────
    mcs = _re.match(r'cellosuite(\d+)_cellosuite\d+_(\d+)', s)
    if mcs:  return f"Suite {mcs.group(1)}/{mcs.group(2)}"
    mcs2 = _re.match(r'cellosuite(\d+)_cellosuite\d+', s)
    if mcs2:  return f"Suite {mcs2.group(1)}"

    # ── Numbered partita (partita_1_1_violin) ─────────────────────────────────
    mps = _re.match(r'partita_(\d+)_(\d+)', s)
    if mps:  return f"Part. {mps.group(1)}/{mps.group(2)}"

    # ── Concerto in d/e ───────────────────────────────────────────────────────
    mco = _re.match(r'concerto_in_([a-z])_(minor|major)', s)
    if mco:
        key  = mco.group(1).upper()
        mode = 'moll' if mco.group(2) == 'minor' else 'dur'
        mov  = _re.search(r'_(\d+)$', s)
        return f"Conc. {key}-{mode}" + (f"/{mov.group(1)}" if mov else '')

    # ── mv4_Partita_bwv828, mv14_canons_bwv_1087 ─────────────────────────────
    if 'canons_bwv' in s or ('canon' in s and 'bwv' in s):
        mbwv_c = _re.search(r'bwv[-_]?(\d+)', s)
        bwv_c  = mbwv_c.group(1) if mbwv_c else '1087'
        if s.endswith(f'_bwv_{bwv_c}') or s.endswith(f'_bwv{bwv_c}') or s.endswith(f'-{bwv_c}'):
            return f"Canons BWV {bwv_c}"
        mov_end = _re.search(r'_(\d+)$', s)
        return f"Canon {bwv_c}/{mov_end.group(1)}" if mov_end else f"Canons BWV {bwv_c}"

    mmv = _re.match(r'mv\d+_[^_]+_bwv[-_]?(\d+[a-z]?)(?:_(\d+))?', s)
    if mmv:
        mov = f"/{int(mmv.group(2))}" if mmv.group(2) else ''
        return f"BWV {mmv.group(1)}{mov}"

    # ── SonataIV ──────────────────────────────────────────────────────────────
    msi = _re.match(r'sonata(iv|iii|ii|i|v)_sonata\1(?:_(\d+))?', s)
    if msi:
        mov = f"/{msi.group(2)}" if msi.group(2) else ''
        return f"Sonata {msi.group(1).upper()}{mov}"

    # ── Bach_ chorale names ───────────────────────────────────────────────────
    if stem.startswith('Bach_'):
        name = stem[5:]
        name = _re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
        return name

    # ── BWV number extraction ─────────────────────────────────────────────────
    mbwv = _re.search(r'bwv[-_]?0*(\d+[a-z]?)', s)
    if mbwv:
        raw_n  = mbwv.group(1)
        suffix = s[mbwv.end():]
        # Remove repeated bwv reference (e.g. BWV_827_BWV_827_1 → just _1)
        suffix = _re.sub(r'_?bwv[-_]?\d+[a-z]?', '', suffix)
        # First movement number in suffix
        mov_m = _re.search(r'[-_]0*(\d+)', suffix)
        mov   = f"/{int(mov_m.group(1))}" if mov_m else ''
        # Dance/part descriptor from full string
        dance = _dance_short(s)
        return f"BWV {raw_n}{mov}" + (f" {dance}" if dance else '')

    # ── Fallback: clean up filename ───────────────────────────────────────────
    title = stem.replace('_', ' ').replace('-', ' ')
    return title[0].upper() + title[1:] if title else stem


_HANDEL_WORK_MAP = {
    'semele':    'Semele',
    'rada':      'Radamisto',
    'ariodan':   'Ariodante',
    'atalan':    'Atalanta',
    'poro':      'Poro',
    'mes':       'Messiah',
    'clori':     'Clori',
    'jmac':      'Jmac',
    'ott':       'Ott',
}


def _handel_cycle(stem: str) -> str | None:
    import re as _re
    stem = _re.sub(r'_\d+$', '', stem)      # strip trailing movement number
    if not stem.startswith('handel_'):
        return None
    parts = stem[7:].split('_')              # after 'handel_'
    for part in parts:
        if part in ('op06', 'op6') or _re.match(r'op6n\d+$', part, _re.I):
            return 'Concerti Grossi Op. 6'
        if part == 'op02': return 'Op. 2 Sonatas'
        if part == 'op03': return 'Op. 3 Concerti'
        if part == 'op05': return 'Op. 5 Sonatas'
    for part in reversed(parts):
        if part in _HANDEL_WORK_MAP:
            return _HANDEL_WORK_MAP[part]
        base = _re.sub(r'(\d+|-new)$', '', part)
        if base in _HANDEL_WORK_MAP:
            return _HANDEL_WORK_MAP[base]
    if any(_re.match(r'hwv\d+', p, _re.I) for p in parts):
        return 'Concertos'
    return None


_TELEMANN_ORATORIO_MAP = {
    'orpheus': 'Orpheus',
    'seren':   'Serenade',
}


def _telemann_cycle(stem: str) -> str | None:
    import re as _re
    stem = _re.sub(r'_\d+$', '', stem)      # strip trailing movement number
    if not stem.startswith('telemann_'):
        return None
    parts = stem[9:].split('_')              # after 'telemann_'
    if not parts:
        return None
    t = parts[0]
    if t == 'oratorio':
        name = parts[1] if len(parts) > 1 else ''
        return _TELEMANN_ORATORIO_MAP.get(name, name.capitalize())
    if t == 'chamb' and len(parts) > 1:
        sub = parts[1]
        if sub.startswith('ris-t'):
            return 'RISM T' + sub[5:]        # 'ris-t394' → 'RISM T394'
        if sub == 'vln':
            return 'Violin Sonatas'
    return None


_VIVALDI_OP_NAMES = {
    'op1':      'Op. 1',
    'op2':      'Op. 2',
    'op3':      'Op. 3 (L\'estro armonico)',
    'op4':      'Op. 4 (La stravaganza)',
    'op5':      'Op. 5',
    'op7':      'Op. 7',
    'op8':      'Op. 8 (Il cimento)',
    'op09':     'Op. 9 (La cetra)',
    'op9':      'Op. 9 (La cetra)',
    'op10':     'Op. 10',
    'op10.old': 'Op. 10 (old ed.)',
    'op11':     'Op. 11',
    'op12':     'Op. 12',
}


def _vivaldi_cycle(stem: str) -> str | None:
    import re as _re
    stem = _re.sub(r'_\d+$', '', stem)
    if not stem.startswith('vivaldi_'):
        return None
    parts = stem[8:].split('_')   # after 'vivaldi_'
    # parts[0] = edition (dawson/dover/lecene/micro/roger/op5/autogr)
    # parts[1] = opus or sub-collection
    if not parts:
        return None
    edition = parts[0]
    if edition == 'autogr':
        return 'Autograph MS'
    if len(parts) > 1:
        op = parts[1].lower()
        if op in _VIVALDI_OP_NAMES:
            return _VIVALDI_OP_NAMES[op]
        if op == 'misc':
            return 'Misc.'
    # depth-2: vivaldi_op5_rvXXX → parts[0] = 'op5'
    op = edition.lower()
    if op in _VIVALDI_OP_NAMES:
        return _VIVALDI_OP_NAMES[op]
    return None


_MOZART_GENRE = {
    'conc':   'Concertos',
    'divert': 'Divertimenti',
    'duos':   'Duos',
    'qrtets': 'String Quartets',
    'sym':    'Symphonies',
    'trios':  'Trios',
    'opera':  'Operas',
    'piano':  'Piano',
}

_BEETHOVEN_GENRE = {
    'conc':  'Concertos',
    'orch':  'Symphonies',
    'qrtet': 'String Quartets',
    'qrtets':'String Quartets',
}


def _mozart_cycle(stem: str) -> str | None:
    import re as _re
    stem = _re.sub(r'_\d+$', '', stem)
    if not stem.startswith('mozart_'): return None
    parts = stem[7:].split('_')
    genre = parts[1].lower() if len(parts) > 1 else ''
    return _MOZART_GENRE.get(genre)


def _beethoven_cycle(stem: str) -> str | None:
    import re as _re
    stem = _re.sub(r'_\d+$', '', stem)
    if not stem.startswith('beethoven_'): return None
    parts = stem[10:].split('_')
    genre = parts[1].lower() if len(parts) > 1 else ''
    return _BEETHOVEN_GENRE.get(genre)


def _cycle_from_rel(rel: str, composer: str) -> str | None:
    if composer == 'Bach':
        return _bach_cycle(rel)
    parts = rel.replace('\\', '/').split('/')
    fname = parts[-1]
    stem  = fname.rsplit('.', 1)[0].lower()
    # music21 corpus files: use path segments for cycle detection
    if parts[0] == 'music21':
        if composer == 'Beethoven':
            return 'String Quartets'   # all bundled Beethoven are string quartets
        if composer == 'Mozart':
            # k545 is the piano sonata; everything else in the bundle is quartets
            if any('k545' in p.lower() for p in parts):
                return 'Piano'
            return 'String Quartets'
    if composer == 'Handel':
        return _handel_cycle(stem)
    if composer == 'Telemann':
        return _telemann_cycle(stem)
    if composer == 'Vivaldi':
        return _vivaldi_cycle(stem)
    if composer == 'Mozart':
        return _mozart_cycle(stem)
    if composer == 'Beethoven':
        return _beethoven_cycle(stem)
    return None


def _composer_from_rel(rel: str) -> str:
    parts = rel.replace('\\', '/').split('/')
    if parts[0] == 'music21' and len(parts) > 1:
        return _COMPOSER_MAP.get(parts[1].lower(), parts[1].capitalize())
    # kern/ files — check for non-Bach composers by path segment
    for part in parts:
        if part.lower() in _KERN_COMPOSER:
            return _KERN_COMPOSER[part.lower()]
    # lilypond/ XML files — check filename prefix (e.g. telemann_chamb_...xml)
    fname = parts[-1].lower()
    for key, name in _KERN_COMPOSER.items():
        if fname.startswith(key + '_'):
            return name
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
    """Return [(rel, full), ...] for MusicXML files in lilypond/musicxml/.

    Deduplicates: if a plain bwv_N.xml exists for a given BWV number, any
    other longer filename covering the same BWV without a distinct movement
    number is skipped (e.g. engraving_files_bwv-568.xml is dropped when
    bwv_568.xml is present).
    """
    import re as _re
    xml_dir = os.path.join(os.path.dirname(__file__), 'lilypond', 'musicxml')
    if not os.path.isdir(xml_dir):
        return []
    _EXCLUDED = {'bwv1013.xml', 'bwv1017.xml'}

    all_fnames = sorted(f for f in os.listdir(xml_dir)
                        if f.endswith('.xml') and f not in _EXCLUDED)

    # Build set of BWV numbers covered by "plain" files (stem == bwv_N or bwvN)
    plain_bwv: set = set()
    for fname in all_fnames:
        stem = fname.rsplit('.', 1)[0]
        if _re.match(r'^bwv[-_]?\d+[a-z]?$', stem, _re.I):
            m = _re.search(r'(\d+[a-z]?)', stem, _re.I)
            if m:
                plain_bwv.add(m.group(1).lower())

    # ── Instrument-part exclusion ─────────────────────────────────────────────
    # Explicit single-file exclusions (bare file superseded by score splits)
    _PART_FILES = {'concerto_in_d_minor.xml', 'concerto_in_e_major.xml', 'air_tromb.xml'}

    # Group rules: file starts with prefix → keep only stems matching allowed_re
    _SCORE_GROUPS = {
        'Brandenburg1_1_':                      r'score(_\d+)?$',
        'Brandenburg1_2_':                      r'score(_\d+)?$',
        'brand5_3_':                            r'score(_\d+)?$',
        'bach_air_bach_air_':                   r'score(_\d+)?$',
        'Cantata_16_no_5_':                     r'score(_\d+)?$',
        'concerto_in_d_minor_':                 r'score(_\d+)?$',
        'concerto_in_e_major_':                 r'score(_\d+)?$',
        'BWV1056R_Schreck_BWV1056R_Schreck_':  r'conductor(_\d+)?$',
        'Passacaglia_':                         r'passacag(_\d+)?$',
    }

    files = []
    for fname in all_fnames:
        stem = fname.rsplit('.', 1)[0]
        # Skip if a plain bwv_N.xml already covers the same BWV with no
        # additional movement suffix (digits after the BWV number)
        if not _re.match(r'^bwv[-_]?\d+[a-z]?$', stem, _re.I):
            m = _re.search(r'bwv[-_]?(\d+[a-z]?)', stem, _re.I)
            if m and m.group(1).lower() in plain_bwv:
                rest = stem[m.end():]
                if not _re.search(r'\d', rest):  # no movement digits → duplicate
                    continue

        # Skip explicit part files
        if fname in _PART_FILES:
            continue

        # Skip standard WTC pieces (BWV 846-893, no letter suffix) — covered by .krn collection
        m_wtc = _re.search(r'bwv[-_]?(\d+)([a-z]?)', stem, _re.I)
        if m_wtc and not m_wtc.group(2) and 846 <= int(m_wtc.group(1)) <= 893:
            continue

        # Skip instrument parts when a full score exists for the same group
        skip = False
        for prefix, allowed_re in _SCORE_GROUPS.items():
            if stem.startswith(prefix):
                suffix = stem[len(prefix):]
                if not _re.match(allowed_re, suffix, _re.I):
                    skip = True
                break
        if skip:
            continue

        full = os.path.join(xml_dir, fname)
        files.append((f'lilypond/{fname}', full))
    return files


def _tobis_movements(path):
    """Return [(title, start_mnum, end_mnum), ...] for a tobis MusicXML file.
    Returns [] if no movement markers found (treat as single piece)."""
    import xml.etree.ElementTree as ET
    import re as _re
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []
    root = tree.getroot()
    first_part = root.find('part')
    if first_part is None:
        return []
    all_mnums = [m.get('number', '') for m in first_part.findall('measure')]
    if not all_mnums:
        return []
    mnum_to_idx = {mn: i for i, mn in enumerate(all_mnums)}

    # Collect movement markers across all parts; key = (mnum, seq) to avoid dups
    seen: dict = {}  # (mnum, seq) → title
    for part in root.findall('part'):
        for msr in part.findall('measure'):
            mnum = msr.get('number', '')
            for words_el in msr.findall('.//direction-type/words'):
                text = (words_el.text or '').strip()
                m = _re.match(r'^(\d+)\.\s+(\S)', text)
                if not m:
                    continue
                seq = int(m.group(1))
                key = (mnum, seq)
                if key not in seen:
                    title = _re.sub(r'\s+', ' ', text.rstrip('. '))
                    seen[key] = title

    if len(seen) <= 1:
        return []

    # Sort by measure position, then seq
    entries = sorted(seen.items(), key=lambda x: (mnum_to_idx.get(x[0][0], 0), x[0][1]))

    result = []
    for i, ((mnum, seq), title) in enumerate(entries):
        if i + 1 < len(entries):
            next_mnum = entries[i + 1][0][0]
            next_idx = mnum_to_idx.get(next_mnum, len(all_mnums))
            end_mnum = all_mnums[next_idx - 1] if next_idx > 0 else mnum
        else:
            end_mnum = all_mnums[-1]
        result.append((title, mnum, end_mnum))
    return result


def _infer_time_sig_from_content(measures, divs, fname=''):
    """Infer time signature from measure note content.
    Returns ET.Element for <time> or None if unable to infer.
    Uses note type distribution and dance-form name hint to resolve ambiguous cases
    (3/2 vs 12/8 for 6-quarter-per-bar measures; both are musically distinct)."""
    import xml.etree.ElementTree as ET
    from collections import Counter

    dur_list = []
    note_types = Counter()
    for m in measures:
        per_voice: dict = {}
        for child in m:
            if child.tag != 'note':
                continue
            dur_el = child.find('duration')
            voice_el = child.find('voice')
            chord_el = child.find('chord')
            if dur_el is None or chord_el is not None:
                continue
            v = voice_el.text if voice_el is not None else '1'
            per_voice[v] = per_voice.get(v, 0) + int(dur_el.text)
        if per_voice:
            dur_list.append(Counter(per_voice.values()).most_common(1)[0][0])
        for n in m.iter('note'):
            typ = n.find('type')
            chord = n.find('chord')
            if typ is not None and chord is None:
                note_types[typ.text] += 1

    if not dur_list:
        return None
    mode_dur = Counter(dur_list).most_common(1)[0][0]
    qn = round(mode_dur / divs, 6)

    total_notes = sum(note_types.values()) or 1
    half_frac = note_types.get('half', 0) / total_notes
    fname_lower = fname.lower()
    is_gigue = 'gigue' in fname_lower
    is_courante = 'courante' in fname_lower or 'corrente' in fname_lower

    if abs(qn - 1.5) < 0.01:
        beats, bt = 3, 8
    elif abs(qn - 2.0) < 0.01:
        beats, bt = 2, 4
    elif abs(qn - 3.0) < 0.01:
        beats, bt = 3, 4
    elif abs(qn - 4.0) < 0.01:
        beats, bt = 4, 4
    elif abs(qn - 4.5) < 0.01:
        beats, bt = 9, 8
    elif abs(qn - 6.0) < 0.01:
        # Courantes are always 3/2; Gigues in compound meter → 12/8;
        # other movements (Sarabande, Double) → 3/2 if half notes substantial
        if is_courante or (not is_gigue and half_frac > 0.08):
            beats, bt = 3, 2
        else:
            beats, bt = 12, 8
    else:
        return None

    t = ET.Element('time')
    b_el = ET.SubElement(t, 'beats')
    b_el.text = str(beats)
    bt_el = ET.SubElement(t, 'beat-type')
    bt_el.text = str(bt)
    return t


def _extract_movement(xml_str: str, start_mnum: str, end_mnum: str,
                      fname: str = '') -> str:
    """Extract measures [start_mnum..end_mnum] from score-partwise XML.
    Carries forward last-seen key/time/clef/divisions into the first extracted
    measure so verovio has all attributes it needs.
    Time signature is inferred from note content (not blindly inherited) to
    correct for source files that never emit time-sig changes between movements."""
    import xml.etree.ElementTree as ET
    import copy
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return xml_str

    first_part = root.find('part')
    if first_part is None:
        return xml_str
    all_mnums = [m.get('number', '') for m in first_part.findall('measure')]
    try:
        start_idx = all_mnums.index(start_mnum)
    except ValueError:
        return xml_str
    try:
        end_idx = all_mnums.index(end_mnum)
    except ValueError:
        end_idx = len(all_mnums) - 1

    keep_set = set(all_mnums[start_idx: end_idx + 1])

    for part in root.findall('part'):
        measures = part.findall('measure')
        # Accumulate attribute elements seen before start_mnum
        acc_divs = acc_key = acc_time = acc_staves = None
        acc_clefs: dict = {}
        for msr in measures:
            if msr.get('number', '') == start_mnum:
                break
            attrs = msr.find('attributes')
            if attrs is None:
                continue
            for child in attrs:
                if child.tag == 'divisions':
                    acc_divs = copy.deepcopy(child)
                elif child.tag == 'key':
                    acc_key = copy.deepcopy(child)
                elif child.tag == 'time':
                    acc_time = copy.deepcopy(child)
                elif child.tag == 'staves':
                    acc_staves = copy.deepcopy(child)
                elif child.tag == 'clef':
                    acc_clefs[child.get('number', '1')] = copy.deepcopy(child)

        # Drop out-of-range measures
        for msr in list(measures):
            if msr.get('number', '') not in keep_set:
                part.remove(msr)

        if start_idx == 0:
            continue  # first movement — attributes already in place

        first_msr = part.find('measure')
        if first_msr is None:
            continue

        # Ensure <attributes> exists as first child
        existing = first_msr.find('attributes')
        if existing is None:
            existing = ET.Element('attributes')
            first_msr.insert(0, existing)

        # Build set of tags already present
        have: set = set()
        for child in existing:
            if child.tag == 'clef':
                have.add(f'clef_{child.get("number","1")}')
            else:
                have.add(child.tag)

        # Insert missing elements in MusicXML canonical order.
        # For time: infer from note content to catch wrong time sigs in source
        # (e.g. CapToMusic exports that write 4/4 for every movement header).
        # Only override when the inferred bar duration differs from declared —
        # same-duration equivalents (6/8↔3/4, 12/8↔3/2, 2/2↔4/4) are kept
        # as-is since the source's grouping choice is likely intentional.
        if acc_divs is not None:
            divs_val = int(acc_divs.text)
            kept = part.findall('measure')
            inferred_time = _infer_time_sig_from_content(kept, divs_val, fname)
            if inferred_time is not None:
                ib  = int(inferred_time.findtext('beats', '0'))
                ibt = int(inferred_time.findtext('beat-type', '1'))
                inferred_bar_q = ib * 4.0 / ibt
                existing_time = existing.find('time')
                if existing_time is not None:
                    eb  = int(existing_time.findtext('beats', '0'))
                    ebt = int(existing_time.findtext('beat-type', '1'))
                    declared_bar_q = eb * 4.0 / ebt
                    if abs(declared_bar_q - inferred_bar_q) > 0.01:
                        # Bar durations differ → source sig is wrong, replace
                        existing.remove(existing_time)
                        have.discard('time')
                        acc_time = inferred_time
                    # else: same bar duration (e.g. 6/8 vs 3/4) → keep source sig
                else:
                    acc_time = inferred_time

        insert_pos = 0
        for tag, elem in [('divisions', acc_divs), ('key', acc_key),
                           ('time', acc_time), ('staves', acc_staves)]:
            if tag not in have and elem is not None:
                existing.insert(insert_pos, elem)
                insert_pos += 1
        for n, elem in sorted(acc_clefs.items()):
            if f'clef_{n}' not in have:
                existing.append(elem)

    # Renumber measures from 1 in all parts
    first_part = root.find('part')
    if first_part is not None:
        orig_nums = [m.get('number', '') for m in first_part.findall('measure')]
        num_map = {orig: str(i + 1) for i, orig in enumerate(orig_nums)}
        for part in root.findall('part'):
            for i, msr in enumerate(part.findall('measure')):
                orig = msr.get('number', '')
                msr.set('number', num_map.get(orig, str(i + 1)))

    return ET.tostring(root, encoding='unicode')


def find_tobis_files():
    """Return [(rel, full), ...] for pre-split XML files under tobis-notenarchiv.de/split/."""
    split_base = os.path.join(os.path.dirname(__file__), 'tobis-notenarchiv.de', 'split')
    if not os.path.isdir(split_base):
        return []
    files = []
    for subdir in sorted(os.listdir(split_base)):
        subpath = os.path.join(split_base, subdir)
        if not os.path.isdir(subpath):
            continue
        def _mvt_key(fn):
            import re as _r
            m = _r.match(r'(BWV_\d+[a-z]?)_(\d+)', fn, _r.I)
            return (m.group(1).upper() if m else fn, int(m.group(2)) if m else 0)
        for fname in sorted(os.listdir(subpath), key=_mvt_key):
            if fname.lower().endswith('.xml'):
                full = os.path.join(subpath, fname)
                files.append((f'tobis/{subdir}/{fname}', full))
    return files


def _regen_tobis_splits(subdir='engl-suites'):
    """Regenerate pre-split XML files for one tobis source subdirectory.
    Reads from tobis-notenarchiv.de/<subdir>/*.xml, writes to
    tobis-notenarchiv.de/split/<subdir>/.
    Safe to re-run; overwrites existing split files."""
    import re as _re
    import unicodedata as _ud

    def _ascii(s):
        """Transliterate accented characters to ASCII (é→e, etc.)."""
        return ''.join(
            c for c in _ud.normalize('NFKD', s)
            if _ud.category(c) != 'Mn' and ord(c) < 128
        )

    base = os.path.join(os.path.dirname(__file__), 'tobis-notenarchiv.de')
    src_dir = os.path.join(base, subdir)
    out_dir = os.path.join(base, 'split', subdir)
    os.makedirs(out_dir, exist_ok=True)

    for src_fname in sorted(os.listdir(src_dir)):
        if not src_fname.lower().endswith(('.xml', '.musicxml')):
            continue
        src_path = os.path.join(src_dir, src_fname)
        with open(src_path, encoding='utf-8') as f:
            xml_str = f.read()

        movements = _tobis_movements(src_path)
        if not movements:
            print(f'  {src_fname}: no movement markers, skipping')
            continue

        # BWV number for output filename prefix
        bwv_m = _re.match(r'(BWV_\d+[a-z]?)\.(xml|musicxml)', src_fname, _re.I)
        bwv_prefix = bwv_m.group(1) if bwv_m else src_fname.rsplit('.', 1)[0]

        for i, (title, start_mnum, end_mnum) in enumerate(movements, 1):
            # Strip leading "N. " sequence number from title (e.g. "6. Gavotte I" → "Gavotte I")
            clean = _re.sub(r'^\d+\.\s*', '', title).strip()
            clean = _ascii(clean)                          # é→e, ö→o, etc.
            safe_title = _re.sub(r'[^\w\s-]', '', clean).strip()
            safe_title = _re.sub(r'\s+', '_', safe_title)
            out_fname = f'{bwv_prefix}_{i}_{safe_title}.xml'
            out_path = os.path.join(out_dir, out_fname)
            extracted = _extract_movement(xml_str, start_mnum, end_mnum,
                                          fname=out_fname)
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write(extracted)
            print(f'  {out_fname}')

    print(f'Done: {subdir}')


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

def _fix_missing_divisions(content: str) -> str:
    """Inject <divisions> into the first <attributes> block when absent.
    MusicXML requires divisions for unambiguous duration parsing; without it
    verovio misaligns voices in files that mix triplet eighths and quarters
    (e.g. BWV_0995_6_Gavotte_II_en_Rondeaux.xml).  Divisions are inferred
    from the duration of the first <type>quarter</type> note found."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return content
    changed = False
    for part in root.findall('.//part'):
        if part.find('.//attributes/divisions') is not None:
            continue  # already has divisions

        # Infer divisions from the first explicit quarter note duration
        divisions = None
        for note in part.iter('note'):
            type_el = note.find('type')
            dur_el  = note.find('duration')
            if type_el is not None and dur_el is not None:
                if (type_el.text or '').strip() == 'quarter':
                    try:
                        divisions = int(dur_el.text)
                        break
                    except (ValueError, TypeError):
                        pass
        if divisions is None:
            continue

        first_measure = part.find('measure')
        if first_measure is None:
            continue
        attrs = first_measure.find('attributes')
        if attrs is None:
            attrs = ET.Element('attributes')
            first_measure.insert(0, attrs)
        if attrs.find('divisions') is None:
            div_el = ET.Element('divisions')
            div_el.text = str(divisions)
            attrs.insert(0, div_el)
            changed = True

    if not changed:
        return content
    result = ET.tostring(root, encoding='unicode')
    if content.lstrip().startswith('<?xml'):
        decl = content[:content.index('?>') + 2]
        result = decl + '\n' + result
    return result


def _fix_missing_tuplet_markers(content: str) -> str:
    """Add missing <tuplet> notation markers to triplet groups.

    Some MusicXML files (e.g. from CapToMusic) only annotate tuplet start/stop
    in the first measure; subsequent measures have <time-modification> but no
    <tuplet type="start/stop"> markers.  Without these markers, verovio emits
    plain <note dur='8'> in the MEI (no <tuplet> wrapper) and spaces them as
    regular eighth notes — causing lower-voice quarter notes to appear
    compressed relative to the upper-voice triplet eighths.

    Algorithm: for each voice in each measure, collect runs of notes sharing
    the same <time-modification> (actual=3, normal=2) in groups of 3, then
    add start/stop markers where absent.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return content

    changed = False
    for part in root.findall('.//part'):
        for measure in part.findall('measure'):
            # Collect non-chord notes per voice in document order
            voices: dict = {}
            for child in measure:
                if child.tag != 'note':
                    continue
                if child.find('chord') is not None:
                    continue          # chord note shares onset with previous
                v_el = child.find('voice')
                v = v_el.text if v_el is not None else '1'
                voices.setdefault(v, []).append(child)

            for note_list in voices.values():
                i = 0
                while i < len(note_list):
                    note = note_list[i]
                    tm = note.find('time-modification')
                    if tm is None:
                        i += 1
                        continue
                    if tm.findtext('actual-notes') != '3' or tm.findtext('normal-notes') != '2':
                        i += 1
                        continue
                    # Gather exactly 3 consecutive triplet notes
                    group = []
                    j = i
                    while j < len(note_list) and len(group) < 3:
                        n = note_list[j]
                        ntm = n.find('time-modification')
                        if ntm is None or ntm.findtext('actual-notes') != '3':
                            break
                        group.append(n)
                        j += 1
                    if len(group) != 3:
                        i = j
                        continue
                    # Only mark uniform groups (all same <duration>) to avoid
                    # incorrectly splitting mixed-value triplet groups (e.g. BWV_0815)
                    durs = [n.findtext('duration') for n in group]
                    if len(set(durs)) != 1:
                        i = j
                        continue
                    first, last = group[0], group[-1]
                    # Check if start marker already present on first note
                    first_nots = first.find('notations')
                    has_start = first_nots is not None and any(
                        t.get('type') == 'start'
                        for t in first_nots.findall('tuplet')
                    )
                    if not has_start:
                        if first_nots is None:
                            first_nots = ET.SubElement(first, 'notations')
                        ts = ET.SubElement(first_nots, 'tuplet')
                        ts.set('number', '1')
                        ts.set('type', 'start')
                        last_nots = last.find('notations')
                        if last_nots is None:
                            last_nots = ET.SubElement(last, 'notations')
                        te = ET.SubElement(last_nots, 'tuplet')
                        te.set('number', '1')
                        te.set('type', 'stop')
                        changed = True
                    i = j  # advance past this group

    if not changed:
        return content
    result = ET.tostring(root, encoding='unicode')
    if content.lstrip().startswith('<?xml'):
        decl = content[:content.index('?>') + 2]
        result = decl + '\n' + result
    return result


def _strip_new_system_hints(content: str) -> str:
    """Remove new-system/new-page layout hints from <print> elements.

    Verovio's MusicXML tie-matching resets at <print new-system='yes'>
    boundaries, leaving cross-system ties unresolved ('ties left open').
    Removing the hints lets verovio compute its own layout, after which
    tie matching works correctly across system breaks.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return content
    changed = False
    for print_el in root.iter('print'):
        for attr in ('new-system', 'new-page'):
            if print_el.get(attr):
                del print_el.attrib[attr]
                changed = True
    if not changed:
        return content
    result = ET.tostring(root, encoding='unicode')
    if content.lstrip().startswith('<?xml'):
        decl = content[:content.index('?>') + 2]
        result = decl + '\n' + result
    return result


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

def _load_tsd_gen_file(fname: str) -> dict:
    path = os.path.join(os.path.dirname(__file__), fname)
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
            filename, metre, tsd_str = parts[0], parts[1], parts[2]
            num, den = metre.split('/')
            beat_dur_q = int(num) * 4.0 / int(den)
            labels = [c for c in tsd_str if c in 'TSD']
            if labels:
                data[filename.strip()] = (beat_dur_q, labels)
    return data

_TSD_GEN_4: dict = _load_tsd_gen_file('TSD_generated_4.txt')
_TSD_GEN_8: dict = _load_tsd_gen_file('TSD_generated_8.txt')

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
    _base_ppq = None
    for _n in tree.iter(tag_pfx + 'note'):
        _ppq = _n.get('dur.ppq')
        if _ppq and _n.get('dur') == '4' and not int(_n.get('dots', 0)):
            _base_ppq = int(_ppq)
            break

    def _elem_dur_q(el, scale):
        """Duration in quarters: prefer dur.ppq/base_ppq, fall back to dur+dots+scale."""
        ppq = el.get('dur.ppq')
        if ppq and _base_ppq:
            return int(ppq) / _base_ppq
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
                 beat_dur_q=1.0, pickup_dur_q=0.0):
    """
    all_seqs: [(voice_key, interval_seq), ...]
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
    # last_end advances only when an occurrence is actually kept — same as _search_motif.
    # If a voice's occurrence at P is cross-deduped, last_end is NOT advanced, so an
    # overlapping occurrence at P+1 in that voice can still be found.
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
                continue  # cross-voice dedup — don't advance last_end
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
            absorbed.add(inv_key)
            ln = len(body)
            all_voices = set(pat_voice_raw[key].keys()) | set(pat_voice_raw[inv_key].keys())
            all_cands = []
            for vi in all_voices:
                for start, nids, onset, dp0_first in pat_voice_raw[key].get(vi, []):
                    all_cands.append((round(onset * 16), start, vi, nids, dp0_first, False))
                for start, nids, onset, dp0_first in pat_voice_raw[inv_key].get(vi, []):
                    all_cands.append((round(onset * 16), start, vi, nids, dp0_first, True))
            # Sort: onset_q, then direct before inverted, then voice
            all_cands.sort(key=lambda x: (x[0], x[5], x[2]))
            last_end_v = {}
            seen_oq = set()
            merged = []
            for onset_q, start, vi, nids, dp0_first, is_inv in all_cands:
                if start < last_end_v.get(vi, -1):
                    continue
                if onset_q in seen_oq:
                    continue  # cross-dedup — don't advance last_end
                merged.append((nids, dp0_first, is_inv, onset_q))
                seen_oq.add(onset_q)
                last_end_v[vi] = start + ln + 1
            pat_occs[key] = merged

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
        return any(p[k:] + p[:k] == q for k in range(1, len(p)))

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


def _search_motif(query):
    """
    Parse query "dur[,dur...];phase;+iv-iv..." (phase optional, default 0).
    Rhythm-only mode: "dur[,dur...];phase" or "dur[,dur...]" — no intervals,
    N durations = N notes, any interval accepted.
    Durations may have operators: >1/16, <=1/8, etc. (default = exact match).
    N+1 durations accepted for N intervals; last one checks last note's duration.
    Returns {"occs": [[nid,...], ...], "count": N}, sorted by onset.
    """
    # strip optional explicit scale prefix: (dur) at very start, e.g. (1/8) or (3/4)
    explicit_scale_q = None
    m_scale = re.match(r'^\(([^)]+)\)(.*)', query)
    if m_scale:
        _, scale_val = _parse_dur(m_scale.group(1).strip())
        explicit_scale_q = scale_val
        query = m_scale.group(2)

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
        seqs              = list(_state.get("seqs", []))
        beat_dur_q        = _state.get("beat_dur_q", 1.0)
        pickup_dur_q      = _state.get("pickup_dur_q", 0.0)
        repeat_ranges     = list(_state.get("repeat_ranges", []))
        volta_search_info = _state.get("volta_search_info")

    # compute phase using the smallest note duration in the pattern as unit
    # rhythm_only: durs elements are (op, val) → s[1] = val
    # interval:    pattern elements are (interval, (op, val)) → s[1][1] = val
    if rhythm_only:
        all_dur_vals = [s[1] for s in durs] + ([last_dur[1]] if last_dur is not None else [])
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
            elif min_dur_q is not None:
                ph = _metric_phase(seq[i][4] - pickup_dur_q, min_dur_q, beat_dur_q)
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
            onset_q = round(seq[i][4] * 16)
            nids = [seq[i][2]] + [seq[i + k][3] for k in range(n)]
            _all_cands.append((onset_q, _curr_is_inv, _vi_idx, i, seq[i][4], nids))

    # Phase 2: sort (direct before inverted at same onset, then by voice), joint greedy.
    # Cross-dedup does NOT advance per-voice last_end — same semantics as _find_motifs.
    _all_cands.sort(key=lambda x: (x[0], x[1], x[2]))
    _last_end_v = {}
    seen_onsets = set()
    occs_with_onset = []
    is_inv_flags    = []
    for _oq, _inv, _vi, _i, _of, _ns in _all_cands:
        if _i < _last_end_v.get(_vi, -1):
            continue
        if _oq in seen_onsets:
            continue  # cross-onset dedup — don't advance last_end_v
        occs_with_onset.append((_of, _ns))
        is_inv_flags.append(_inv)
        seen_onsets.add(_oq)
        _last_end_v[_vi] = _i + n + 1

    def _strip_p2(nid):
        return nid[:-4] if nid.endswith('__p2') else nid

    # Apply repeat_pairs from unfolded seqs: seqs already contain play-2 copies
    repeat_pairs = []
    # Determine effective repeat parameters (volta or simple)
    _eff_rpt = None
    if volta_search_info:
        _eff_rpt = volta_search_info
    elif len(repeat_ranges) == 1:
        rr = repeat_ranges[0]
        _eff_rpt = {
            'rpt_start': rr[0], 'rpt_end': rr[1],
            'shift':     rr[1] - rr[0],
            'play2_end': rr[1] + (rr[1] - rr[0]),
        }

    if _eff_rpt:
        rpt_start_q = _eff_rpt['rpt_start']
        rpt_end_q   = _eff_rpt['rpt_end']
        shift_q     = _eff_rpt['shift']
        play2_end_q = _eff_rpt['play2_end']

        p1_idxs = [j for j, (o, _) in enumerate(occs_with_onset)
                   if rpt_start_q - 1e-9 <= o < rpt_end_q - 1e-9]
        p2_idxs = [j for j, (o, _) in enumerate(occs_with_onset)
                   if rpt_end_q - 1e-9 <= o < play2_end_q - 1e-9]
        p_set   = set(p1_idxs) | set(p2_idxs)
        nr_idxs = [j for j in range(len(occs_with_onset)) if j not in p_set]

        if p2_idxs:
            nr_before = [j for j in nr_idxs if occs_with_onset[j][0] < rpt_start_q - 1e-9]
            nr_after  = [j for j in nr_idxs if occs_with_onset[j][0] >= play2_end_q - 1e-9]
            p1_by_oq16 = {round(occs_with_onset[j][0] * 16): j for j in p1_idxs}
            pairs = []
            for j2 in p2_idxs:
                o2 = occs_with_onset[j2][0]
                j1 = p1_by_oq16.get(round((o2 - shift_q) * 16))
                if j1 is not None:
                    pairs.append((j1, j2))
            # B-section repeat: split nr_after into B_p1 / B_p2 and pair them
            b_has_repeat  = _eff_rpt.get('b_has_repeat', False)
            B_dur_q       = _eff_rpt.get('B_dur_q', 0.0)
            B_p1_end_q    = _eff_rpt.get('B_p1_end_q', float('inf'))
            if b_has_repeat and B_dur_q > 0:
                nr_B_p1 = [j for j in nr_after if occs_with_onset[j][0] < B_p1_end_q - 1e-9]
                nr_B_p2 = [j for j in nr_after if occs_with_onset[j][0] >= B_p1_end_q - 1e-9]
            else:
                nr_B_p1 = nr_after
                nr_B_p2 = []
            idx_order = nr_before + p1_idxs + p2_idxs + nr_B_p1 + nr_B_p2
            occs_with_onset = [occs_with_onset[j] for j in idx_order]
            is_inv_flags    = [is_inv_flags[j]    for j in idx_order]
            nb       = len(nr_before)
            p1_count = len(p1_idxs)
            p2_count = len(p2_idxs)
            p1_pos   = {j1: nb + k              for k, j1 in enumerate(p1_idxs)}
            p2_pos   = {j2: nb + p1_count + k   for k, j2 in enumerate(p2_idxs)}
            # skip_p2=True when p1 and p2 share any physical note (body repeat, or motif
            # spanning body/volta boundary).  False only when entirely different notes
            # (motif wholly within one volta ending vs the other).
            def _nids_overlap(pos1, pos2):
                s1 = set(_strip_p2(n) for n in occs_with_onset[pos1][1])
                s2 = set(_strip_p2(n) for n in occs_with_onset[pos2][1])
                return bool(s1 & s2)
            repeat_pairs = [(p1_pos[j1], p2_pos[j2],
                             _nids_overlap(p1_pos[j1], p2_pos[j2]))
                            for j1, j2 in pairs if j1 in p1_pos and j2 in p2_pos]
            # B pairs (B_p2 nids always match B_p1 after stripping → skip_p2=True)
            if nr_B_p2:
                _b_base = nb + p1_count + p2_count
                B_p1_by_oq = {round(occs_with_onset[_b_base + k][0] * 16): _b_base + k
                               for k in range(len(nr_B_p1))}
                for k2, j in enumerate(nr_B_p2):
                    o2 = occs_with_onset[_b_base + len(nr_B_p1) + k2][0]
                    k1_pos = B_p1_by_oq.get(round((o2 - B_dur_q) * 16))
                    if k1_pos is not None:
                        repeat_pairs.append((k1_pos, _b_base + len(nr_B_p1) + k2, True))
                # B-section volta pairing (volta_groups[1]):
                # pair B's 1st-ending occurrences with B's 2nd-ending occurrences
                # from _Bs (no __p2 nids); skip _Bp2 occurrences.
                b_volta_v1 = _eff_rpt.get('b_volta_v1')
                b_volta_v2 = _eff_rpt.get('b_volta_v2')
                if b_volta_v1 and b_volta_v2:
                    bv1_s, bv1_e = b_volta_v1
                    bv2_s, bv2_e = b_volta_v2
                    bv_offset_16 = round((bv2_s - bv1_s) * 16)
                    Bv1_by_oq16 = {}
                    for k in range(len(nr_B_p1)):
                        pos = _b_base + k
                        o = occs_with_onset[pos][0]
                        if bv1_s - 1e-9 <= o < bv1_e - 1e-9:
                            Bv1_by_oq16[round(o * 16)] = pos
                    for k2 in range(len(nr_B_p2)):
                        pos2 = _b_base + len(nr_B_p1) + k2
                        o2 = occs_with_onset[pos2][0]
                        if not (bv2_s - 1e-9 <= o2 < bv2_e - 1e-9):
                            continue
                        if any(nid.endswith('__p2') for nid in occs_with_onset[pos2][1]):
                            continue
                        pos1 = Bv1_by_oq16.get(round(o2 * 16) - bv_offset_16)
                        if pos1 is not None:
                            repeat_pairs.append((pos1, pos2, True))
            # Volta-difference check (mirrors analyze_motifs collapse logic):
            # If motif doesn't appear in any volta region → collapse play-2 copies.
            if volta_search_info and p2_idxs:
                _v1_s, _v1_e = _eff_rpt.get('volta1', (float('inf'), float('inf')))
                _v2_s, _v2_e = _eff_rpt.get('volta2', (float('inf'), float('inf')))
                _in_Av1 = any(_v1_s-1e-9 <= occs_with_onset[p1_pos[j1]][0] < _v1_e-1e-9
                              for j1 in p1_idxs if j1 in p1_pos)
                _in_Av2 = any(_v2_s-1e-9 <= occs_with_onset[p2_pos[j2]][0] < _v2_e-1e-9
                              for j2 in p2_idxs if j2 in p2_pos)
                _in_Bv1 = _in_Bv2 = False
                if nr_B_p2:
                    _b_v1 = _eff_rpt.get('b_volta_v1')
                    _b_v2 = _eff_rpt.get('b_volta_v2')
                    if _b_v1 and _b_v2:
                        _bv1s, _bv1e = _b_v1
                        _bv2s, _bv2e = _b_v2
                        _in_Bv1 = any(_bv1s-1e-9 <= occs_with_onset[_b_base+k][0] < _bv1e-1e-9
                                      for k in range(len(nr_B_p1)))
                        _in_Bv2 = any(_bv2s-1e-9 <= occs_with_onset[_b_base+len(nr_B_p1)+k2][0] < _bv2e-1e-9
                                      for k2 in range(len(nr_B_p2)))
                # Secondary volta check: also scan for the natural inverse of the
                # searched pattern in volta regions.  Mirrors analyze_motifs behaviour
                # where a merged motif doesn't collapse if EITHER form (direct or
                # inverted) is in a volta.
                if (not _in_Av1 or not _in_Av2) and not contour and pattern is not None:
                    _inv_ivs = [[-x for x in (iv if isinstance(iv, list) else [iv])]
                                for iv, _ in pattern]
                    def _inv_in_range(rng_s, rng_e):
                        for _vk2, sq2 in seqs:
                            for ii in range(len(sq2) - n + 1):
                                if not (rng_s - 1e-9 <= sq2[ii][4] < rng_e - 1e-9):
                                    continue
                                if not all(sq2[ii + k][6] for k in range(n)):
                                    continue
                                if min_dur_q is not None:
                                    ph2 = _metric_phase(sq2[ii][4] - pickup_dur_q,
                                                        min_dur_q, beat_dur_q)
                                    if ph2 != start_phase:
                                        continue
                                if all(sq2[ii + k][0] in _inv_ivs[k] and
                                       _dur_matches(sq2[ii + k][1], pattern[k][1])
                                       for k in range(n)):
                                    return True
                        return False
                    if not _in_Av1 and _v1_s < float('inf'):
                        _in_Av1 = _inv_in_range(_v1_s, _v1_e)
                    if not _in_Av2 and _v2_s < float('inf'):
                        _in_Av2 = _inv_in_range(_v2_s, _v2_e)
                if (not _in_Av1 and not _in_Av2) and (not _in_Bv1 and not _in_Bv2):
                    # Motif absent from all volta regions (body-only repeat).
                    # Body p2 notes are identical SVG elements → show once.
                    _keep = (list(range(nb)) +
                             list(range(nb, nb + p1_count)) +
                             list(range(nb + p1_count + p2_count,
                                        nb + p1_count + p2_count + len(nr_B_p1))))
                    occs_with_onset = [occs_with_onset[k] for k in _keep]
                    is_inv_flags    = [is_inv_flags[k]    for k in _keep]
                    repeat_pairs = []
                    p2_count = 0  # no play-2 slots remain to strip
            # strip __p2 suffix from nids in A play-2 slots
            stripped = []
            for k, (o, nids) in enumerate(occs_with_onset):
                if nb + p1_count <= k < nb + p1_count + p2_count:
                    stripped.append((o, [_strip_p2(nid) for nid in nids]))
                else:
                    stripped.append((o, nids))
            occs_with_onset = stripped

    # Strip __p2 from B_p2 nids (they're outside the A play-2 range, not stripped above)
    occs_with_onset = [(o, [_strip_p2(nid) for nid in nids]) for o, nids in occs_with_onset]
    occs = [nids for _, nids in occs_with_onset]
    return {"occs": occs, "count": len(occs), "repeat_pairs": repeat_pairs,
            "is_inv": is_inv_flags}


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

        # ── Unfold repeat/volta before motif detection ───────────────────────────
        # Insert play-2 copies so _find_motifs sees cross-boundary patterns.
        rpt_start = rpt_end = shift = 0.0
        play2_end = 0.0
        volta1_range_q = volta2_range_q = None  # (start, end) in unfolded time
        is_volta = False
        b_has_repeat = False   # True when B section also has a structural repeat
        B_dur_q      = 0.0    # duration of B section (quarters)
        B_p1_end_q   = 0.0   # end of B first pass in unfolded time
        b_has_volta  = False   # True when B section has its own 1st/2nd endings
        b_volta_v1_16s = b_volta_v1_16e = 0  # B volta1 onset range in 16ths (unfolded)
        b_volta_v2_16s = b_volta_v2_16e = 0  # B volta2 onset range in 16ths (unfolded)
        b_volta_offset_16 = 0                 # volta2_start − volta1_start in 16ths
        if volta_groups:
            # Volta unfolding: [I] + A + A1 + [I_p2] + A_p2 + A2(shifted) + B(shifted)
            # When B also repeats (suite dance ||:A:||||:B:||), B_p2 is appended so
            # _find_motifs can detect cross-repeat patterns and B is counted twice.
            # I = any section(s) before A that are inside the repeat bracket
            # (detected via repeat_ranges[0][0] which marks the true repeat start)
            vg = volta_groups[0]
            _body_s, _body_e = vg['body']
            _v1_s,   _v1_e   = vg['volta1']
            _v2_s,   _v2_e   = vg['volta2']
            _A_dur  = _body_e - _body_s
            _v2_dur = _v2_e - _v2_s
            # True repeat start — includes pickup/intro sections inside the bracket
            _I_start = repeat_ranges[0][0] if repeat_ranges else _body_s
            _I_dur   = _body_s - _I_start
            # All play-2 notes are shifted by full play-1 duration = v1_e - I_start
            _play2_shift = _v1_e - _I_start
            _A2_uf_start = _v1_e + _I_dur + _A_dur
            _A2_shift    = _A2_uf_start - _v2_s
            _B_uf_start  = _A2_uf_start + _v2_dur
            _B_shift     = _B_uf_start - _v2_e
            # B section repeat (||:A:||||:B:|| structure): repeat_ranges has ≥2 entries
            _b_repeat = len(repeat_ranges) >= 2
            _B_dur    = (repeat_ranges[-1][1] - repeat_ranges[-1][0]) if _b_repeat else 0.0
            # Pre-detect B volta structure so per-voice loop can split body/v1/v2 correctly.
            # Without this, _Bs contains B_v2 notes and _Bp2 contains B_v1 notes — both wrong.
            _bv1_s_orig = _bv1_e_orig = _bv2_s_orig = _bv2_e_orig = None
            _Bb_p2_shift = _Bv2_shift = 0.0
            if len(volta_groups) >= 2:
                _vg1 = volta_groups[1]
                _bv1_s_orig, _bv1_e_orig = _vg1['volta1']
                _bv2_s_orig, _bv2_e_orig = _vg1['volta2']
                # B play-2 body starts after B play-1 ends (_B_uf_start + B_dur)
                _Bb_p2_shift = _B_shift + (_bv1_e_orig - _v2_e)
                # B_v2 placed at same relative offset from B_body as B_v1 in play-1
                _Bv2_shift   = _Bb_p2_shift + _bv1_s_orig - _bv2_s_orig
            unfolded = {}
            for vk, notes in voices.items():
                _pre = [n for n in notes if n[5] < _I_start]
                _I  = [n for n in notes if _I_start <= n[5] < _body_s]
                _A  = [n for n in notes if _body_s  <= n[5] < _body_e]
                _A1 = [n for n in notes if _v1_s    <= n[5] < _v1_e]
                _A2 = [n for n in notes if _v2_s    <= n[5] < _v2_e]
                _B  = [n for n in notes if n[5] >= _v2_e]
                _Ip2 = [(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_play2_shift) for n in _I]
                _Ap2 = [(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_play2_shift) for n in _A]
                _A2s = [(n[0], n[1], n[2], n[3], n[4], n[5]+_A2_shift)            for n in _A2]
                if _bv1_s_orig is not None:
                    # B has its own volta: play-1 = body+v1, play-2 = body+v2
                    _Bb  = [n for n in notes if _v2_e        <= n[5] < _bv1_s_orig]
                    _Bv1 = [n for n in notes if _bv1_s_orig  <= n[5] < _bv1_e_orig]
                    _Bv2 = [n for n in notes if _bv2_s_orig  <= n[5] < _bv2_e_orig]
                    _Bs  = ([(n[0], n[1], n[2], n[3], n[4], n[5]+_B_shift)        for n in _Bb] +
                            [(n[0], n[1], n[2], n[3], n[4], n[5]+_B_shift)        for n in _Bv1])
                    _Bp2 = ([(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_Bb_p2_shift) for n in _Bb] +
                            [(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_Bv2_shift)   for n in _Bv2])
                else:
                    _Bs  = [(n[0], n[1], n[2], n[3], n[4], n[5]+_B_shift)             for n in _B]
                    _Bp2 = ([(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_B_shift+_B_dur)
                              for n in _B] if _b_repeat and _B_dur > 0 else [])
                unfolded[vk] = _pre + _I + _A + _A1 + _Ip2 + _Ap2 + _A2s + _Bs + _Bp2
            seq_voices = unfolded
            # Repeat parameters for per-motif counting (in unfolded time)
            rpt_start    = _I_start
            rpt_end      = _v1_e                       # end of play-1 (I + A + A1)
            shift        = _play2_shift                # uniform shift for all play-2 notes
            play2_end    = _A2_uf_start + _v2_dur      # end of play-2 block = start of B
            volta1_range_q = (_v1_s, _v1_e)
            volta2_range_q = (_A2_uf_start, _A2_uf_start + _v2_dur)
            is_volta     = True
            b_has_repeat = _b_repeat
            B_dur_q      = _B_dur
            B_p1_end_q   = play2_end + _B_dur          # end of B first pass
            # Detect B-section's own 1st/2nd endings (volta_groups[1])
            if len(volta_groups) >= 2:
                _vg1 = volta_groups[1]
                _Bp2_start   = _B_uf_start + _B_dur   # start of B play-2 in unfolded time
                _bv1_uf_s    = _B_uf_start + (_vg1['volta1'][0] - _v2_e)
                _bv1_uf_e    = _Bp2_start              # B play-1 ends where play-2 begins
                _bv2_uf_s    = _Bp2_start + (_vg1['volta1'][0] - _v2_e)
                _bv2_uf_e    = _bv2_uf_s + (_vg1['volta2'][1] - _vg1['volta2'][0])
                b_has_volta  = True
                b_volta_v1_16s = round(_bv1_uf_s * 16)
                b_volta_v1_16e = round(_bv1_uf_e * 16)
                b_volta_v2_16s = round(_bv2_uf_s * 16)
                b_volta_v2_16e = round(_bv2_uf_e * 16)
                b_volta_offset_16 = round((_bv2_uf_s - _bv1_uf_s) * 16)
        elif len(repeat_ranges) == 1:
            rpt_start, rpt_end = repeat_ranges[0]
            shift = rpt_end - rpt_start
            play2_end = rpt_end + shift
            unfolded = {}
            for vk, notes in voices.items():
                pre  = [n for n in notes if n[5] < rpt_start]
                rep  = [n for n in notes if rpt_start <= n[5] < rpt_end]
                post = [n for n in notes if n[5] >= rpt_end]
                # play-2: same pitches/durations but unique nids (suffix __p2) so
                # _deoverlap doesn't discard them as duplicates of play-1
                rep_p2  = [(n[0] + '__p2', n[1], n[2], n[3], n[4], n[5] + shift) for n in rep]
                post_sh = [(n[0], n[1], n[2], n[3], n[4], n[5] + shift) for n in post]
                unfolded[vk] = pre + rep + rep_p2 + post_sh
            seq_voices = unfolded
        else:
            seq_voices = voices

        all_seqs = [(vk, _interval_seq(notes, beat_dur_q, pickup_dur_q))
                    for vk, notes in seq_voices.items()
                    if len(notes) >= 4]
        motifs = _find_motifs(all_seqs, beat_dur_q=beat_dur_q, pickup_dur_q=pickup_dur_q)
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
            if shift > 0:
                rpt_start_16  = rpt_start * 16
                rpt_end_16    = rpt_end   * 16
                shift_16      = shift * 16
                play2_end_16  = play2_end * 16
                p1_idxs  = [j for j, t in enumerate(transforms)
                            if rpt_start_16 <= t['onset_q'] < rpt_end_16]
                p2_idxs  = [j for j, t in enumerate(transforms)
                            if rpt_end_16 <= t['onset_q'] < play2_end_16]
                p_set    = set(p1_idxs) | set(p2_idxs)
                nr_idxs  = [j for j in range(len(transforms)) if j not in p_set]
                if p2_idxs:
                    # Pair each p2 occurrence with its p1 counterpart via uniform shift
                    p1_by_oq = {transforms[j]['onset_q']: j for j in p1_idxs}
                    pairs = []
                    for j2 in p2_idxs:
                        j1 = p1_by_oq.get(transforms[j2]['onset_q'] - shift_16)
                        if j1 is not None:
                            pairs.append((j1, j2))
                    nr_before = [j for j in nr_idxs if transforms[j]['onset_q'] < rpt_start_16]
                    nr_after  = [j for j in nr_idxs if transforms[j]['onset_q'] >= play2_end_16]
                    idx_order = nr_before + p1_idxs + p2_idxs + nr_after
                    # strip __p2 suffix from play-2 nids so they point to real SVG elements
                    occs_out = [[_strip_p2(nid) for nid in m['occurrences'][j]]
                                for j in idx_order]
                    transforms_out = [transforms[j] for j in idx_order]
                    nb = len(nr_before)
                    p1_pos = {j1: nb + k                 for k, j1 in enumerate(p1_idxs)}
                    p2_pos = {j2: nb + len(p1_idxs) + k  for k, j2 in enumerate(p2_idxs)}
                    # skip_p2=True when p1 and p2 share any physical note (same or overlapping
                    # position — e.g. body repeat, or motif spanning body/volta boundary).
                    # False only when they share NO notes (entirely different volta endings).
                    def _nids_overlap(pos1, pos2):
                        return bool(set(occs_out[pos1]) & set(occs_out[pos2]))
                    repeat_pairs = [(p1_pos[j1], p2_pos[j2],
                                     _nids_overlap(p1_pos[j1], p2_pos[j2]))
                                    for j1, j2 in pairs
                                    if j1 in p1_pos and j2 in p2_pos]
                    n_occ = len(occs_out)
                    if is_volta:
                        # Split nr_after into B first-pass and B second-pass (when B repeats)
                        B_p1_end_16 = B_p1_end_q * 16
                        B_dur_16    = B_dur_q * 16
                        if b_has_repeat and B_dur_q > 0:
                            nr_B_p1 = [j for j in nr_after
                                       if transforms[j]['onset_q'] < B_p1_end_16]
                            nr_B_p2 = [j for j in nr_after
                                       if transforms[j]['onset_q'] >= B_p1_end_16]
                        else:
                            nr_B_p1 = nr_after
                            nr_B_p2 = []
                        # Check if motif appears in either volta region
                        v1_16_s = volta1_range_q[0] * 16
                        v1_16_e = volta1_range_q[1] * 16
                        v2_16_s = volta2_range_q[0] * 16
                        v2_16_e = volta2_range_q[1] * 16
                        p1_in_v1 = any(v1_16_s <= transforms[j]['onset_q'] < v1_16_e
                                       for j in p1_idxs)
                        p2_in_v2 = any(v2_16_s <= transforms[j]['onset_q'] < v2_16_e
                                       for j in p2_idxs)
                        if not p1_in_v1 and not p2_in_v2:
                            # Motif absent from both volta regions (body-only repeat).
                            # Body p2 notes are identical SVG elements → collapse.
                            idx_order = nr_before + p1_idxs + nr_B_p1
                            occs_out = [[_strip_p2(nid) for nid in m['occurrences'][j]]
                                        for j in idx_order]
                            transforms_out = [transforms[j] for j in idx_order]
                            repeat_pairs = []
                            n_occ = len(occs_out)
                        elif nr_B_p2:
                            # Volta diff + B repeats: pair B occurrences the same way A is paired
                            B_p1_by_oq = {transforms[j]['onset_q']: j for j in nr_B_p1}
                            B_pairs_raw = []
                            for j2 in nr_B_p2:
                                j1 = B_p1_by_oq.get(transforms[j2]['onset_q'] - B_dur_16)
                                if j1 is not None:
                                    B_pairs_raw.append((j1, j2))
                            # Map j → position in occs_out
                            # idx_order = nr_before + p1_idxs + p2_idxs + nr_B_p1 + nr_B_p2
                            _nr_all_map = {j: len(nr_before) + len(p1_idxs) + len(p2_idxs) + k
                                           for k, j in enumerate(nr_after)}
                            B_rep_pairs = [(_nr_all_map[j1], _nr_all_map[j2], True)
                                           for j1, j2 in B_pairs_raw
                                           if j1 in _nr_all_map and j2 in _nr_all_map]
                            repeat_pairs = repeat_pairs + B_rep_pairs
                            # B-section volta pairing (volta_groups[1]):
                            # pair B's 1st-ending occurrences (in nr_B_p1, from _Bs)
                            # with B's 2nd-ending occurrences (in nr_B_p2, from _Bs).
                            # Skip _Bp2 occurrences (they have __p2 nids).
                            if b_has_volta:
                                Bv1_by_oq = {
                                    transforms[j]['onset_q']: j
                                    for j in nr_B_p1
                                    if b_volta_v1_16s <= transforms[j]['onset_q'] < b_volta_v1_16e
                                }
                                for j2 in nr_B_p2:
                                    oq2 = transforms[j2]['onset_q']
                                    if not (b_volta_v2_16s <= oq2 < b_volta_v2_16e):
                                        continue
                                    if any(nid.endswith('__p2') for nid in m['occurrences'][j2]):
                                        continue
                                    j1 = Bv1_by_oq.get(oq2 - b_volta_offset_16)
                                    if j1 is not None and j1 in _nr_all_map and j2 in _nr_all_map:
                                        repeat_pairs.append((_nr_all_map[j1], _nr_all_map[j2], True))
                        if n_occ < 2:
                            continue
                    else:
                        # Simple repeat: structural filter
                        paired_p2 = {j2 for _, j2 in pairs}
                        unpaired_p2 = [j for j in p2_idxs if j not in paired_p2]
                        structural = len(p1_idxs) + len(nr_idxs) + len(unpaired_p2)
                        if structural < 2:
                            continue
            # Recompute three-way counts from the final filtered transforms_out.
            # The original _nd/_ni/_nb come from _find_motifs on the full unfolded
            # sequence; if the volta-collapse path removed play-2 entries the values
            # are stale.  Recount so the dict always displays the correct totals.
            if (_ni > 0 or _nb > 0) and transforms_out is not transforms:
                _pos_inv = {}
                for _t in transforms_out:
                    _oq  = _t['onset_q']
                    _inv = _t.get('inversion', False)
                    if _oq not in _pos_inv:
                        _pos_inv[_oq] = set()
                    _pos_inv[_oq].add(_inv)
                _nd = sum(1 for _f in _pos_inv.values() if _f == {False})
                _ni = sum(1 for _f in _pos_inv.values() if _f == {True})
                _nb = sum(1 for _f in _pos_inv.values() if len(_f) == 2)
            # Both-parts-repeat halving: when A (volta) and B both repeat, every
            # occurrence is duplicated → display count / 2 to reflect one hearing.
            # Applied independently per sub-count so an even inv sub-count is
            # halved even when the total (and/or direct sub-count) is odd.
            _nd_halved = is_volta and b_has_repeat and _nd % 2 == 0 and _nd // 2 >= 2
            _ni_halved = is_volta and b_has_repeat and _ni % 2 == 0 and _ni // 2 >= 2
            _nb_halved = is_volta and b_has_repeat and _nb % 2 == 0 and _nb // 2 >= 2
            _both_rpt  = is_volta and b_has_repeat and n_occ % 2 == 0 and n_occ // 2 >= 2
            _dc        = n_occ // 2 if _both_rpt else n_occ
            if _dc < 2:
                continue   # halved to single occurrence → not a meaningful motif
            result.append({
                'color':             _MOTIF_COLORS[i % len(_MOTIF_COLORS)],
                'occs':              occs_out,
                'count':             n_occ,
                'display_count':     _dc,
                'both_parts_repeat': _both_rpt,
                'nd_halved':         _nd_halved,
                'ni_halved':         _ni_halved,
                'nb_halved':         _nb_halved,
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
                'mdl':               _mdl_score(n_occ, L_pat, transforms_out),
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

    # Beat duration in quarter notes (from time signature).
    # Compound meters (mc%3==0 and mu>=8, e.g. 6/8, 6/16, 9/8): beat = dotted note = 3 subdivisions.
    # Simple meters: beat = one note of the denominator value, capped at one quarter note.
    beat_dur = 1.0
    for line in lines:
        for tok in line.strip().split('\t'):
            m = re.match(r'^\*M(\d+)/(\d+)$', tok)
            if m:
                mc, mu = int(m.group(1)), int(m.group(2))
                sub = 4.0 / mu          # one subdivision in quarter notes
                if mc % 3 == 0 and mu >= 8:
                    beat_dur = sub * 3  # compound: dotted note per beat
                else:
                    beat_dur = min(sub, 1.0)  # simple: cap at quarter note
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

        # Scan interpretation lines (before first data line) for *clef tokens
        has_clef = False
        file_clefs = {}  # kern column index → clef string
        for j in range(header_idx + 1, len(lines)):
            raw = lines[j].rstrip("\n\r")
            if not raw or raw.startswith("!"):
                continue
            if not raw.startswith("*") and not raw.startswith("="):
                break  # reached note data
            tokens = raw.split("\t")
            if any(t.startswith("*clef") for t in tokens):
                has_clef = True
                for ci, t in enumerate(tokens):
                    if t.startswith("*clef") and ci in kern_idxs:
                        file_clefs[ci] = t
                break

        if file_clefs:
            # Order staves by clef: G-clef spines (treble) → lower staff numbers (top);
            # F/C-clef spines (bass/alto) → higher staff numbers (bottom).
            # Within each group, rightmost column = lowest staff number (standard score order).
            treble_cols = sorted([c for c in kern_idxs if 'G' in file_clefs.get(c, '')],
                                 reverse=True)
            bass_cols   = sorted([c for c in kern_idxs if 'G' not in file_clefs.get(c, '')],
                                 reverse=True)
            ordered = treble_cols + bass_cols
            for staff_n, col in enumerate(ordered, 1):
                staff_row[col] = f"*staff{staff_n}"
        else:
            # No clef tokens in file — fall back: last kern column = bass (staff2), rest treble (staff1)
            for rank, col in enumerate(kern_idxs):
                staff_row[col] = "*staff1" if rank < n_kern - 1 else "*staff2"
                clef_row[col]  = "*clefG2" if rank < n_kern - 1 else "*clefF4"

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

    # If the 2-spine structure created by the first *^ collapses back to 1 spine
    # later (a line where every token is *v), the grand-staff conversion would
    # cause empty bars beyond that point. Skip conversion for such files — verovio
    # will render them as a single-staff voice-split piece.
    for i in range(first_split + 1, len(lines)):
        raw = lines[i].rstrip("\n\r")
        if not raw or raw.startswith("!"):
            continue
        tokens = raw.split("\t")
        if all(t == "*v" for t in tokens):
            return content  # full merge-back: 2-spine structure is temporary

    # Detect original clef (before first *^) to preserve instrument register
    orig_clef = None
    for i in range(header_idx + 1, first_split):
        raw = lines[i].rstrip("\n\r")
        if raw.startswith("*clef"):
            orig_clef = raw.split("\t")[0]
            break

    # ── build 2-spine grand-staff file ───────────────────────────────────────
    result = []

    # New header: 2 **kern spines + staff + clef
    # For F-clef instruments (cello, bass): both spines in bass clef;
    # right subspine (after *^) = higher voice → staff1 (top).
    # For G-clef or no clef (piano/WTC preludes): treble + bass as before.
    if orig_clef and 'F' in orig_clef:
        result.append("**kern\t**kern\n")
        result.append("*staff2\t*staff1\n")
        result.append(f"{orig_clef}\t{orig_clef}\n")
    else:
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
    _basename_pre = os.path.basename(path)
    _has_tsd = _basename_pre in _TSD_DATA or _basename_pre in _TSD_GEN_4 or _basename_pre in _TSD_GEN_8
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
        elif ext in ('xml', 'musicxml', 'mxl'):
            content = _fix_missing_divisions(content)
            content = _fix_missing_tuplet_markers(content)
            content = _strip_new_system_hints(content)
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

    # parse voices — separate try so _voices_s survives later errors
    try:
        _voices_s, _beat_dur_q_s, _pickup_dur_q_s, _rr_s, _vg_s = _voice_notes_from_mei(mei_str)
        if _beat_override is not None:
            _beat_dur_q_s = _beat_override
    except Exception:
        _voices_s = {}
        _beat_dur_q_s = 1.0
        _pickup_dur_q_s = 0.0
        _rr_s = []
        _vg_s = []

    # compute interval sequences for the /search endpoint + build note label map
    # _volta_search_info: repeat parameters for volta-aware pairing in _search_motif
    _volta_search_info = None
    try:
        # unfold repeat/volta so /search finds cross-boundary patterns
        if _vg_s:
            # Volta unfolding (same logic as analyze_motifs)
            _vg = _vg_s[0]
            _bs, _be = _vg['body'];  _v1s, _v1e = _vg['volta1'];  _v2s, _v2e = _vg['volta2']
            _A_dur = _be - _bs;  _v2_dur = _v2e - _v2s
            _I_start = _rr_s[0][0] if _rr_s else _bs
            _I_dur   = _bs - _I_start
            _play2_sh = _v1e - _I_start
            _A2_uf   = _v1e + _I_dur + _A_dur
            _A2_sh   = _A2_uf - _v2s
            _B_uf    = _A2_uf + _v2_dur
            _B_sh    = _B_uf - _v2e
            _b_rpt = len(_rr_s) >= 2
            _B_dur = (_rr_s[-1][1] - _rr_s[-1][0]) if _b_rpt else 0.0
            # Pre-detect B volta structure (same logic as analyze_motifs)
            _bv1s_o = _bv1e_o = _bv2s_o = _bv2e_o = None
            _Bb_p2_sh = _Bv2_sh = 0.0
            if len(_vg_s) >= 2:
                _vg1s = _vg_s[1]
                _bv1s_o, _bv1e_o = _vg1s['volta1']
                _bv2s_o, _bv2e_o = _vg1s['volta2']
                _Bb_p2_sh = _B_sh + (_bv1e_o - _v2e)
                _Bv2_sh   = _Bb_p2_sh + _bv1s_o - _bv2s_o
            _uf = {}
            for vk, notes in _voices_s.items():
                _I  = [n for n in notes if _I_start <= n[5] < _bs]
                _A  = [n for n in notes if _bs  <= n[5] < _be]
                _A1 = [n for n in notes if _v1s <= n[5] < _v1e]
                _A2 = [n for n in notes if _v2s <= n[5] < _v2e]
                _B  = [n for n in notes if n[5] >= _v2e]
                _Ip2 = [(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_play2_sh) for n in _I]
                _Ap2 = [(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_play2_sh) for n in _A]
                _A2s = [(n[0], n[1], n[2], n[3], n[4], n[5]+_A2_sh) for n in _A2]
                if _bv1s_o is not None:
                    _Bb  = [n for n in notes if _v2e       <= n[5] < _bv1s_o]
                    _Bv1 = [n for n in notes if _bv1s_o    <= n[5] < _bv1e_o]
                    _Bv2 = [n for n in notes if _bv2s_o    <= n[5] < _bv2e_o]
                    _Bs  = ([(n[0], n[1], n[2], n[3], n[4], n[5]+_B_sh) for n in _Bb] +
                            [(n[0], n[1], n[2], n[3], n[4], n[5]+_B_sh) for n in _Bv1])
                    _Bp2 = ([(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_Bb_p2_sh) for n in _Bb] +
                            [(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_Bv2_sh)   for n in _Bv2])
                else:
                    _Bs  = [(n[0], n[1], n[2], n[3], n[4], n[5]+_B_sh)  for n in _B]
                    _Bp2 = ([(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_B_sh+_B_dur)
                              for n in _B] if _b_rpt and _B_dur > 0 else [])
                _uf[vk] = _I + _A + _A1 + _Ip2 + _Ap2 + _A2s + _Bs + _Bp2
            all_seqs = [(vk, _interval_seq(notes, _beat_dur_q_s, _pickup_dur_q_s))
                        for vk, notes in _uf.items() if len(notes) >= 4]
            _play2_end = _A2_uf + _v2_dur
            _volta_search_info = {
                'rpt_start':   _I_start, 'rpt_end': _v1e,
                'shift':       _play2_sh,
                'play2_end':   _play2_end,
                'volta1':      (_v1s, _v1e),
                'volta2':      (_A2_uf, _A2_uf + _v2_dur),
                'b_has_repeat': _b_rpt,
                'B_dur_q':     _B_dur,
                'B_p1_end_q':  _play2_end + _B_dur,
            }
            # B-section's own 1st/2nd endings (volta_groups[1])
            if len(_vg_s) >= 2:
                _vg1s = _vg_s[1]
                _Bp2_st = _B_uf + _B_dur
                _volta_search_info['b_volta_v1'] = (
                    _B_uf + (_vg1s['volta1'][0] - _v2e), _Bp2_st)
                _volta_search_info['b_volta_v2'] = (
                    _Bp2_st + (_vg1s['volta1'][0] - _v2e),
                    _Bp2_st + (_vg1s['volta1'][0] - _v2e) + (_vg1s['volta2'][1] - _vg1s['volta2'][0]))
        elif len(_rr_s) == 1:
            _rpt_s, _rpt_e = _rr_s[0]
            _sh = _rpt_e - _rpt_s
            _uf = {}
            for vk, notes in _voices_s.items():
                _pre   = [n for n in notes if n[5] < _rpt_s]
                _rep   = [n for n in notes if _rpt_s <= n[5] < _rpt_e]
                _post  = [n for n in notes if n[5] >= _rpt_e]
                _rep2  = [(n[0]+'__p2', n[1], n[2], n[3], n[4], n[5]+_sh) for n in _rep]
                _post2 = [(n[0], n[1], n[2], n[3], n[4], n[5]+_sh) for n in _post]
                _uf[vk] = _pre + _rep + _rep2 + _post2
            all_seqs = [(vk, _interval_seq(notes, _beat_dur_q_s, _pickup_dur_q_s))
                        for vk, notes in _uf.items() if len(notes) >= 4]
        else:
            all_seqs = [(vk, _interval_seq(notes, _beat_dur_q_s, _pickup_dur_q_s))
                        for vk, notes in _voices_s.items() if len(notes) >= 4]
        _ACC_SFX = {0: '', 1: '#', -1: 'b', 2: '##', -2: 'bb'}
        nid_labels = {}
        for _notes in _voices_s.values():
            for nid, pname, oct_int, _dur, midi_val, _onset in _notes:
                base = _PITCH_CLASS.get(pname.lower(), 0) + (oct_int + 1) * 12
                acc = _ACC_SFX.get(midi_val - base, '')
                nid_labels[nid] = pname.upper() + acc
        nid_to_note = {n[0]: n for _ns in _voices_s.values() for n in _ns}
        beam_of = _beam_groups_from_mei(mei_str)
    except Exception:
        all_seqs = []
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

    def _eff_count(m):
        return m.get('display_count', m['count'])
    motifs.sort(key=lambda m: (_is_smooth(_eff_count(m)) and _eff_count(m) >= 8, _eff_count(m)), reverse=True)

    reload_js = _RELOAD_JS.format(version=version)

    # ── build motif table rows (auto-detected motifs) ─────────────────────────
    def _row(i, m):
        pfx = m['phase_pfx']
        phase_html = (f'<sub style="letter-spacing:-1px;color:#aaa">{pfx}</sub>'
                      if pfx else '')
        halved    = m.get('both_parts_repeat', False)
        nd_halved = m.get('nd_halved', halved)
        ni_halved = m.get('ni_halved', halved)
        nb_halved = m.get('nb_halved', halved)
        any_halved = nd_halved or ni_halved or nb_halved or halved
        cnt    = m.get('display_count', m['count'])
        n_dir  = m.get('n_direct_only', m['count'])
        n_inv  = m.get('n_inv_only', 0)
        n_both = m.get('n_both', 0)
        n_dir  = n_dir  // 2 if nd_halved else n_dir
        n_inv  = n_inv  // 2 if ni_halved else n_inv
        n_both = n_both // 2 if nb_halved else n_both
        def _bold(n):
            return f'<b>{n}</b>' if _is_smooth(n) and n >= 8 else str(n)
        _sup = '<sup style="color:#aaa;font-size:9px;margin-left:1px">÷2</sup>'
        half_sup = _sup if halved else ''
        if n_inv > 0 or n_both > 0:
            n_dir_total = n_dir + n_both
            n_inv_total = n_inv + n_both
            cnt_html = (
                f'<span style="font-size:11px">'
                f'<span class="cnt-f" data-fi="{i}" data-ff="direct" '
                f'style="cursor:pointer;color:#555" title="только прямые">'
                f'&times;{_bold(n_dir_total)}{_sup if nd_halved else ""}</span>'
                f'&nbsp;<span class="cnt-f" data-fi="{i}" data-ff="inv" '
                f'style="cursor:pointer;color:#888" title="только инверсии">'
                f'&#x21C5;{_bold(n_inv_total)}{_sup if ni_halved else ""}</span>'
                f'&nbsp;<span class="cnt-f" data-fi="{i}" data-ff="all" '
                f'style="cursor:pointer;color:#888" title="все">'
                f'&#x2295;{_bold(cnt)}</span>'
                f'</span>'
            )
        else:
            cnt_html = _bold(cnt) + half_sup
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
            f'<tr data-midx="{i}" data-count="{cnt}" data-mdl="{mdl}" data-length="{m["length"]}" '
            f'style="border-bottom:1px solid #e8e8e8;cursor:pointer" '
            f'onmouseover="this.style.background=\'#f0f0f0\'" '
            f'onmouseout="if(this.getAttribute(\'data-active\')!==\'1\')this.style.background=\'\'">'
            f'<td style="padding:5px 10px 5px 0;white-space:nowrap">'
            f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
            f'background:{m["color"]};margin-right:5px;vertical-align:middle"></span>'
            f'<b>M{i+1}</b>{phase_html}</td>'
            f'<td style="padding:3px 16px 3px 0">'
            f'<div style="display:flex;align-items:center;gap:8px">'
            # f'<span style="font-family:monospace;font-size:11px;white-space:nowrap">'
            # f'{" &nbsp; ".join(m["pattern"])}</span>'
            f'{staff_svg}</div></td>'
            f'<td style="padding:5px 10px 5px 0;text-align:center">&times;{cnt_html}</td>'
            f'<td style="padding:5px 8px 5px 0;text-align:center;color:#888">{m["length"]}</td>'
            f'<td style="padding:5px 0;text-align:right;font-size:11px;color:#557">{mdl_html}</td>'
            f'</tr>'
        )

    auto_rows = "".join(_row(i, m) for i, m in enumerate(motifs))
    motif_data = [{"color": m["color"],
                   "transforms": m.get("transforms", []),
                   "queryStr": m.get("queryStr", ""),
                   "profile": m.get("profile", []),
                   "mdl": m.get("mdl", 0)}
                  for m in motifs]
    motif_json = json.dumps(motif_data)
    note_labels_json = json.dumps(nid_labels)

    # ── TSD harmony labels ────────────────────────────────────────────────────
    _basename = _basename_pre
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
        # only accumulate offset for files that have implicit pickup measures
        _allow_tsd_offset = (ext in ('xml', 'musicxml', 'mxl')
                             and 'number="-1"' in content)
        # If label window > pickup duration, TSD labels start from bar 1 (skip pickup)
        _offset_tsd = (_pickup_dur_q_s
                       if _pickup_dur_q_s > 0 and _bar_dur_q_tsd > _pickup_dur_q_s
                       else 0.0)
        for _i in range(len(_tsd_labels_out)):
            _t0 = _i * _bar_dur_q_tsd + _offset_tsd
            _t1 = _t0 + _bar_dur_q_tsd
            # First choice: any note starting in [t0, t1)
            _anchor = next(
                (nid for onset_q, nid in _flat if _t0 <= onset_q < _t1), None
            )
            # Fallback: prefer nearest note at or after t0 (don't cross barlines backward)
            if _anchor is None:
                _ahead = sorted((onset_q, nid) for onset_q, nid in _flat if onset_q >= _t0)
                if _ahead:
                    _found_onset, _anchor = _ahead[0]
                    # gap >= one window → extra barline; shift all subsequent windows forward
                    _gap = _found_onset - _t0
                    if _allow_tsd_offset and _gap >= _bar_dur_q_tsd:
                        _offset_tsd += round(_gap / _bar_dur_q_tsd) * _bar_dur_q_tsd
                else:
                    _behind = sorted((onset_q, nid) for onset_q, nid in _flat if onset_q < _t0)
                    if _behind:
                        _anchor = _behind[-1][1]
            _tsd_nids_out.append(_anchor)
    tsd_json      = json.dumps(_tsd_labels_out)
    tsd_nids_json = json.dumps(_tsd_nids_out)

    # ── TSD generated labels ──────────────────────────────────────────────────
    def _build_gen_overlay(gen_dict):
        labels_out, nids_out = [], []
        if _basename not in gen_dict:
            return labels_out, nids_out
        _bar_dur_gen, _lbl = gen_dict[_basename]
        _flat_gen = sorted(
            (onset_q, nid)
            for note_list in _voices_s.values()
            for nid, _p, _o, _d, _m, onset_q in note_list
        )
        _allow_gen_offset = (ext in ('xml', 'musicxml', 'mxl')
                             and 'number="-1"' in content)
        # If label window > pickup duration, generated TSD also starts from bar 1
        _offset_gen = (_pickup_dur_q_s
                       if _pickup_dur_q_s > 0 and _bar_dur_gen > _pickup_dur_q_s
                       else 0.0)
        for _i in range(len(_lbl)):
            _t0 = _i * _bar_dur_gen + _offset_gen
            _anchor = next(
                (nid for onset_q, nid in _flat_gen if _t0 <= onset_q < _t0 + _bar_dur_gen), None
            )
            if _anchor is None:
                _ahead = sorted((onset_q, nid) for onset_q, nid in _flat_gen if onset_q >= _t0)
                if _ahead:
                    _found_onset_g, _anchor = _ahead[0]
                    _gap_g = _found_onset_g - _t0
                    if _allow_gen_offset and _gap_g >= _bar_dur_gen:
                        _offset_gen += round(_gap_g / _bar_dur_gen) * _bar_dur_gen
                else:
                    _behind = sorted((onset_q, nid) for onset_q, nid in _flat_gen if onset_q < _t0)
                    if _behind:
                        _anchor = _behind[-1][1]
            nids_out.append(_anchor)
        return _lbl, nids_out

    _tsd_gen4_labels, _tsd_gen4_nids = _build_gen_overlay(_TSD_GEN_4)
    _tsd_gen8_labels, _tsd_gen8_nids = _build_gen_overlay(_TSD_GEN_8)
    tsd_gen4_json      = json.dumps(_tsd_gen4_labels)
    tsd_gen4_nids_json = json.dumps(_tsd_gen4_nids)
    tsd_gen8_json      = json.dumps(_tsd_gen8_labels)
    tsd_gen8_nids_json = json.dumps(_tsd_gen8_nids)

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
        + (f'<button id="tsd-gen4-btn" onclick="window.toggleTSDGen4()" '
           f'style="font:12px sans-serif;padding:4px 10px;border:1px solid #bbb;'
           f'border-radius:4px;background:#f5f5f5;cursor:pointer">TSD~4</button>'
           if _tsd_gen4_labels else '')
        + (f'<button id="tsd-gen8-btn" onclick="window.toggleTSDGen8()" '
           f'style="font:12px sans-serif;padding:4px 10px;border:1px solid #bbb;'
           f'border-radius:4px;background:#f5f5f5;cursor:pointer">TSD~8</button>'
           if _tsd_gen8_labels else '')
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
  // repeat_pairs: [[play1_idx, play2_idx, skip_p2], ...]
  // skip_p2=true  → same physical notes (simple repeat): show "N(M)" at play1, skip play2 box
  // skip_p2=false → different physical notes (e.g. volta endings): draw both with own numbers
  var extraNum={{}};   // play1_idx -> play2_num (1-based)
  var skipDraw={{}};   // play2_idx -> true
  if(m.repeat_pairs){{
    m.repeat_pairs.forEach(function(pair){{
      var skip=pair.length<3||pair[2];
      if(skip){{extraNum[pair[0]]=pair[1]+1; skipDraw[pair[1]]=true;}}
    }});
  }}
  m.occs.forEach(function(occ,occIdx){{
    if(skipDraw[occIdx])return;
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
        // Search from end: add to the most-recent group for this sys,
        // unless there's a backward x-jump (cross-boundary motif) — then start a new sub-group.
        var found=false;
        for(var gi=svgSysGroups[si].length-1;gi>=0;gi--){{
          if(svgSysGroups[si][gi].sys===sys){{
            var grp=svgSysGroups[si][gi];
            var lastR=grp.rects[grp.rects.length-1];
            if(cr.right < lastR.left - 10)break; // backward jump → fall through to new group
            grp.rects.push(cr); found=true; break;
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
          txt.textContent=extraNum[occIdx]!==undefined
            ? String(occIdx+1)+'('+extraNum[occIdx]+')'
            : String(occIdx+1);
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

var _motifCache={{}};
function fetchMotifOccs(queryStr,cb){{
  if(_motifCache[queryStr]){{cb(_motifCache[queryStr]);return;}}
  fetch('/search',{{method:'POST',headers:{{'Content-Type':'text/plain'}},body:queryStr}})
  .then(function(r){{return r.json();}})
  .then(function(d){{_motifCache[queryStr]=d;cb(d);}})
  .catch(function(){{cb(null);}});
}}
function colorMotifOccs(occs,color){{
  occs.forEach(function(occ){{
    occ.forEach(function(id){{
      var el=document.getElementById(id);
      if(el)try{{el.setAttribute('fill',color);}}catch(e){{}}
    }});
  }});
}}
function filteredByInv(data,filter){{
  // Returns {{occs, repeat_pairs}} with indices remapped to the filtered subset.
  if(filter==='all'||!data.is_inv)return{{occs:data.occs,repeat_pairs:data.repeat_pairs||[]}};
  var wantInv=(filter==='inv');
  var oldToNew={{}};
  var occs=[];
  data.occs.forEach(function(occ,i){{
    if(data.is_inv[i]===wantInv){{oldToNew[i]=occs.length;occs.push(occ);}}
  }});
  var rp=(data.repeat_pairs||[]).filter(function(p){{return p[0] in oldToNew&&p[1] in oldToNew;}})
    .map(function(p){{return[oldToNew[p[0]],oldToNew[p[1]],p[2]];}});
  return{{occs:occs,repeat_pairs:rp}};
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
  // Legacy: called by addCustomMotif with an object that has .occs and .color
  colorMotifOccs(m.occs,m.color);
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
        _highlightFilter(idx,filter);
        if(st2){{
          var badge2='';
          if(filter==='direct')badge2='<span style="background:#1a7f37;color:#fff;border-radius:3px;padding:1px 5px;font-size:10px">\u00d7direct</span> ';
          else if(filter==='inv')badge2='<span style="background:#c05a00;color:#fff;border-radius:3px;padding:1px 5px;font-size:10px">\u21c5inv</span> ';
          st2.innerHTML=badge2+'<b>M'+(idx+1)+'</b>';
        }}
        fetchMotifOccs(motifs[idx].queryStr,function(data){{
          if(activeKey!==key||activeFilter!==filter)return;
          if(!data||!data.occs)return;
          colorMotifOccs(data.occs,motifs[idx].color);
          var fr=filteredByInv(data,filter);
          drawBoxes({{occs:fr.occs,color:motifs[idx].color,repeat_pairs:fr.repeat_pairs}});
          scrollToFirst({{occs:fr.occs}});
        }});
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
        if(st){{st.innerHTML='<b>M'+(idx+1)+'</b>';}}
        var qs=motifs[idx].queryStr;
        if(qs){{
          var inp=document.getElementById('motif-search-input');
          if(inp){{inp.value=qs;}}
        }}
        fetchMotifOccs(qs,function(data){{
          if(activeKey!==key)return;
          if(!data||!data.occs)return;
          colorMotifOccs(data.occs,motifs[idx].color);
          drawBoxes({{occs:data.occs,color:motifs[idx].color,repeat_pairs:data.repeat_pairs}});
          scrollToFirst({{occs:data.occs}});
        }});
        /* DISABLED: transposition profile detail row
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
        */
      }}
    }});
  }});
}}

function addCustomMotif(occs,queryStr,repeat_pairs,displayCount){{
  var cidx=customMotifs.length;
  var color=CUSTOM_COLORS[cidx%CUSTOM_COLORS.length];
  repeat_pairs=repeat_pairs||[];
  var cnt=occs.length;
  customMotifs.push({{color:color,occs:occs,repeat_pairs:repeat_pairs}});
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
    '<td style="padding:5px 10px 5px 0;text-align:center">\xd7'+(isSmooth(cnt)&&cnt>=8?'<b>'+cnt+'</b>':String(cnt))+'</td>'+
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
  drawBoxes({{color:color,occs:occs,repeat_pairs:repeat_pairs}});
  scrollToFirst({{occs:occs}});
}}

function _invertQueryStr(q){{
  // Invert the intervals part of a query string "[(<scale>)]dur;phase;ivs" → same with -ivs
  // Preserve optional (scale) prefix.
  var scalePfx='';
  var sm=q.match(/^\\([^)]+\\)/);
  if(sm){{scalePfx=sm[0];q=q.slice(sm[0].length);}}
  var parts=q.split(';');
  if(parts.length<3)return null;
  var ivPart=parts[2];
  // Check it's an interval/contour pattern (not empty)
  if(!ivPart)return null;
  var invIv=ivPart.replace(/([+\\-])(\\d*)/g,function(m,sign,num){{
    return(sign==='+' ? '-' : '+')+num;
  }});
  if(invIv===ivPart)return null; // nothing changed (no + or -)
  return scalePfx+parts[0]+';'+parts[1]+';'+invIv;
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
    // Strip ;inv from dict queryStr before comparing — it may differ from user input
    var mqBase=mq.replace(/;inv\\s*$/,'').trim();
    if(base===mqBase){{
      // Direct match: user typed the motif's own query (with or without ;inv suffix)
      var filter=hasInv?'inv':'direct';
      return{{idx:i,filter:filter,variant:filter}};
    }}
    if(invBase&&invBase===mqBase){{
      // User typed the inverted form of this motif's query
      var filter2=hasInv?'direct':'inv';
      return{{idx:i,filter:filter2,variant:filter2}};
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
  _highlightFilter(idx,filter);
  fetchMotifOccs(motifs[idx].queryStr,function(data){{
    if(!data||!data.occs)return;
    colorMotifOccs(data.occs,motifs[idx].color);
    var fr2=filteredByInv(data,filter);
    drawBoxes({{occs:fr2.occs,color:motifs[idx].color,repeat_pairs:fr2.repeat_pairs}});
    scrollToFirst({{occs:fr2.occs}});
  }});
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
    addCustomMotif(data.occs,query,data.repeat_pairs,data.count);
  }})
  .catch(function(e){{st.style.color='#c0392b';st.textContent=String(e);}});
}};

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',highlight);
else highlight();

// ── TSD harmony labels ──────────────────────────────────────────────────────
var tsdLabels={tsd_json};
var tsdNids={tsd_nids_json};
var tsdGen4Labels={tsd_gen4_json};
var tsdGen4Nids={tsd_gen4_nids_json};
var tsdGen8Labels={tsd_gen8_json};
var tsdGen8Nids={tsd_gen8_nids_json};
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
    var _stf=sys?sys.querySelector('g.staff'):null;
    var _stfH=_stf?_stf.getBBox().height:0;
    var fs=_stfH?_stfH*0.24:(sysBB?sysBB.height*0.12:noteBB.height*4.5);
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

// ── TSD generated overlays — HTML div approach (no SVG coord conversion) ─────
// Labels are <div> inside #score-pages (position:relative).
// Positions use getBoundingClientRect() in pixels — no viewBox math.
function _buildTsdGenOverlay(labels,nids,rowPx){{
  var container=document.getElementById('score-pages');
  if(!container)return[];
  var elems=[];
  var _CHAR_W=9; // approx px per char in bold 13px sans-serif
  var _PAD=3;    // extra gap after each label
  var _runs=[];var _ri=0;
  while(_ri<labels.length){{
    var _rj=_ri+1;
    while(_rj<labels.length&&labels[_rj]===labels[_ri])_rj++;
    _runs.push({{lbl:labels[_ri],cnt:_rj-_ri,idx:_ri}});
    _ri=_rj;
  }}
  // track last placed x per y-row (keyed by Math.round(y))
  var _lastX={{}};
  for(var _ti=0;_ti<_runs.length;_ti++){{
    var nid=nids[_runs[_ti].idx];
    var lbl=_runs[_ti].lbl;
    var txt=(_runs[_ti].cnt>1?lbl+_runs[_ti].cnt:lbl);
    if(!nid||!lbl)continue;
    var el=document.getElementById(nid);if(!el)continue;
    var svg=el,sys=el;
    while(svg&&svg.tagName.toLowerCase()!=='svg')svg=svg.parentNode;
    if(!svg)continue;
    while(sys&&sys!==svg){{if(sys.getAttribute&&sys.getAttribute('class')==='system')break;sys=sys.parentNode;}}
    if(!sys||sys===svg)sys=null;
    var cBCR=container.getBoundingClientRect();
    var eBCR=el.getBoundingClientRect();
    var refBCR=(sys||svg).getBoundingClientRect();
    var x=eBCR.left-cBCR.left+container.scrollLeft;
    var y=refBCR.bottom-cBCR.top+container.scrollTop+rowPx;
    var yKey=Math.round(y);
    if(_lastX[yKey]!==undefined&&x<_lastX[yKey])x=_lastX[yKey];
    _lastX[yKey]=x+txt.length*_CHAR_W+_PAD;
    var d=document.createElement('div');
    d.textContent=txt;
    d.style.cssText='position:absolute;font:bold 13px sans-serif;opacity:0.65;'
      +'pointer-events:none;display:none;white-space:nowrap;'
      +'color:'+(TSD_COLOR[lbl]||'#333')+';'
      +'left:'+x+'px;top:'+y+'px';
    container.appendChild(d);
    elems.push(d);
  }}
  return elems;
}}

var _tsdGen4Elems=[];var _tsdGen4Visible=false;
var _tsdGen8Elems=[];var _tsdGen8Visible=false;

window.toggleTSDGen4=function(){{
  if(!_tsdGen4Elems.length)_tsdGen4Elems=_buildTsdGenOverlay(tsdGen4Labels,tsdGen4Nids,4);
  _tsdGen4Visible=!_tsdGen4Visible;
  for(var _i=0;_i<_tsdGen4Elems.length;_i++)_tsdGen4Elems[_i].style.display=_tsdGen4Visible?'block':'none';
  var btn=document.getElementById('tsd-gen4-btn');
  if(btn){{btn.style.background=_tsdGen4Visible?'#e8f4fd':'#f5f5f5';btn.style.borderColor=_tsdGen4Visible?'#5ba3d0':'#bbb';btn.style.fontWeight=_tsdGen4Visible?'bold':'normal';}}
  if(_tsdGen4Visible){{var sp=document.getElementById('score-pages');if(sp)sp.scrollIntoView({{behavior:'smooth'}});}}
}};

window.toggleTSDGen8=function(){{
  if(!_tsdGen8Elems.length)_tsdGen8Elems=_buildTsdGenOverlay(tsdGen8Labels,tsdGen8Nids,22);
  _tsdGen8Visible=!_tsdGen8Visible;
  for(var _i=0;_i<_tsdGen8Elems.length;_i++)_tsdGen8Elems[_i].style.display=_tsdGen8Visible?'block':'none';
  var btn=document.getElementById('tsd-gen8-btn');
  if(btn){{btn.style.background=_tsdGen8Visible?'#e8f4fd':'#f5f5f5';btn.style.borderColor=_tsdGen8Visible?'#5ba3d0':'#bbb';btn.style.fontWeight=_tsdGen8Visible?'bold':'normal';}}
  if(_tsdGen8Visible){{var sp=document.getElementById('score-pages');if(sp)sp.scrollIntoView({{behavior:'smooth'}});}}
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
<div id="score-pages" style="position:relative">{pages}</div>
</body>
</html>"""
    return html, n_pages, version, all_seqs, _beat_dur_q_s, _pickup_dur_q_s, _rr_s, _volta_search_info

# ── background render + update ────────────────────────────────────────────────

def _render_worker(path: str, version: str, queue):
    """Runs in a subprocess to isolate verovio segfaults from the main process."""
    try:
        html, n_pages, ver, seqs, beat_dur_q, pickup_dur_q, repeat_ranges, volta_info = render_score(path, version)
        queue.put(('ok', html, n_pages, ver, seqs, beat_dur_q, pickup_dur_q, repeat_ranges, volta_info))
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

    _, html, n_pages, ver, seqs, beat_dur_q, pickup_dur_q, repeat_ranges, volta_info = result
    with _state_lock:
        _state["html"]              = html
        _state["version"]           = ver
        _state["seqs"]              = seqs
        _state["beat_dur_q"]        = beat_dur_q
        _state["pickup_dur_q"]      = pickup_dur_q
        _state["repeat_ranges"]     = repeat_ranges
        _state["volta_search_info"] = volta_info
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

        self._files        = find_generated_files() + find_lilypond_files() + find_tobis_files() + find_kern_files(KERN_DIR) + find_music21_files()
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
        self._tree.bind("<Key>", self._on_tree_key)

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
            cycle = _cycle_from_rel(rel, composer)
            key = (composer, cycle)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((rel, full))

        def _group_sort_key(key):
            import re as _re
            composer, cycle = key
            if composer == 'Bach':
                mc = _re.match(r'Cantata BWV (\d+)$', cycle or '')
                if mc:
                    return (0, _BACH_CYCLE_IDX.get('Cantatas', 99), int(mc.group(1)), '')
                return (0, _BACH_CYCLE_IDX.get(cycle or '', 99), 0, cycle or '')
            return (1, 0, 0, composer or '', cycle or '')

        import re as _re2
        sorted_order = sorted(order, key=_group_sort_key)
        total = 0
        use_headers = len(sorted_order) > 1 or (
            sorted_order and sorted_order[0][1] is not None)
        i = 0
        while i < len(sorted_order):
            composer, cycle = sorted_order[i]
            # Non-Bach composer with cycles: 3-level nesting (Composer → Cycle → files)
            if use_headers and composer != 'Bach' and cycle is not None:
                comp_keys = []
                while i < len(sorted_order) and sorted_order[i][0] == composer and sorted_order[i][1] is not None:
                    comp_keys.append(sorted_order[i])
                    i += 1
                comp_total = sum(len(groups[k]) for k in comp_keys)
                comp_node = self._tree.insert('', tk.END,
                                              text=f'{composer}  ({comp_total})',
                                              values=(), tags=('group',))
                self._tree.item(comp_node, open=False)
                for k in comp_keys:
                    _, cy = k
                    gfiles = groups[k]
                    child = self._tree.insert(comp_node, tk.END,
                                              text=f'{cy}  ({len(gfiles)})',
                                              values=(), tags=('group',))
                    self._tree.item(child, open=False)
                    for rel, full in gfiles:
                        self._tree.insert(child, tk.END,
                                          text=os.path.basename(rel), values=(full,))
                    total += len(gfiles)
                continue
            # Cantatas: 3-level nesting (Cantatas → Cantata BWV N → files)
            if use_headers and _re2.match(r'Cantata BWV \d+$', cycle or ''):
                cant_keys = []
                while i < len(sorted_order) and _re2.match(
                        r'Cantata BWV \d+$', sorted_order[i][1] or ''):
                    cant_keys.append(sorted_order[i])
                    i += 1
                cant_total = sum(len(groups[k]) for k in cant_keys)
                cant_node = self._tree.insert('', tk.END,
                                              text=f'Cantatas  ({cant_total})',
                                              values=(), tags=('group',))
                self._tree.item(cant_node, open=False)
                for k in cant_keys:
                    _, cy = k
                    gfiles = groups[k]
                    child = self._tree.insert(cant_node, tk.END,
                                              text=f'{cy}  ({len(gfiles)})',
                                              values=(), tags=('group',))
                    self._tree.item(child, open=False)
                    for rel, full in gfiles:
                        self._tree.insert(child, tk.END,
                                          text=os.path.basename(rel), values=(full,))
                    total += len(gfiles)
                continue
            # Normal 2-level
            group_files = groups[(composer, cycle)]
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
            i += 1
        self._count_var.set(f"{total} file{'s' if total != 1 else ''}")

    def _all_groups(self):
        """Return all group header item IDs in tree order."""
        result = []
        def _walk(parent=''):
            for iid in self._tree.get_children(parent):
                if 'group' in self._tree.item(iid, 'tags'):
                    result.append(iid)
                    _walk(iid)
        _walk()
        return result

    def _on_tree_key(self, event):
        ch = event.char
        if not ch or not ch.isprintable() or len(ch) != 1:
            return
        ch = ch.lower()
        groups = self._all_groups()
        matching = [iid for iid in groups
                    if self._tree.item(iid, 'text').lower().startswith(ch)]
        if not matching:
            return 'break'
        sel = self._tree.selection()
        cur = sel[0] if sel else None
        if cur in matching:
            target = matching[(matching.index(cur) + 1) % len(matching)]
        else:
            target = matching[0]
        parent = self._tree.parent(target)
        while parent:
            self._tree.item(parent, open=True)
            parent = self._tree.parent(parent)
        self._tree.selection_set(target)
        self._tree.focus(target)
        self._tree.see(target)
        return 'break'

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

    # Kill any existing instance on the same port before binding
    try:
        import urllib.request
        urllib.request.urlopen(
            f"http://127.0.0.1:{SERVER_PORT}/shutdown", timeout=2)
        time.sleep(0.8)  # wait for old process to exit
    except Exception:
        pass  # no old instance running — that's fine

    # start HTTP server
    threading.Thread(target=start_server, daemon=True).start()

    # Create browser window first (needs screen size from tkinter)
    _app = FileBrowser()
    _sw  = _app.winfo_screenwidth()
    _sh  = _app.winfo_screenheight()
    _bw  = _sw - 480   # browser fills the left part

    _url = f"http://127.0.0.1:{SERVER_PORT}/"
    _browser_proc = None
    for _exe in [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]:
        if os.path.exists(_exe):
            import subprocess
            _browser_proc = subprocess.Popen([_exe, "--new-window",
                              "--window-position=0,0",
                              f"--window-size={_bw},{_sh}", _url])
            break
    if _browser_proc is None:
        webbrowser.open(_url)

    def _on_close():
        if _browser_proc is not None:
            try:
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(_browser_proc.pid)],
                               capture_output=True)
            except Exception:
                pass
        _app.destroy()

    _app.protocol("WM_DELETE_WINDOW", _on_close)
    _app.mainloop()

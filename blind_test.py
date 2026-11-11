#!/usr/bin/env python3
"""
Blind relevance test built on the kern_reader core (reader/app.py).

  python blind_test.py --session sessions/session_1.json --rater anna      # run a test
  python blind_test.py --session sessions/session_1.json --preview 0 --out preview.html
  python blind_test.py --session sessions/session_1.json --check           # validate items vs rendering

Own port (8766); never kills browsers or other kern_reader instances.
"""
import sys, os, multiprocessing

multiprocessing.freeze_support()

_here = os.path.dirname(os.path.abspath(__file__))
_reader_dir = os.path.join(_here, 'reader')
if _reader_dir not in sys.path:
    sys.path.insert(0, _reader_dir)

# Load the core under the name '_core' at import time: the spawned render subprocess re-imports
# this file as __mp_main__ and needs sys.modules['_core'] for unpickling (same trick as kern_reader.py).
import importlib.util
_spec = importlib.util.spec_from_file_location('_core', os.path.join(_reader_dir, 'app.py'))
_core = importlib.util.module_from_spec(_spec)
sys.modules['_core'] = _core
_spec.loader.exec_module(_core)

import json
import re

BLIND_PORT = 8766
_OVERLAY_JS = os.path.join(_here, 'blind_overlay.js')


# ── page post-processing ──────────────────────────────────────────────────────

def make_blind_html(html: str, piece_idx: int, n_pieces: int, items: list) -> str:
    """Turn a normal render_score() page into a blind-test page."""
    html = re.sub(r'<div class="fn">.*?</div>', '', html, count=1, flags=re.S)   # hide file name
    cfg = {'pieceIdx': piece_idx, 'nPieces': n_pieces,
           'items': [{'id': it['id'], 'query': it['query'], 'variant': it['variant'],
                      'label': it['variant_label']} for it in items]}
    with open(_OVERLAY_JS, encoding='utf-8') as f:
        js = f.read()
    inject = ('<script>window.BLIND=' + json.dumps(cfg).replace('</', '<\\/') + ';</script>'
              '<script>' + js + '</script>')
    return html.replace('</body>', inject + '</body>', 1)


# ── file lookup ───────────────────────────────────────────────────────────────

def resolve_paths(rels):
    """rel path (as in blind_cache.json) -> full path."""
    want = set(rels)
    out = {}
    for finder in (lambda: _core.find_kern_files(_core.KERN_DIR), _core.find_music21_files,
                   _core.find_lilypond_files, _core.find_tobis_files):
        try:
            for r, f in finder():
                if r in want:
                    out[r] = f
        except Exception:
            pass
        if len(out) == len(want):
            break
    return out


def load_session(path):
    with open(path, encoding='utf-8') as f:
        sess = json.load(f)
    for pi, p in enumerate(sess['pieces']):
        for k, it in enumerate(p['items']):
            it['id'] = f'p{pi}_i{k}'
    return sess


# ── render in a subprocess (isolates verovio crashes) ─────────────────────────

def _blind_render_worker(path, piece_idx, n_pieces, items, queue):
    try:
        html = _core.render_score(path, '1', 0)[0]
        queue.put(('ok', make_blind_html(html, piece_idx, n_pieces, items)))
    except Exception as e:
        queue.put(('error', str(e)))


def render_piece(path, piece_idx, n_pieces, items, timeout=90):
    ctx = multiprocessing.get_context('spawn')
    q = ctx.Queue()
    proc = ctx.Process(target=_blind_render_worker, args=(path, piece_idx, n_pieces, items, q), daemon=True)
    proc.start()
    try:
        res = q.get(timeout=timeout)          # read BEFORE join (pipe-buffer deadlock)
    except Exception:
        proc.terminate(); proc.join(3)
        return None, 'render timed out or crashed'
    proc.join(5)
    return (res[1], None) if res[0] == 'ok' else (None, res[1])


# ── test runner (server + session state) ──────────────────────────────────────

import datetime
import threading
import time

_PAGE_CSS = ("body{font:16px sans-serif;max-width:760px;margin:60px auto;padding:0 24px;color:#222}"
             "button{font:bold 15px sans-serif;padding:10px 26px;border:1px solid #1a5fb4;border-radius:5px;"
             "background:#1a5fb4;color:#fff;cursor:pointer}")


def _simple_page(ver, body):
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>' + _PAGE_CSS + '</style><script>'
            '(function(){var cur="' + ver + '";var es=new EventSource("/events");'
            'es.onmessage=function(e){if(e.data!==cur){es.close();window.location.replace("/?t="+Date.now());}};})();'
            '</script></head><body>' + body + '</body></html>')


class BlindRun:
    def __init__(self, sess, session_path, rater):
        self.sess, self.rater = sess, rater
        self.n = len(sess['pieces'])
        os.makedirs(os.path.join(_here, 'responses'), exist_ok=True)
        safe = re.sub(r'[^A-Za-z0-9_-]', '_', rater)
        tag = sess.get('tag', '')
        self.resp_path = os.path.join(_here, 'responses',
                                      f"{safe}_{tag + '_' if tag else ''}{sess['seed']}.json")
        if os.path.isfile(self.resp_path):
            with open(self.resp_path, encoding='utf-8') as f:
                self.resp = json.load(f)
        else:
            self.resp = {'session_seed': sess['seed'], 'tag': sess.get('tag', ''), 'session_file': os.path.basename(session_path),
                         'rater': rater, 'started': datetime.datetime.now().isoformat(timespec='seconds'),
                         'pieces': []}
        done = {r['piece_idx'] for r in self.resp['pieces']}
        self.idx = next((i for i in range(self.n) if i not in done), self.n)
        self.paths = resolve_paths([p['piece'] for p in sess['pieces']])
        self.cache, self.errors = {}, {}
        self.lock = threading.Lock()
        self.ver = int(time.time())
        self.current_piece = None          # piece index currently displayed (None = intro/loading/finish)

    # -- page switching ------------------------------------------------------
    def _set(self, html_fn):
        with _core._state_lock:
            self.ver += 1
            ver = str(self.ver)
            _core._state['html'] = html_fn(ver)
            _core._state['version'] = ver
        _core._notify_sse(ver)

    def show_intro(self):
        done = len(self.resp['pieces'])
        resume = f'<p><i>Resuming: {done} of {self.n} pieces already done.</i></p>' if done else ''
        self.current_piece = None
        btn = ("<p><button onclick=\"fetch('/blind/begin',{method:'POST'}).then(function(){"
               "document.body.innerHTML='Loading…';})\">Start</button></p>")
        self._set(lambda v: _simple_page(v,
            '<h2>Motif relevance test</h2>'
            f'<p>You will see {self.n} short pieces, one after another. For each piece a list of motifs is shown. '
            'Rate every motif from <b>0</b> (not relevant for this piece) to <b>4</b> (surely relevant). '
            'Click a motif to see its first and last occurrence in the score. '
            'Please do not count the occurrences. Any number of the listed motifs may be relevant, '
            'from none to all.</p>' + resume + btn))

    def show_loading(self):
        self.current_piece = None
        self._set(lambda v: _simple_page(v, '<p style="color:#888;margin-top:120px">Loading next piece…</p>'))

    def show_finish(self):
        self.current_piece = None
        self._set(lambda v: _simple_page(v, '<h2>Thank you!</h2><p>All pieces are rated. You can close this window.</p>'))

    # -- rendering with prefetch --------------------------------------------
    def _ensure_render(self, i):
        with self.lock:
            if i in self.cache or i in self.errors or i >= self.n:
                return
        piece = self.sess['pieces'][i]
        path = self.paths.get(piece['piece'])
        if not path:
            html, err = None, 'file not found'
        else:
            html, err = render_piece(path, i, self.n, piece['items'])
        with self.lock:
            if html:
                self.cache[i] = html
            else:
                self.errors[i] = err

    def prefetch(self, i):
        threading.Thread(target=self._ensure_render, args=(i,), daemon=True).start()

    def show_piece(self, i):
        """Blocking: render (if needed), display, start prefetching the next piece."""
        while i < self.n:
            self._ensure_render(i)
            with self.lock:
                html, err = self.cache.get(i), self.errors.get(i)
            if html:
                self.idx = i
                with _core._state_lock:
                    self.ver += 1
                    ver = str(self.ver)
                    # the page's SSE listener reloads whenever the announced version != the one embedded in
                    # the page -> stamp the version we are about to announce into the page
                    _core._state['html'] = re.sub(r'var _cur="[^"]*";', 'var _cur="%s";' % ver, html, count=1)
                    _core._state['version'] = ver
                    self.current_piece = i
                _core._notify_sse(ver)
                self.prefetch(i + 1)
                return
            # unrenderable piece: log it and move on
            print(f"[blind] piece {i} skipped: {err}", flush=True)
            self.resp['pieces'].append({'piece_idx': i, 'piece': self.sess['pieces'][i]['piece'],
                                        'render_error': err, 'items': []})
            self._save()
            i += 1
        self.idx = self.n
        self.show_finish()

    # -- responses -----------------------------------------------------------
    def _save(self):
        tmp = self.resp_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.resp, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.resp_path)

    def submit(self, payload):
        """Called from the HTTP thread; returns quickly, advances in a background thread."""
        with self.lock:
            if payload.get('piece_idx') != self.current_piece:
                return False                      # duplicate / stale submit
            self.current_piece = None
        i = payload['piece_idx']
        piece = self.sess['pieces'][i]
        by_id = {it['id']: it for it in piece['items']}
        items = []
        for r in payload['items']:
            d = by_id[r['id']]
            items.append({'id': r['id'], 'kind': d['kind'], 'smooth': d['smooth'], 'count': d['count'],
                          'variant': d['variant'], 'pair_id': d['pair_id'], 'query': d['query'],
                          'length': d['length'], 'rating': r['rating'], 'missing': r['missing'],
                          'shown_count': r['shown_count'], 'views': r['views'], 't_rate_ms': r['t_rate_ms']})
        self.resp['pieces'].append({'piece_idx': i, 'piece': piece['piece'], 'shared': piece['shared'],
                                    'elapsed_ms': payload['elapsed_ms'],
                                    'submitted_at': datetime.datetime.now().isoformat(timespec='seconds'),
                                    'items': items})
        self._save()
        self.show_loading()
        threading.Thread(target=self.show_piece, args=(i + 1,), daemon=True).start()
        return True


class BlindHandler(_core.Handler):
    run = None
    page_hits = 0                      # number of page loads (debug: detects reload loops)

    def do_GET(self):
        if self.path.split('?')[0] == '/blind/hits':
            b = str(BlindHandler.page_hits).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(b))); self.end_headers()
            self.wfile.write(b)
            return
        if self.path.split('?')[0] not in ('/events', '/shutdown', '/version'):
            BlindHandler.page_hits += 1
        super().do_GET()

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n) if n else b''
        ok = False
        if self.path == '/blind/begin':
            threading.Thread(target=self.run.show_piece, args=(self.run.idx,), daemon=True).start()
            ok = True
        elif self.path == '/blind/submit':
            try:
                ok = self.run.submit(json.loads(body.decode('utf-8')))
            except Exception as e:
                print('[blind] submit error:', e, flush=True)
        self.send_response(200 if ok else 409)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok' if ok else b'no')


class _Server(_core._ThreadingHTTPServer):
    daemon_threads = True


def _open_browser(url):
    import subprocess, webbrowser
    for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(exe):
            subprocess.Popen([exe, '--new-window', url])
            return
    webbrowser.open(url)


def _pick_session(rater, sdir):
    """Resume the rater's own session if a response file exists, else the first session of this
    experiment (sessions dir) nobody used yet."""
    import glob
    sfiles = sorted(glob.glob(os.path.join(sdir, 'session_*.json')),
                    key=lambda x: int(re.search(r'session_(\d+)', x).group(1)))
    if not sfiles:
        raise SystemExit(f'no session files in {sdir}')
    with open(sfiles[0], encoding='utf-8') as f:
        tag = json.load(f).get('tag', '')
    safe = re.sub(r'[^A-Za-z0-9_-]', '_', rater)
    pre = f'{safe}_{tag}_' if tag else f'{safe}_'
    for fp in sfiles:
        seed = int(re.search(r'session_(\d+)', fp).group(1))
        if os.path.isfile(os.path.join(_here, 'responses', f'{pre}{seed}.json')):
            return fp                                   # resume
    used = set()
    for fp in glob.glob(os.path.join(_here, 'responses', '*.json')):
        try:
            with open(fp, encoding='utf-8') as f:
                r = json.load(f)
            if r.get('tag', '') == tag:
                used.add(r['session_seed'])
        except Exception:
            pass
    for fp in sfiles:
        if int(re.search(r'session_(\d+)', fp).group(1)) not in used:
            return fp
    raise SystemExit('all sessions of this experiment are used; generate more with blind_design.py')


def _cmd_run(a):
    rater = a.rater or input('Rater name/ID: ').strip() or 'anon'
    a.session = a.session or _pick_session(rater, a.sessions_dir)
    print(f'Session: {a.session}', flush=True)
    sess = load_session(a.session)
    run = BlindRun(sess, a.session, rater)
    miss = [p['piece'] for p in sess['pieces'] if p['piece'] not in run.paths]
    if miss:
        raise SystemExit(f'files not found: {miss}')
    BlindHandler.run = run
    try:
        srv = _Server(('127.0.0.1', BLIND_PORT), BlindHandler)
    except OSError:
        raise SystemExit(f'port {BLIND_PORT} is busy (another blind_test.py running?)')
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if run.idx >= run.n:
        run.show_finish()
    else:
        run.show_intro()
        run.prefetch(run.idx)
    url = f'http://127.0.0.1:{BLIND_PORT}/'
    print(f'Blind test for "{rater}" at {url}  (responses: {run.resp_path})  Ctrl+C to stop', flush=True)
    if not a.no_browser:
        _open_browser(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cmd_preview(a):
    sess = load_session(a.session)
    piece = sess['pieces'][a.preview]
    path = resolve_paths([piece['piece']]).get(piece['piece'])
    if not path:
        raise SystemExit(f"file not found for {piece['piece']}")
    html, err = render_piece(path, a.preview, len(sess['pieces']), piece['items'])
    if err:
        raise SystemExit(err)
    html = re.sub(r"new EventSource\('/events'\)", "{set onmessage(f){}, close(){}}", html)   # standalone file
    if a.autoclick is not None:
        html = html.replace('</body>', '<script>window.addEventListener("load",function(){setTimeout(function(){'
                            'var rs=document.querySelectorAll("#blind-panel table tr");'
                            f'var r=rs[{a.autoclick}]; if(r)r.click();'
                            '},1500);});</script></body>', 1)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"wrote {a.out}  ({piece['piece']}, {len(piece['items'])} items)")


def _page_motifs(html):
    i = html.index('var motifs=') + len('var motifs=')
    return json.JSONDecoder().raw_decode(html[i:])[0]


def _variant_count(m, variant):
    """Python mirror of filteredByInv() in reader/app.py: number of occurrences shown for a variant."""
    isb = variant.startswith('b')
    base = variant[1:] if isb else variant
    occs = m['occs']
    isinv = m.get('is_inv') or []
    if base == 'all' or not isinv:
        n = len(occs)
    else:
        want = (base == 'inv')
        n = sum(1 for k in range(len(occs)) if bool(isinv[k]) == want)
    if isb:
        binv = m.get('b_inv') or []
        n += sum(1 for k in range(len(m.get('b_occs') or [])) if base == 'all' or bool(binv[k]) == (base == 'inv'))
    return n


def _cmd_check(a):
    sess = load_session(a.session)
    paths = resolve_paths([p['piece'] for p in sess['pieces']])
    tot = found = ok = 0
    bad = []
    for pi, piece in enumerate(sess['pieces']):
        path = paths.get(piece['piece'])
        html, err = render_piece(path, pi, len(sess['pieces']), piece['items']) if path else (None, 'file not found')
        if err:
            print(f"[{pi}] {piece['piece']}: RENDER ERROR {err}")
            bad.append((piece['piece'], '-', '-', 'render error', err))
            tot += len(piece['items'])
            continue
        motifs = _page_motifs(html)
        byq = {m['queryStr']: m for m in motifs}
        for it in piece['items']:
            tot += 1
            m = byq.get(it['query'])
            if m is None:
                bad.append((piece['piece'], it['query'], it['variant'], 'motif not found', ''))
                continue
            found += 1
            n = _variant_count(m, it['variant'])
            if n == it['count']:
                ok += 1
            else:
                bad.append((piece['piece'], it['query'], it['variant'], f"design {it['count']}", f"page {n}"))
        print(f"[{pi}] {piece['piece']}: {len(piece['items'])} items", flush=True)
    print(f"\nitems {tot}, motif found {found}, count matches {ok}")
    for b in bad:
        print('  MISMATCH', *b)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', default=None, help='session file; default: next unused one in sessions/')
    ap.add_argument('--rater', default=None)
    ap.add_argument('--sessions-dir', default=os.path.join(_here, 'sessions'),
                    help='experiment to run when --session is omitted (e.g. sessions_min16)')
    ap.add_argument('--preview', type=int, default=None, help='render piece N to a standalone HTML file')
    ap.add_argument('--out', default='blind_preview.html')
    ap.add_argument('--autoclick', type=int, default=None, help='(preview) auto-click motif row N')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    if (a.preview is not None or a.check) and not a.session:
        raise SystemExit('--session is required for --preview/--check')
    if a.preview is not None:
        return _cmd_preview(a)
    if a.check:
        return _cmd_check(a)
    _cmd_run(a)


if __name__ == '__main__':
    main()

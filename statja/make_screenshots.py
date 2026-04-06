"""
Generate score screenshots for article examples.
For each piece+query in examples.txt:
  - renders score HTML via kern_reader
  - auto-runs the search, activates boxes
  - if 1 page: screenshots full score
  - if multi-page: screenshots system of first + system of last occurrence
Output: statja/figures/<piece>_<query_slug>.png
"""
import sys, os, re, time, json, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pathlib import Path
from PIL import Image
import numpy as np

OUTPUT_DIR = Path(__file__).parent / 'figures'
OUTPUT_DIR.mkdir(exist_ok=True)

# ── parse examples.txt ────────────────────────────────────────────────────────

def parse_examples(path):
    """
    Returns list of (filename, query) pairs.
    Ignores section headers and comment suffixes.
    Handles lines starting with whitespace (additional query for prev file).
    """
    examples = []
    cur_file = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line.strip() or line.strip().endswith(':'):
                continue
            # line starting with whitespace → additional query for cur_file
            if line[0] in (' ', '\t'):
                parts = line.split()
            else:
                parts = line.split()
                cur_file = parts[0]
            # query is the token matching ;  (contains semicolons)
            query = None
            for p in parts:
                if ';' in p:
                    query = p
                    break
            if query and cur_file:
                # add .krn extension if missing
                fn = cur_file
                if '.' not in fn:
                    fn = fn + '.krn'
                examples.append((fn, query))
    return examples


def slugify(s):
    s = s.replace('+', 'p').replace('-', 'm')
    return re.sub(r'[^\w]', '_', s)[:40]


# ── HTML template with auto-search injection ──────────────────────────────────

IIFE_INJECTION = """
// auto-search injection (runs inside main IIFE so addCustomMotif is in scope)
// expose to window so Python playwright can call it after viewport expansion
window._screenshotOccs = {occs_json};
window._screenshotQuery = {query_json};
window._screenshotAddCustomMotif = addCustomMotif;
"""

# ── renderer ──────────────────────────────────────────────────────────────────

def render_piece(path, query):
    """Returns (html_str, n_pages) or None on failure."""
    import kern_reader as kr
    try:
        result = kr.render_score(path, version='screenshot')
        if result is None:
            return None
        html, n_pages, version, all_seqs, beat_dur_q, pickup_dur_q = result
        # populate _state so _search_motif can find the sequences
        kr._state['seqs']          = all_seqs
        kr._state['beat_dur_q']    = beat_dur_q
        kr._state['pickup_dur_q']  = pickup_dur_q
        # always search with inversion: add ;inv if not already present
        search_query = query if ';inv' in query else query + ';inv'
        search_result = kr._search_motif(search_query)
        occs = search_result.get('occs', [])
        count = search_result.get('count', 0)
        print(f'  search: {count} occurrences (with inv)')
        # inject call to addCustomMotif INSIDE the IIFE, before its closing })()
        iife_call = IIFE_INJECTION.format(
            occs_json=json.dumps(occs),
            query_json=json.dumps(query)
        )
        # find the end of the main IIFE and insert before it
        iife_end = '})();\n'
        idx = html.rfind(iife_end)
        if idx != -1:
            html = html[:idx] + iife_call + html[idx:]
        else:
            html = html.replace('</body>', '<script>' + iife_call + '</script>\n</body>')
        return html, n_pages
    except Exception as e:
        print(f'  render error: {e}')
        import traceback; traceback.print_exc()
        return None


# ── screenshot via playwright ─────────────────────────────────────────────────

def screenshot_piece(html, query, out_path, n_pages):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
            headless=True
        )
        page = browser.new_page(viewport={'width': 1400, 'height': 900})

        # write html to temp file
        tmp = Path(__file__).parent / '_tmp_score.html'
        tmp.write_text(html, encoding='utf-8')
        page.goto(tmp.as_uri())
        page.wait_for_load_state('load')
        time.sleep(1.2)   # let verovio SVG render

        # expand viewport BEFORE drawing boxes so getBoundingClientRect is correct
        full_h = page.evaluate('document.body.scrollHeight')
        page.set_viewport_size({'width': 1400, 'height': max(full_h + 200, 900)})
        time.sleep(0.3)

        # call addCustomMotif (exposed to window by IIFE injection) after viewport expansion
        page.evaluate('''() => {
            if (typeof window._screenshotAddCustomMotif === "function" && window._screenshotOccs.length > 0) {
                window._screenshotAddCustomMotif(window._screenshotOccs, window._screenshotQuery);
            }
        }''')
        time.sleep(0.8)   # let drawBoxes finish

        # collect box rects — motif boxes are SVG <path> elements with vector-effect=non-scaling-stroke
        rects = page.evaluate('''() => {
            var boxes = document.querySelectorAll("path[vector-effect=non-scaling-stroke]");
            var r = [];
            boxes.forEach(function(b) {
                var br = b.getBoundingClientRect();
                if (br.width > 0 || br.height > 0)
                    r.push({x: br.left, y: br.top, w: br.width, h: br.height});
            });
            return r;
        }''')

        if not rects:
            print('  warning: no boxes found, screenshotting full page')
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
            return

        full_png = page.screenshot(full_page=True)
        img = Image.open(io.BytesIO(full_png))
        W, H = img.size

        def trim_right(im, bg=255, margin=50):
            """Crop empty right margin; keep `margin` px of breathing room."""
            arr = np.array(im.convert('L'))
            # find rightmost column that has any non-background pixel
            col_min = arr.min(axis=0)          # min value per column
            nonbg = np.where(col_min < bg)[0]  # columns with content
            if len(nonbg) == 0:
                return im
            right = int(nonbg[-1]) + margin + 1
            right = min(right, im.width)
            return im.crop((0, 0, right, im.height))

        # get full BCR of every .system element — use these as crop boundaries
        sys_rects = page.evaluate('''() => {
            var r = [];
            document.querySelectorAll(".system").forEach(function(s) {
                var br = s.getBoundingClientRect();
                if (br.height > 0) r.push({y0: br.top, y1: br.bottom});
            });
            return r;
        }''')

        def snap_to_system(y, sys_rects):
            """Return (y0, y1) of the system that contains y (client coords)."""
            PAD = 8
            for s in sys_rects:
                if s['y0'] - PAD <= y <= s['y1'] + PAD:
                    return (s['y0'], s['y1'])
            # fallback: nearest system
            best = min(sys_rects, key=lambda s: min(abs(y - s['y0']), abs(y - s['y1'])))
            return (best['y0'], best['y1'])

        # group box rects into score-systems using .system BCRs
        PAD_TOP = 50   # extra room above system for occurrence numbers
        PAD_BOT = 12   # small bottom margin
        systems = []  # list of (y_min, y_max) in client coords, snapped to system bounds
        for r in rects:
            if sys_rects:
                sy0, sy1 = snap_to_system(r['y'] + r['h'] / 2, sys_rects)
            else:
                sy0, sy1 = r['y'] - 100, r['y'] + r['h'] + 100
            merged = False
            for i, (ey0, ey1) in enumerate(systems):
                if abs(sy0 - ey0) < 5:   # same system
                    merged = True
                    break
            if not merged:
                systems.append((sy0, sy1))
        systems.sort()

        from PIL import ImageDraw as _ID

        def clean_crop(img, sy0, sy1, crop_y0, crop_y1, sys_rects):
            """Crop around a system and white-out bleed from adjacent systems."""
            crop = img.crop((0, crop_y0, W, crop_y1)).copy()
            d = _ID.Draw(crop)
            WHITE = (255, 255, 255)
            # find this system in sys_rects
            idx = next((i for i, s in enumerate(sys_rects)
                        if abs(s['y0'] - sy0) < 5), -1)
            # white out everything above midpoint between previous system and this one
            if idx > 0:
                mid = (sys_rects[idx - 1]['y1'] + sy0) / 2
                wipe_to = int(mid) - crop_y0
                if 0 < wipe_to:
                    d.rectangle([0, 0, crop.width, wipe_to], fill=WHITE)
            # white out everything below midpoint between this system and next one
            if idx >= 0 and idx < len(sys_rects) - 1:
                mid = (sy1 + sys_rects[idx + 1]['y0']) / 2
                wipe_from = int(mid) - crop_y0
                if wipe_from < crop.height:
                    d.rectangle([0, wipe_from, crop.width, crop.height], fill=WHITE)
            return trim_right(crop)

        if n_pages == 1 or len(systems) == 1:
            y0 = max(0, int(systems[0][0]) - PAD_TOP)
            y1 = min(H, int(systems[-1][1]) + PAD_BOT)
            clean_crop(img, systems[0][0], systems[0][1], y0, y1, sys_rects).save(str(out_path))
        else:
            # show first system + omission indicator + last system
            first_sys = systems[0]
            last_sys  = systems[-1]

            y0_f = max(0, int(first_sys[0]) - PAD_TOP)
            y1_f = min(H, int(first_sys[1]) + PAD_BOT)
            y0_l = max(0, int(last_sys[0]) - PAD_TOP)
            y1_l = min(H, int(last_sys[1]) + PAD_BOT)

            crop_first = clean_crop(img, first_sys[0], first_sys[1], y0_f, y1_f, sys_rects)
            crop_last  = clean_crop(img, last_sys[0],  last_sys[1],  y0_l, y1_l, sys_rects)
            CW = max(crop_first.width, crop_last.width)

            # omission bar: gray band with three centered dots (drawn as circles)
            bar_h = 44
            bar = Image.new('RGB', (CW, bar_h), (210, 210, 210))
            from PIL import ImageDraw
            draw = ImageDraw.Draw(bar)
            dot_r = 3
            spacing = 22
            cy = bar_h // 2
            x0 = CW // 2 - spacing
            for i in range(3):
                cx = x0 + i * spacing
                draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
                             fill=(40, 40, 40))

            total_h = crop_first.height + bar_h + crop_last.height
            combined = Image.new('RGB', (CW, total_h), (255, 255, 255))
            combined.paste(crop_first, (0, 0))
            combined.paste(bar, (0, crop_first.height))
            combined.paste(crop_last, (0, crop_first.height + bar_h))
            combined.save(str(out_path))

        browser.close()
        tmp.unlink(missing_ok=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    examples_path = Path(__file__).parent / 'examples.txt'
    examples = parse_examples(str(examples_path))
    print(f'Found {len(examples)} piece+query pairs')

    import kern_reader as kr

    for fname, query in examples:
        print(f'\n{fname}  |  {query}')
        path = kr.find_kern_files.__module__ and None  # placeholder
        # find the file
        path = None
        # tsd_model.find_file searches all known dirs (kern, lilypond/musicxml, etc.)
        try:
            import tsd_model
            path = tsd_model.find_file(fname)
        except Exception:
            pass
        if not path:
            root = os.path.join(os.path.dirname(__file__), '..', 'kern')
            for _rel, fp in kr.find_kern_files(root):
                if os.path.basename(fp) == fname:
                    path = fp
                    break
        if not path:
            for _rel, fp in kr.find_music21_files():
                if os.path.basename(fp) == fname:
                    path = fp
                    break
        if not path:
            print(f'  not found: {fname}')
            continue

        result = render_piece(path, query)
        if result is None:
            print(f'  render failed')
            continue
        html, n_pages = result
        print(f'  rendered, {n_pages} page(s)')

        out_name = f'{slugify(fname)}_{slugify(query)}.png'
        out_path = OUTPUT_DIR / out_name
        screenshot_piece(html, query, out_path, n_pages)
        print(f'  saved: {out_path.name}')


if __name__ == '__main__':
    main()

import sys, json, time
sys.path.insert(0, '..')
import kern_reader as kr
from playwright.sync_api import sync_playwright
from pathlib import Path

path = '../kern/osu/classical/bach/inventions/inven01.krn'
query = '1/16;1;-1-1-1+2-1+2-1'
result = kr.render_score(path, version='test')
html, n_pages, version, all_seqs, beat_dur_q, pickup_dur_q = result
kr._state['seqs'] = all_seqs
kr._state['beat_dur_q'] = beat_dur_q
kr._state['pickup_dur_q'] = pickup_dur_q
sr = kr._search_motif(query)
occs = sr['occs']
first_nid = occs[0][0]
print('first nid:', first_nid, '  n_pages:', n_pages)

injection = '<script>window.__autoOccs=' + json.dumps(occs) + ';window.__autoQuery=' + json.dumps(query) + ';</script>'
html2 = html.replace('</body>', injection + '</body>')
tmp = Path('_test_boxes.html').resolve()
tmp.write_text(html2, encoding='utf-8')

with sync_playwright() as p:
    b = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
    page = b.new_page(viewport={'width': 1400, 'height': 900})
    page.on('console', lambda m: print('CONSOLE', m.type, m.text[:120]))
    page.on('pageerror', lambda e: print('PAGEERROR', str(e)[:200]))
    page.goto(tmp.as_uri())
    page.wait_for_load_state('load')
    time.sleep(2)
    full_h = page.evaluate('document.body.scrollHeight')
    print('scrollHeight:', full_h)
    page.set_viewport_size({'width': 1400, 'height': max(full_h + 200, 900)})
    time.sleep(0.5)
    info = page.evaluate('''(nid) => {
        var el = document.getElementById(nid);
        if (!el) return {found: false};
        var cr = el.getBoundingClientRect();
        return {found: true, tag: el.tagName, x: cr.x, y: cr.y, w: cr.width, h: cr.height};
    }''', first_nid)
    print('BCR:', info)

    # call addCustomMotif
    page.evaluate('''() => {
        if (typeof addCustomMotif === "function")
            addCustomMotif(window.__autoOccs, window.__autoQuery);
    }''')
    time.sleep(0.8)

    # check if functions accessible and boxes drawn
    result = page.evaluate('''() => {
        var s = document.querySelectorAll("script")[1].text;
        // try eval first 100 chars
        return {
            win_addCustomMotif: typeof window.addCustomMotif,
            scriptStart: s.substring(0, 80),
            scriptEnd: s.substring(s.length - 80)
        };
    }''')
    print('state:', result)
    b.close()

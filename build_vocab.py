#!/usr/bin/env python3
"""
Build global motif vocabulary from kern + MusicXML corpus.

Composers included by default: Bach, Buxtehude, Vivaldi, Scarlatti.
Sources:
  kern/          — filtered to target composers
  lilypond/musicxml/*.xml — all Bach MusicXML files

Scans all files with analyze_motifs, collects unique (body, phase) patterns,
assigns integer IDs sorted by total corpus occurrence count.

Output:
  motif_vocab.json  — machine-readable vocabulary
  motif_vocab.html  — interactive browser with mini staff notation

Usage:
  python build_vocab.py
  python build_vocab.py --min-files 2   # only motifs appearing in >= N files
  python build_vocab.py --filter wtc    # further narrow by path substring
"""

import json
import multiprocessing
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
import kern_reader as kr


# ── subprocess worker ─────────────────────────────────────────────────────────

def _worker_func(path, q):
    """Analyse one file; put list of motif dicts or None into q."""
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        import kern_reader as _kr

        _kr.check_file(path)
        ext = path.rsplit('.', 1)[-1].lower()

        if ext == 'mxl':
            import zipfile as _zf
            with _zf.ZipFile(path) as z:
                xml_name = next(
                    n for n in z.namelist()
                    if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n
                )
                raw = z.read(xml_name)
                if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                    content = raw.decode('utf-16')
                elif raw[:3] == b'\xef\xbb\xbf':
                    content = raw.decode('utf-8-sig')
                else:
                    content = raw.decode('utf-8', errors='replace')
        else:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

        if ext == 'krn':
            content = _kr.prepare_grand_staff(content)
            content = _kr.add_beam_markers(content)

        _kr._vtk.setOptions({
            'pageWidth':        2200,
            'adjustPageHeight': True,
            'scale':            35,
            'font':             'Leipzig',
        })
        if not _kr._vtk.loadData(content):
            q.put(None)
            return

        mei_str = _kr._vtk.getMEI()
        voices, beat_dur_q = _kr._voice_notes_from_mei(mei_str)
        all_seqs = [(vk, _kr._interval_seq(notes, beat_dur_q))
                    for vk, notes in voices.items()
                    if len(notes) >= 4]
        raw_motifs = _kr._find_motifs(all_seqs)

        out = []
        for m in raw_motifs:
            body  = m['pattern']   # tuple of (interval, dur) — raw body
            phase = m.get('phase', 0)
            # union count = direct-only + inv-only + coinciding
            n_d = m.get('n_direct_only', 0)
            n_i = m.get('n_inv_only', 0)
            n_b = m.get('n_both', 0)
            count = (n_d + n_i + n_b) or len(m['occurrences'])
            out.append({
                'body':       [list(step) for step in body],
                'phase':      phase,
                'count':      count,
                'sample_dp0': 28,   # canonical C4; transposition is a per-occurrence attribute
            })
        q.put(out)
    except Exception:
        q.put(None)


_TIMEOUT = 90


def _analyze_file(ctx, path):
    q = ctx.Queue()
    p = ctx.Process(target=_worker_func, args=(path, q))
    p.start()
    try:
        result = q.get(timeout=_TIMEOUT)
    except Exception:
        result = None
    p.join(timeout=5)
    if p.is_alive():
        p.terminate()
        p.join()
    return result


# ── note reconstruction ───────────────────────────────────────────────────────

_DIATONIC_SEMI = [0, 2, 4, 5, 7, 9, 11]   # C D E F G A B


def body_to_notes_info(body, dp0):
    """
    Reconstruct notes_info for _mini_staff_svg from a motif body + starting dp.
    body: [[interval, dur_q], ...]   — N intervals → N+1 notes
    Returns [(pname_lower, oct_int, dur_q, midi_val, nid), ...]
    """
    notes_info = []
    dp = dp0
    for i, (interval, dur) in enumerate(body):
        oct_  = dp // 7
        step  = dp % 7
        pname = 'cdefgab'[step]
        midi  = oct_ * 12 + _DIATONIC_SEMI[step]
        notes_info.append((pname, oct_, dur, midi, f'n{i}'))
        dp += interval
    # last note — use duration of last interval (best approximation)
    last_dur = body[-1][1] if body else 0.25
    oct_  = dp // 7
    step  = dp % 7
    pname = 'cdefgab'[step]
    midi  = oct_ * 12 + _DIATONIC_SEMI[step]
    notes_info.append((pname, oct_, last_dur, midi, f'n{len(body)}'))
    return notes_info


def _dur_str(d):
    from fractions import Fraction
    f = Fraction(d / 4.0).limit_denominator(64)
    return f'{f.numerator}/{f.denominator}'


def _phase_label(phase):
    if phase == 0:
        return '●'
    return '_|' * phase


# ── HTML generation ───────────────────────────────────────────────────────────

def _generate_html(vocab_json, html_path):
    from kern_reader import _mini_staff_svg

    rows = []
    for entry in vocab_json:
        body  = entry['body']
        phase = entry['phase']
        dp0   = entry['sample_dp0']

        notes_info = body_to_notes_info(body, dp0)
        svg = _mini_staff_svg(notes_info)

        # Interval string: ↑2·1/16 ↓1·1/16 ...
        parts = []
        for iv, d in body:
            arrow = '↑' if iv > 0 else ('↓' if iv < 0 else '—')
            parts.append(f'{arrow}{abs(iv)}·{_dur_str(d)}')
        pat_str = ' '.join(parts)

        n_notes = len(body) + 1
        phase_lbl = _phase_label(phase)

        rows.append(
            f'<tr data-pat="{pat_str.lower()}">'
            f'<td class="id">{entry["id"]}</td>'
            f'<td class="staff">{svg}</td>'
            f'<td class="pat">{pat_str}</td>'
            f'<td class="ph">{phase_lbl}</td>'
            f'<td class="nn">{n_notes}</td>'
            f'<td class="cnt">{entry["total_count"]}</td>'
            f'<td class="nf">{entry["n_files"]}</td>'
            f'</tr>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Global Motif Vocabulary ({len(vocab_json)} types)</title>
<style>
  body {{ font-family: sans-serif; font-size: 13px; padding: 20px 28px;
         background: #f8f8f8; color: #222; }}
  h1   {{ font-size: 17px; margin-bottom: 4px; }}
  .sub {{ color: #888; font-size: 12px; margin-bottom: 14px; }}
  .controls {{ display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }}
  input  {{ padding: 5px 9px; border: 1px solid #ccc; border-radius: 4px;
            font-size: 13px; width: 280px; }}
  select {{ padding: 5px 7px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }}
  label  {{ font-size: 12px; color: #555; }}
  table  {{ border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px #0001; border-radius: 4px; overflow: hidden; }}
  th, td {{ padding: 5px 10px; border-bottom: 1px solid #eee; vertical-align: middle; }}
  th     {{ background: #f0f0f0; cursor: pointer; user-select: none;
            white-space: nowrap; font-size: 12px; }}
  th:hover {{ background: #e4e4e4; }}
  th.sorted-asc::after  {{ content: ' ▲'; font-size: 10px; }}
  th.sorted-desc::after {{ content: ' ▼'; font-size: 10px; }}
  .id  {{ color: #aaa; font-size: 11px; text-align: right; }}
  .pat {{ font-family: monospace; font-size: 11px; color: #444; white-space: nowrap; }}
  .ph  {{ font-family: monospace; font-size: 12px; color: #777; text-align: center; }}
  .nn  {{ text-align: right; color: #999; font-size: 11px; }}
  .cnt {{ text-align: right; font-weight: 600; }}
  .nf  {{ text-align: right; color: #888; }}
  tr:hover td {{ background: #f5f0e8; }}
  tr.hidden {{ display: none; }}
  .staff svg {{ display: block; }}
</style>
</head>
<body>
<h1>Global Motif Vocabulary</h1>
<div class="sub" id="subtitle">{len(vocab_json)} unique patterns across corpus</div>

<div class="controls">
  <input type="text" id="filter" placeholder="Filter by pattern (e.g. ↑1 ↓2)…" oninput="applyFilter()">
  <label>Min files: <select id="minfiles" onchange="applyFilter()">
    <option value="1">1+</option>
    <option value="2" selected>2+</option>
    <option value="3">3+</option>
    <option value="5">5+</option>
    <option value="10">10+</option>
  </select></label>
  <label>Min count: <select id="mincnt" onchange="applyFilter()">
    <option value="1">1+</option>
    <option value="5">5+</option>
    <option value="10" selected>10+</option>
    <option value="20">20+</option>
    <option value="50">50+</option>
  </select></label>
</div>

<table id="tbl">
  <thead><tr>
    <th data-col="0">ID</th>
    <th>Notation</th>
    <th data-col="2">Pattern</th>
    <th data-col="3">Phase</th>
    <th data-col="4">Notes</th>
    <th data-col="5" class="sorted-desc">Count</th>
    <th data-col="6">Files</th>
  </tr></thead>
  <tbody>
{''.join(rows)}
  </tbody>
</table>

<script>
const tbody = document.querySelector('#tbl tbody');
let _sortCol = 5, _sortAsc = false;

function applyFilter() {{
  const q    = document.getElementById('filter').value.toLowerCase();
  const minf = parseInt(document.getElementById('minfiles').value);
  const minc = parseInt(document.getElementById('mincnt').value);
  let vis = 0;
  tbody.querySelectorAll('tr').forEach(tr => {{
    const pat  = tr.dataset.pat || '';
    const nf   = parseInt(tr.cells[6].textContent);
    const cnt  = parseInt(tr.cells[5].textContent);
    const show = (!q || pat.includes(q)) && nf >= minf && cnt >= minc;
    tr.classList.toggle('hidden', !show);
    if (show) vis++;
  }});
  document.getElementById('subtitle').textContent =
    vis + ' of {len(vocab_json)} patterns shown';
}}

document.querySelectorAll('th[data-col]').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = parseInt(th.dataset.col);
    if (_sortCol === col) {{ _sortAsc = !_sortAsc; }}
    else {{ _sortCol = col; _sortAsc = col <= 2; }}
    document.querySelectorAll('th').forEach(t => t.classList.remove('sorted-asc','sorted-desc'));
    th.classList.add(_sortAsc ? 'sorted-asc' : 'sorted-desc');
    sortTable();
  }});
}});

function sortTable() {{
  const rows = [...tbody.rows];
  rows.sort((a, b) => {{
    const av = a.cells[_sortCol].textContent.trim();
    const bv = b.cells[_sortCol].textContent.trim();
    const an = parseFloat(av), bn = parseFloat(bv);
    const cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv);
    return _sortAsc ? cmp : -cmp;
  }});
  rows.forEach(r => tbody.appendChild(r));
}}

// apply defaults on load
applyFilter();
</script>
</body>
</html>"""

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"HTML viewer:  {html_path}")


# ── main ──────────────────────────────────────────────────────────────────────

_COMPOSERS = ['bach', 'buxtehude', 'vivaldi', 'scarlatti']

MUSICXML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'lilypond', 'musicxml')


def _collect_files(filter_terms=None):
    """Return [(rel_path, full_path), ...] for all target files."""
    files = []

    # kern: only target composers
    kern_files = kr.find_kern_files(kr.KERN_DIR)
    for rel, full in kern_files:
        rel_lo = rel.lower()
        if any(c in rel_lo for c in _COMPOSERS):
            files.append((rel, full))

    # MusicXML: all files in lilypond/musicxml/
    if os.path.isdir(MUSICXML_DIR):
        for name in sorted(os.listdir(MUSICXML_DIR)):
            if name.lower().endswith('.xml'):
                rel  = os.path.join('lilypond', 'musicxml', name)
                full = os.path.join(MUSICXML_DIR, name)
                files.append((rel, full))

    if filter_terms:
        files = [(r, f) for r, f in files
                 if any(t in r.lower() for t in filter_terms)]

    return files


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--filter',    default=None,
                        help='Further narrow by path substring (comma-separated OR)')
    parser.add_argument('--min-files', type=int, default=1,
                        help='Exclude motif types appearing in fewer than N files (default 1)')
    args = parser.parse_args()

    filter_terms = ([t.strip().lower() for t in args.filter.split(',')]
                    if args.filter else None)
    all_files = _collect_files(filter_terms)

    total = len(all_files)
    print(f"Scanning {total} files…")

    # vocab: body_key → aggregated entry
    vocab = {}   # (body_tuple, phase) → dict
    n_ok = n_err = 0

    ctx = multiprocessing.get_context('spawn')
    for idx, (rel, full) in enumerate(all_files):
        if (idx + 1) % 10 == 0 or idx == 0:
            print(f"  {idx+1}/{total}  {rel}", flush=True)
        result = _analyze_file(ctx, full)
        if result is None:
            n_err += 1
            continue
        n_ok += 1
        for m in result:
            key = (tuple(tuple(s) for s in m['body']), m['phase'])
            if key not in vocab:
                vocab[key] = {
                    'body':       m['body'],
                    'phase':      m['phase'],
                    'count':      0,
                    'files':      set(),
                    'sample_dp0': m['sample_dp0'],
                }
            entry = vocab[key]
            entry['count'] += m['count']
            entry['files'].add(rel)

    print(f"\nDone.  OK={n_ok}  errors={n_err}")
    print(f"Unique motif types before filtering: {len(vocab)}")

    # filter by min_files
    vocab = {k: v for k, v in vocab.items() if len(v['files']) >= args.min_files}
    print(f"After --min-files={args.min_files}:   {len(vocab)} types")

    # sort by total count descending
    sorted_vocab = sorted(vocab.values(), key=lambda e: -e['count'])

    # build JSON list
    vocab_json = [
        {
            'id':          i,
            'body':        entry['body'],
            'phase':       entry['phase'],
            'total_count': entry['count'],
            'n_files':     len(entry['files']),
            'sample_dp0':  entry['sample_dp0'],
        }
        for i, entry in enumerate(sorted_vocab)
    ]

    base = os.path.dirname(os.path.abspath(__file__))

    json_path = os.path.join(base, 'motif_vocab.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(vocab_json, f, ensure_ascii=False, indent=2)
    print(f"Vocabulary:   {json_path}  ({len(vocab_json)} entries)")

    html_path = os.path.join(base, 'motif_vocab.html')
    _generate_html(vocab_json, html_path)


if __name__ == '__main__':
    main()

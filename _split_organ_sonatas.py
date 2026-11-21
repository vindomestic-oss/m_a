"""Split the organ (trio) sonatas BWV 526-528, 530 (MuseScore .mxl files in musicxml/musedata/)
into one .mxl per movement. BWV 525 already comes split.

* BWV 527/528/530 are "with custom audio" exports: P1 is the real score (3 staves: manuals + pedal),
  P2... are playback copies of P1's notes (the dup check showed 96-100% of their notes inside P1)
  and would triple every note in the reader -> only P1 is kept.
* BWV 526 has three real parts (RH / LH / pedal) -> all kept.
* Each movement's first measure gets the full attribute state (divisions, key, time, staves, clefs)
  accumulated over the preceding measures; measures are renumbered from 1.
* The unsplit originals are moved to musicxml/musedata/_unsplit/.
"""
import os, re, shutil, zipfile

D = r'C:\m_a\musicxml\musedata'

# (source file, kept part ids or None = all, movements [(first_idx, last_idx_exclusive, suffix, title)], base name)
SONATAS = [
    ('bwv-526-trio-sonata-ii-in-c-minor.mxl', None,
     [(0, 78, 'i-vivace', 'I. Vivace'), (78, 126, 'ii-largo', 'II. Largo'), (126, 298, 'iii-allegro', 'III. Allegro')],
     'organ-sonata-n2-in-c-minor-bwv-526'),
    ('sonata-iii-bwv-527-with-custom-audio.mxl', ['P1'],
     [(0, 160, 'i-adagio', 'I. Adagio'), (160, 224, 'ii-adagio-e-dolce', 'II. Adagio e dolce'),
      (224, 404, 'iii-vivace', 'III. Vivace')],
     'organ-sonata-n3-in-d-minor-bwv-527'),
    ('sonata-no-4-bwv-528-with-custom-audio-source.mxl', ['P1'],
     [(0, 65, 'i-adagio-vivace', 'I. Adagio - Vivace'), (65, 110, 'ii-andante', 'II. Andante'),
      (110, 207, 'iii-un-poco-allegro', 'III. Un poco allegro')],
     'organ-sonata-n4-in-e-minor-bwv-528'),
    ('sonata-no-6-bwv-530.mxl', ['P1'],
     [(0, 180, 'i-vivace', 'I. Vivace'), (180, 261, 'ii-lento', 'II. Lento'),
      (261, 338, 'iii-allegro', 'III. Allegro')],
     'organ-sonata-n6-in-g-major-bwv-530'),
    # --- organ preludes / fantasias with fugues (each file holds both pieces; base '' = suffix is the full name)
    ('bwv-536-prelude-and-fugue-in-a-major.mxl', None,
     [(0, 32, 'bwv_536_1_prelude_A_major', 'Prelude'), (32, 168, 'bwv_536_2_fugue_A_major', 'Fugue')], ''),
    ('bwv-562-fantasia-and-fugue-in-c-minor.mxl', None,
     [(0, 81, 'bwv_562_1_fantasia_C_minor', 'Fantasia'), (81, 109, 'bwv_562_2_fugue_C_minor', 'Fugue')], ''),
    ('j-s-bach-fantasia-and-bwv_537_2_fugue_C_minor.mxl', ['P1'],      # P2-P4 = octave-shifted registration copies
     [(0, 48, 'bwv_537_1_fantasia_C_minor', 'Fantasia'), (48, 179, 'bwv_537_2_fugue_C_minor', 'Fugue')], ''),
    ('j-s-bach-prelude-and-bwv_545_2_fugue_C_major.mxl', ['P1'],      # P2-P4 = pedal copies an octave lower
     [(0, 31, 'bwv_545_1_prelude_C_major', 'Prelude'), (31, 142, 'bwv_545_2_fugue_C_major', 'Fugue')], ''),
    ('j-s-bach-prelude-and-bwv_547_2_fugue_C_major.mxl', ['P1'],      # P2/P3 = pedal copies
     [(0, 88, 'bwv_547_1_prelude_C_major', 'Prelude'), (88, 160, 'bwv_547_2_fugue_C_major', 'Fugue')], ''),
    ('prelude-and-bwv_539_2_fugue-johann-sebastian-bach-organ-soundfonts-and-expressions.mxl', None,
     [(0, 43, 'bwv_539_1_prelude_D_minor', 'Prelude'), (43, 139, 'bwv_539_2_fugue_D_minor', 'Fugue')], ''),
    ('prelude-and-bwv_548_2_fugue-johann-sebastian-bach.mxl', None,
     [(0, 137, 'bwv_548_1_prelude_E_minor', 'Prelude'), (137, 330, 'bwv_548_2_fugue_E_minor', 'Fugue')], ''),
    ('prelude-toccata-and-bwv_540_2_fugue_F_major.mxl', None,
     [(0, 438, 'bwv_540_1_toccata_F_major', 'Prelude (Toccata)'), (438, 608, 'bwv_540_2_fugue_F_major', 'Fugue')], ''),
]


def split_part(part_xml):
    """-> (header, [measure xml strings], footer)"""
    pieces = re.split(r'(?=<measure[ >])', part_xml)
    header = pieces[0]
    last = pieces[-1]
    k = last.rindex('</part>')
    pieces[-1], footer = last[:k], last[k:]
    return header, pieces[1:], footer


ATTR_RE = re.compile(r'<attributes>.*?</attributes>', re.S)


def update_state(state, attr_xml):
    for tag in ('divisions', 'staves'):
        m = re.search(r'<%s>[^<]*</%s>' % (tag, tag), attr_xml)
        if m:
            state[tag] = m.group(0)
    for tag in ('key', 'time'):
        m = re.search(r'<%s[ >].*?</%s>' % (tag, tag), attr_xml, re.S)
        if m:
            state[tag] = m.group(0)
    for m in re.finditer(r'<clef(?: [^>]*)?>.*?</clef>', attr_xml, re.S):
        num = re.search(r'number="(\d+)"', m.group(0))
        state.setdefault('clef', {})[num.group(1) if num else '1'] = m.group(0)


def state_xml(state, nl):
    ind = '        '
    parts = [state.get('divisions'), state.get('key'), state.get('time'), state.get('staves')]
    parts += [c for _n, c in sorted(state.get('clef', {}).items())]
    return '<attributes>' + ''.join(nl + ind + p for p in parts if p) + nl + '      </attributes>'


def build_movement(part_header, measures, footer, state_before, first, last, nl):
    ms = list(measures[first:last])
    state = {k: (dict(v) if isinstance(v, dict) else v) for k, v in state_before.items()}
    m0 = ms[0]
    a = ATTR_RE.search(m0)
    if a:
        update_state(state, a.group(0))
        m0 = m0[:a.start()] + state_xml(state, nl) + m0[a.end():]
    else:
        close = m0.index('>') + 1
        m0 = m0[:close] + nl + '      ' + state_xml(state, nl) + m0[close:]
    ms[0] = m0
    out = []
    for i, m in enumerate(ms):
        out.append(re.sub(r'(<measure[^>]*?number=")([^"]*)(")', lambda mm: mm.group(1) + str(i + 1) + mm.group(3), m, count=1))
    return part_header + ''.join(out) + footer


def run(src, keep, movements, base):
    path = os.path.join(D, src)
    with zipfile.ZipFile(path) as z:
        cont = z.read('META-INF/container.xml')
        inner = next(n for n in z.namelist() if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n)
        s = z.read(inner).decode('utf-8')
    nl = '\r\n' if '\r\n' in s else '\n'
    p_re = re.compile(r'<part id="([^"]*)">.*?</part>', re.S)
    parts = [(m.group(1), m.start(), m.end()) for m in p_re.finditer(s)]
    head = s[:parts[0][1]]
    tail = s[parts[-1][2]:]
    # keep only the requested parts, also in <part-list>
    if keep is not None:
        for pid, _a, _b in parts:
            if pid not in keep:
                head = re.sub(r'<score-part id="%s">.*?</score-part>\s*' % pid, '', head, flags=re.S)
    kept = [(pid, s[a:b]) for pid, a, b in parts if keep is None or pid in keep]
    split = {}
    for pid, pxml in kept:
        hdr, ms, ftr = split_part(pxml)
        split[pid] = (hdr, ms, ftr)
        assert len(ms) >= max(m[1] for m in movements), (src, pid, len(ms))
    # attribute state at the start of each movement, per part
    states = {}
    for pid, (_h, ms, _f) in split.items():
        st = {}
        marks = {m[0]: None for m in movements}
        states[pid] = {}
        for i, m in enumerate(ms):
            if i in marks:
                states[pid][i] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in st.items()}
            for a in ATTR_RE.finditer(m):
                update_state(st, a.group(0))
    outs = []
    for first, last, suffix, title in movements:
        body = ''.join(build_movement(split[pid][0], split[pid][1], split[pid][2], states[pid][first], first, last, nl)
                       for pid, _x in kept)
        h = re.sub(r'(<work-title>)[^<]*(</work-title>)', lambda m: m.group(1) + re.sub(r'\s*$', '', re.search(r'<work-title>([^<]*)', head).group(1)) + ' - ' + title + m.group(2), head, count=1)
        xml = h + body + tail
        name = ('%s-%s.mxl' % (base, suffix)) if base else (suffix + '.mxl')
        with zipfile.ZipFile(os.path.join(D, name), 'w', zipfile.ZIP_DEFLATED) as zz:
            zz.writestr('META-INF/container.xml', cont)
            zz.writestr('score.xml', xml)
        n_meas = len(re.findall(r'<measure[ >]', xml)) // len(kept)
        outs.append((name, n_meas, len(kept)))
        print(name, n_meas, 'measures x', len(kept), 'part(s)')
    return path


if __name__ == '__main__':
    done = []
    for src, keep, movements, base in SONATAS:
        if os.path.exists(os.path.join(D, src)):
            done.append(run(src, keep, movements, base))
    os.makedirs(os.path.join(D, '_unsplit'), exist_ok=True)
    for p in done:
        shutil.move(p, os.path.join(D, '_unsplit', os.path.basename(p)))
        print('moved to _unsplit:', os.path.basename(p))

"""Split flute sonatas BWV 1030/1031/1032 .mxl into per-movement .mxl files."""
import re, zipfile, os, shutil
D = r'C:\m_a\musicxml\musedata'
ORIG = r'C:\m_a\musicxml\_orig'
# src file -> (BWV, [(first_measure_index, name)])
# src file -> (BWV, key name, [(first_measure_index, name)], renumber_from_1)
JOBS = {
 'flute-sonata-in-b-minor-bwv-1030-johann-sebastian-bach.mxl':
   ('1030', 'B minor', [(0, 'Andante'), (120, 'Largo e dolce'), (138, 'Presto'), (221, 'Presto 12-16')], False),
 'flute-sonata-in-e-flat-major-bwv-1031-johann-sebastian-bach.mxl':
   ('1031', 'E-flat major', [(0, 'Allegro moderato'), (71, 'Siciliano'), (104, 'Allegro')], False),
 'bach-flute-sonata-in-a-major-bwv-1032.mxl':
   ('1032', 'A major', [(0, 'Vivace'), (102, 'Largo e dolce'), (139, 'Allegro')], False),
 'flute-sonata-in-c-major-bwv-1033-johann-sebastian-bach.mxl':
   ('1033', 'C major', [(0, 'Andante-Presto'), (26, 'Allegro'), (74, 'Adagio'), (88, 'Menuetto')], False),
 'bwv-1034-flute-sonata-in-e-minor.mxl':
   ('1034', 'E minor', [(0, 'Adagio ma non tanto'), (30, 'Allegro'), (100, 'Andante'), (156, 'Allegro')], True),
 'bwv-1035-flute-sonata-in-e-major.mxl':
   ('1035', 'E major', [(0, 'Adagio ma non tanto'), (20, 'Allegro'), (213, 'Siciliano'), (270, 'Allegro assai')], True),
}
MEAS = re.compile(r'<measure [^>]*>.*?</measure>', re.S)
PART = re.compile(r'<part id="[^"]*">.*?</part>', re.S)

def last(tag, text):
    r = re.findall(r'<%s(?:\s[^>]*)?>.*?</%s>' % (tag, tag), text, re.S)
    return r[-1] if r else None

def last_clefs(text):
    d = {}
    for c in re.findall(r'<clef(?:\s[^>]*)?>.*?</clef>', text, re.S):
        m = re.match(r'<clef\s[^>]*number="(\d+)"', c)
        d[m.group(1) if m else '1'] = c
    return [d[k] for k in sorted(d)]

def build_attrs(prefix_text, first_attr):
    """first_attr: original first <attributes> block of the part (carries staves etc.)."""
    a = first_attr
    div = last('divisions', prefix_text)
    key = last('key', prefix_text)
    tim = last('time', prefix_text)
    a = re.sub(r'<divisions>.*?</divisions>', lambda m: div, a, flags=re.S) if div else a
    a = re.sub(r'<key(?:\s[^>]*)?>.*?</key>', lambda m: key, a, count=1, flags=re.S) if key else a
    a = re.sub(r'<time(?:\s[^>]*)?>.*?</time>', lambda m: tim, a, count=1, flags=re.S) if tim else a
    clefs = last_clefs(prefix_text)
    if clefs:
        a = re.sub(r'<clef(?:\s[^>]*)?>.*?</clef>\s*', '', a, flags=re.S)
        a = a.replace('</attributes>', ''.join(clefs) + '</attributes>')
    return a

for src, (bwv, keyname, movs, renum) in JOBS.items():
    path = os.path.join(D, src)
    if not os.path.exists(path):
        path = os.path.join(ORIG, src)
    z = zipfile.ZipFile(path)
    _closer = z
    inner = next(n for n in z.namelist() if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n)
    cont = z.read('META-INF/container.xml').decode('utf-8')
    cont = re.sub(r'full-path="[^"]*"', 'full-path="score.xml"', cont).encode('utf-8')
    s = z.read(inner).decode('utf-8-sig'); z.close()
    parts = list(PART.finditer(s))
    head, tail = s[:parts[0].start()], s[parts[-1].end():]
    between = [s[parts[i].end():parts[i+1].start()] for i in range(len(parts)-1)]
    pm = [MEAS.findall(p.group(0)) for p in parts]
    ph = [re.match(r'<part [^>]*>', p.group(0)).group(0) for p in parts]
    n = len(pm[0]); assert all(len(x) == n for x in pm)
    bounds = [b for b, _ in movs] + [n]
    for idx, (b0, mname) in enumerate(movs):
        b1 = bounds[idx+1]
        out_parts = []
        for pi in range(len(parts)):
            ms = pm[pi]
            first_attr = re.search(r'<attributes>.*?</attributes>', ms[0], re.S).group(0)
            prefix = ''.join(ms[:b0+1])
            attrs = build_attrs(prefix, first_attr)
            mv = list(ms[b0:b1])
            m0 = mv[0]
            # drop existing attributes block preceding first note
            mo = re.search(r'<attributes>.*?</attributes>', m0, re.S)
            fn = m0.find('<note')
            if mo and (fn < 0 or mo.start() < fn):
                m0 = m0[:mo.start()] + m0[mo.end():]
            m0 = re.sub(r'(<measure [^>]*>)', lambda m: m.group(1) + attrs, m0, count=1)
            mv[0] = m0
            if renum:
                mv = [re.sub(r'(<measure [^>]*?number=")[^"]*(")', lambda m, k=k: m.group(1) + str(k + 1) + m.group(2), x, count=1)
                      for k, x in enumerate(mv)]
            out_parts.append(ph[pi] + ''.join(mv) + '</part>')
        body = out_parts[0]
        for i in range(1, len(out_parts)):
            body += between[i-1] + out_parts[i]
        title = f'Flute Sonata in {keyname}, BWV {bwv} - {idx+1}. {mname}'
        h = re.sub(r'(<work-title>).*?(</work-title>)', lambda m: m.group(1) + title + m.group(2), head, flags=re.S)
        xml = h + body + tail
        slug = re.sub(r'[^a-z0-9]+', '-', mname.lower()).strip('-')
        name = f'flute-sonata-bwv-{bwv}-{idx+1}-{slug}.mxl'
        with zipfile.ZipFile(os.path.join(D, name), 'w', zipfile.ZIP_DEFLATED) as zo:
            zo.writestr('META-INF/container.xml', cont)
            zo.writestr('score.xml', xml)
        print(name, b1 - b0, 'measures')
    os.makedirs(ORIG, exist_ok=True)
    if os.path.dirname(path) != ORIG:
        shutil.move(path, os.path.join(ORIG, src))

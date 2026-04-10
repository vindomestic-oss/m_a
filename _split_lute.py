import xml.etree.ElementTree as ET, re, os, copy, unicodedata, urllib.request, zipfile, io

ET.register_namespace('', 'http://www.musicxml.org/ns/musicxml')
MVT_PAT   = re.compile(r'^\d+\.\s+(.+)')
MVT_NAMES = re.compile(r'^(Gigue|Allemande|Courante|Sarabande|Gavotte|Menuett|Bourr.e|Loure|Pr.ludium|Fuga|Allegro|Andante|Presto|Air|Double|Rondeau)[\s\.]?$', re.IGNORECASE)
BASE_URL  = 'https://www.tobis-notenarchiv.de/bach/11-Lautenwerke/BWV_{:04d}.zip'
BASE      = r'C:\m_a\tobis-notenarchiv.de\split\lautenwerke'

def to_ascii(s):
    return re.sub(r'[^A-Za-z0-9]','_', unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode()).strip('_')

def has_meter_change(m, ns):
    a = m.find(ns+'attributes')
    return a is not None and a.find(ns+'time') is not None

def get_full_bar_dur(measures, up_to, ns):
    """Expected bar duration in divisions units (single voice), scanning up to index up_to inclusive."""
    divs = 1; beats_n = 4; beats_d = 4
    for m in measures[:up_to+1]:
        a = m.find(ns+'attributes')
        if a is None: continue
        d = a.find(ns+'divisions')
        if d is not None: divs = int(d.text)
        t = a.find(ns+'time')
        if t is not None:
            bn = t.find(ns+'beats')
            bt = t.find(ns+'beat-type')
            if bn is not None: beats_n = int(bn.text)
            if bt is not None: beats_d = int(bt.text)
    return divs * beats_n * 4 // beats_d

def voice1_dur(m, ns):
    """Duration of voice-1 notes (before first <backup>) in divisions units."""
    dur = 0
    for child in m:
        tag = child.tag.split('}')[-1]
        if tag == 'backup':
            break
        if tag == 'note' and child.find(ns+'chord') is None:
            d = child.find(ns+'duration')
            if d is not None: dur += int(d.text)
    return dur

def detect_boundaries(measures, ns):
    bounds = []
    for i, m in enumerate(measures):
        for d in m.findall('.//' + ns+'direction'):
            for w in d.findall('.//' + ns+'words'):
                txt = (w.text or '').strip()
                mt = MVT_PAT.match(txt)
                mn = MVT_NAMES.match(txt) if i > 0 else None
                if mt or mn:
                    title = mt.group(1).strip() if mt else txt.split()[0]
                    if i > 0 and has_meter_change(measures[i-1], ns):
                        start = i - 1
                    elif i > 0:
                        # Also look 2-3 bars back for a meter change that
                        # precedes the text label (e.g. Gigue's 3/8 starts 2
                        # bars before "7. Gigue." text).
                        found_back = None
                        for back in range(2, min(i + 1, 4)):
                            if has_meter_change(measures[i - back], ns):
                                found_back = i - back
                                break
                        if found_back is not None:
                            start = found_back
                        else:
                            expected = get_full_bar_dur(measures, i-1, ns)
                            actual = voice1_dur(measures[i-1], ns)
                            # Don't pull in a bar that ends the previous section
                            # (backward repeat / final barline = end of movement, not a pickup)
                            prev_has_repeat = any(
                                r.get('direction') == 'backward'
                                for r in measures[i-1].findall('.//' + ns + 'repeat')
                            )
                            start = i - 1 if (actual > 0 and actual < expected and not prev_has_repeat) else i
                    else:
                        start = i
                    if not bounds or bounds[-1][0] != start:
                        bounds.append((start, title))
    return bounds

def collect_attrs_up_to(measures, end_idx, ns):
    attrs = {}; clefs = {}
    for m in measures[:end_idx]:
        a = m.find(ns+'attributes')
        if a is None: continue
        for child in a:
            tag = child.tag.split('}')[-1]
            if tag == 'clef': clefs[child.get('number','1')] = copy.deepcopy(child)
            else: attrs[tag] = copy.deepcopy(child)
    if not attrs and not clefs: return None
    merged = ET.Element(ns+'attributes' if ns else 'attributes')
    for tag in ('divisions','key','time','staves'):
        if tag in attrs: merged.append(attrs[tag])
    for num in sorted(clefs): merged.append(clefs[num])
    return merged

def split_file(src, bwv_str):
    tree = ET.parse(src)
    root = tree.getroot()
    ns = '{http://www.musicxml.org/ns/musicxml}' if root.tag.startswith('{') else ''
    part = root.find('.//' + ns+'part')
    measures = list(part.findall(ns+'measure'))
    bounds = detect_boundaries(measures, ns)
    if not bounds: print('  no movements'); return
    for k, (start, title) in enumerate(bounds):
        end = bounds[k+1][0] if k+1 < len(bounds) else len(measures)
        new_root = copy.deepcopy(root)
        new_part = new_root.find('.//' + ns+'part')
        for m in list(new_part.findall(ns+'measure')): new_part.remove(m)
        mvt_m = [copy.deepcopy(m) for m in measures[start:end]]
        if k > 0:
            inh = collect_attrs_up_to(measures, start, ns)
            if inh is not None:
                first_attrs = mvt_m[0].find(ns+'attributes')
                if first_attrs is None:
                    mvt_m[0].insert(0, inh)
                else:
                    # Merge missing inherited attributes into existing block
                    existing_tags = {child.tag.split('}')[-1] for child in first_attrs}
                    pos = 0
                    for tag in ('divisions', 'key', 'time', 'staves'):
                        inh_el = inh.find((ns + tag) if ns else tag)
                        if inh_el is not None and tag not in existing_tags:
                            first_attrs.insert(pos, copy.deepcopy(inh_el))
                            pos += 1
        for m in mvt_m: new_part.append(m)
        slug = to_ascii(re.sub(r'^\d+\.\s*','',title))
        out = os.path.join(BASE, bwv_str+'_'+str(k+1)+'_'+slug+'.xml')
        ET.indent(new_root, space='\t')
        ET.ElementTree(new_root).write(out, encoding='unicode', xml_declaration=True)
        print('  ' + os.path.basename(out) + '  (' + str(end-start) + ' measures)')

SPLITS = [(995,'BWV_0995'),(996,'BWV_0996'),(997,'BWV_0997'),(998,'BWV_0998')]
for bwv, bwv_str in SPLITS:
    # clean old numbered splits
    for f in os.listdir(BASE):
        if re.match(bwv_str + r'_\d+_', f) and f.endswith('.xml'):
            os.remove(os.path.join(BASE, f))
    # download fresh
    data = urllib.request.urlopen(BASE_URL.format(bwv)).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        src_fn = os.path.basename(names[0]).replace('.musicxml','.xml')
        src = os.path.join(BASE, src_fn)
        with open(src,'wb') as f: f.write(z.read(names[0]))
    print('=== BWV_' + str(bwv) + ' (' + src_fn + ') ===')
    split_file(src, bwv_str)
    os.remove(src)

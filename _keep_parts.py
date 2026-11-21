"""Drop duplicate / playback-copy parts from a MuseScore .mxl (the original goes to musicxml/musedata/_unsplit/).

  python _keep_parts.py <file.mxl> P1,P7

Used for exports where P2.. are registration copies of P1 (every note of the copy is already in P1,
possibly an octave shifted): left in, they would multiply every note in the analysis.
"""
import os, re, shutil, sys, zipfile

D = r'C:\m_a\musicxml\musedata'


def keep_parts(name, keep):
    path = os.path.join(D, name)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        blobs = {n: z.read(n) for n in names}
    inner = next(n for n in names if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n)
    s = blobs[inner].decode('utf-8')
    ids = re.findall(r'<part id="([^"]*)"', s)
    for pid in ids:
        if pid in keep:
            continue
        s = re.sub(r'<score-part id="%s">.*?</score-part>\s*' % re.escape(pid), '', s, count=1, flags=re.S)
        s = re.sub(r'<part id="%s">.*?</part>\s*' % re.escape(pid), '', s, count=1, flags=re.S)
    os.makedirs(os.path.join(D, '_unsplit'), exist_ok=True)
    shutil.copy2(path, os.path.join(D, '_unsplit', name))
    blobs[inner] = s.encode('utf-8')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, blobs[n])
    return ids, [p for p in ids if p in keep]


if __name__ == '__main__':
    ids, kept = keep_parts(sys.argv[1], set(sys.argv[2].split(',')))
    print('parts', ids, '-> kept', kept)

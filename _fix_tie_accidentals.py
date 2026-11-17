"""Add an invisible <accidental> to tie-stop notes that have <alter> but no <accidental>.

Verovio's MusicXML importer matches the two ends of a tie by the written accidental, not by
<alter>. A tie-stop note such as B-flat without <accidental> is read as B-natural, the tie stays
open ("ties left open") and the note is sounded / analysed as a second, wrong-pitch attack.
Adding <accidental print-object="no"> tells verovio the pitch without printing a symbol.

Usage:  python _fix_tie_accidentals.py file.mxl [file2.xml ...]    (rewrites in place)
"""
import os, re, sys, zipfile

ACC = {1: 'sharp', 2: 'double-sharp', -1: 'flat', -2: 'flat-flat'}


def fix_xml(xml):
    n_fixed = 0

    def fix_note(m):
        nonlocal n_fixed
        t = m.group(0)
        if '<tie type="stop"' not in t or '<accidental' in t:
            return t
        a = re.search(r'<alter>(-?\d+)</alter>', t)
        if not a or int(a.group(1)) not in ACC:
            return t
        # schema order: ... <type/> <dot/>* <accidental/> ...
        t2, k = re.subn(r'(<type>[^<]*</type>(?:\s*<dot\s*/>)*)',
                        lambda mm: mm.group(1) + '<accidental print-object="no">%s</accidental>'
                        % ACC[int(a.group(1))], t, count=1)
        if k:
            n_fixed += 1
            return t2
        return t

    out = re.sub(r'<note[ >].*?</note>', fix_note, xml, flags=re.S)
    return out, n_fixed


def fix_file(path):
    if path.lower().endswith('.mxl'):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            blobs = {n: z.read(n) for n in names}
        inner = next(n for n in names if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n)
        xml, k = fix_xml(blobs[inner].decode('utf-8'))
        blobs[inner] = xml.encode('utf-8')
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for n in names:
                z.writestr(n, blobs[n])
    else:
        with open(path, encoding='utf-8', newline='') as f:
            xml, k = fix_xml(f.read())
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(xml)
    return k


if __name__ == '__main__':
    for p in sys.argv[1:]:
        print(os.path.basename(p), 'tie-stop accidentals added:', fix_file(p))

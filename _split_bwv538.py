"""Split bwv-538_dorian.mxl (Toccata and Fugue in D minor "Dorian") into Toccata and Fugue .mxl files.

The musedata score is one part, 321 measures without a number restart. The toccata ends at
measure 99 (light-heavy barline); the fugue ("Fuga.", 2/2) starts at measure 100. The fugue
measures are renumbered from 1 and get the full <attributes> of measure 1 with the fugue's meter.
The unsplit original is moved to musicxml/musedata/_unsplit/ so the menu lists only the two halves.
"""
import os, re, shutil, zipfile

D = r'C:\m_a\musicxml\musedata'
SRC = os.path.join(D, 'bwv-538_dorian.mxl')
SPLIT_AT = 100                                   # first measure of the fugue

with zipfile.ZipFile(SRC) as z:
    s = z.read('score.xml').decode('utf-8')
    cont = z.read('META-INF/container.xml')

starts = [(m.start(), int(m.group(1))) for m in re.finditer(r'<measure number="(-?\d+)"', s)]
i_split = next(i for i, (_p, n) in enumerate(starts) if n == SPLIT_AT)
cut = starts[i_split][0]
end_part = s.index('</part>')
head, toc_m, fug_m, tail = s[:starts[0][0]], s[starts[0][0]:cut], s[cut:end_part], s[end_part:]

# fugue: full attributes of measure 1 (divisions, key, clef, ...) with the fugue's own time signature
a0 = s.index('<attributes>'); a1 = s.index('</attributes>', a0) + len('</attributes>')
full_attr = s[a0:a1]
fug_time = re.search(r'<time[^>]*>.*?</time>', fug_m, re.S).group(0)
new_attr = re.sub(r'<time[^>]*>.*?</time>', fug_time, full_attr, flags=re.S)
fug_m = re.sub(r'<attributes>.*?</attributes>', new_attr, fug_m, count=1, flags=re.S)
# renumber the fugue from 1
fug_m = re.sub(r'<measure number="(-?\d+)"',
               lambda m: '<measure number="%d"' % (int(m.group(1)) - SPLIT_AT + 1), fug_m)

def retitle(h, title):
    out = h.replace('Toccata and Fugue in D Minor &quot;Dorian&quot; BWV 538', title)
    assert out != h
    return out


out = {
    'bwv_538_1_toccata_D_minor.mxl': retitle(head, 'Toccata in D Minor &quot;Dorian&quot; BWV 538') + toc_m + tail,
    'bwv_538_2_fugue_D_minor.mxl':   retitle(head, 'Fugue in D Minor &quot;Dorian&quot; BWV 538') + fug_m + tail,
}
for name, xml in out.items():
    with zipfile.ZipFile(os.path.join(D, name), 'w', zipfile.ZIP_DEFLATED) as zz:
        zz.writestr('META-INF/container.xml', cont)
        zz.writestr('score.xml', xml)
    print(name, len(re.findall(r'<measure ', xml)), 'measures')

os.makedirs(os.path.join(D, '_unsplit'), exist_ok=True)
shutil.move(SRC, os.path.join(D, '_unsplit', os.path.basename(SRC)))
print('moved original to _unsplit/')

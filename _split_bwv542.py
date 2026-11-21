"""Split fantasia-and-fugue-in-g-minor-bwv-542.mxl into Fantasia and Fugue .mxl files."""
import re, sys, zipfile, os
D = r'C:\m_a\musicxml\musedata'
SRC = os.path.join(D, 'fantasia-and-fugue-in-g-minor-bwv-542.mxl')
s = zipfile.ZipFile(SRC).read('score.xml').decode('utf-8')
cont = zipfile.ZipFile(SRC).read('META-INF/container.xml')

starts = [m.start() for m in re.finditer(r'<measure number="1"', s)]
assert len(starts) == 2
end_part = s.index('</part>')
head, fant_m, fug_m, tail = s[:starts[0]], s[starts[0]:starts[1]], s[starts[1]:end_part], s[end_part:]

a0 = s.index('<attributes>'); a1 = s.index('</attributes>', a0) + len('</attributes>')
full_attr = s[a0:a1]
fug_time = re.search(r'<time[^>]*>.*?</time>', fug_m, re.S).group(0)
new_attr = re.sub(r'<time[^>]*>.*?</time>', fug_time, full_attr, flags=re.S)
fug_m = re.sub(r'<attributes>.*?</attributes>', new_attr, fug_m, count=1, flags=re.S)

def retitle(h, title):
    return h.replace('Fantasia and Fugue in G Minor', title)

out = {
 'fantasia-in-g-minor-bwv-542.mxl': retitle(head, 'Fantasia in G Minor') + fant_m + tail,
 'fugue-in-g-minor-bwv-542.mxl':    retitle(head, 'Fugue in G Minor') + fug_m + tail,
}
for name, xml in out.items():
    with zipfile.ZipFile(os.path.join(D, name), 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('META-INF/container.xml', cont)
        z.writestr('score.xml', xml)
    print(name, len(re.findall(r'<measure ', xml)), 'measures')

import sys, re, glob, os
import xml.etree.ElementTree as ET
from fractions import Fraction

STEP = {'C': 0, 'D': 1, 'E': 2, 'F': 3, 'G': 4, 'A': 5, 'B': 6}
XML_DIR = r'C:\m_a\lilypond\musicxml'
LY_DIR = r'C:\m_a\lilypond\bach'


def parse(path):
    root = ET.parse(path).getroot()
    res = {}  # part idx -> {(staff,voice): [(on, end, dp)]}
    for pi, part in enumerate(root.findall('part')):
        voices = {}
        t0 = Fraction(0)
        div = 1
        for msr in part.findall('measure'):
            pos = Fraction(0)
            last_dur = Fraction(0)
            maxpos = Fraction(0)
            for el in msr:
                if el.tag == 'attributes':
                    d = el.find('divisions')
                    if d is not None:
                        div = int(d.text)
                elif el.tag == 'note':
                    dur = Fraction(int(el.find('duration').text), div) if el.find('duration') is not None else Fraction(0)
                    chord = el.find('chord') is not None
                    start = pos - last_dur if chord else pos
                    if el.find('rest') is None and el.find('grace') is None:
                        p = el.find('pitch')
                        dp = int(p.find('octave').text) * 7 + STEP[p.find('step').text]
                        v = el.find('voice').text if el.find('voice') is not None else '1'
                        st = el.find('staff').text if el.find('staff') is not None else '1'
                        voices.setdefault((st, v), []).append((t0 + start, t0 + start + dur, dp))
                    if not chord:
                        last_dur = dur
                        pos += dur
                    maxpos = max(maxpos, pos)
                elif el.tag == 'backup':
                    pos -= Fraction(int(el.find('duration').text), div)
                elif el.tag == 'forward':
                    pos += Fraction(int(el.find('duration').text), div)
                    maxpos = max(maxpos, pos)
            t0 += maxpos
        res[pi] = voices
    return res


def detect(voices):
    """voice A ends at T (no later notes) and voice B in same staff starts at T with |dp diff|<=2,
    or voice A has a hole [t1,t2] exactly filled by B."""
    out = []
    items = {k: sorted(v) for k, v in voices.items() if v}
    keys = list(items)
    for ka in keys:
        a = items[ka]
        for kb in keys:
            if ka == kb or ka[0] != kb[0]:
                continue
            b = items[kb]
            # A's end -> B's start
            a_last = a[-1]
            if b[0][0] == a_last[1] and abs(b[0][2] - a_last[2]) <= 2 and b[0][0] > 0:
                # A must not simply be a voice that ends with the piece, B must not start with piece
                out.append(('end->start', ka, kb, float(a_last[1])))
    return out


def main():
    names = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(LY_DIR + r'\*.ly'))
    total = 0
    for n in names:
        p = os.path.join(XML_DIR, n + '.xml')
        if not os.path.exists(p):
            continue
        try:
            res = parse(p)
        except Exception as e:
            print('ERR', n, e)
            continue
        ev = []
        for pi, voices in res.items():
            for e in detect(voices):
                ev.append((pi,) + e)
        if ev:
            total += 1
            print('HIT', n, len(ev), [(e[0], e[4]) for e in ev][:8])
    print('FILES', total)


main()

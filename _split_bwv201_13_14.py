"""Split BWV_0201_13-14.xml into two separate MusicXML files."""
import copy
import xml.etree.ElementTree as ET

SRC = r'C:\m_a\tobis-notenarchiv.de\cantatas\BWV_0201_13-14.xml'
OUT_13 = r'C:\m_a\tobis-notenarchiv.de\cantatas\BWV_0201_13.xml'
OUT_14 = r'C:\m_a\tobis-notenarchiv.de\cantatas\BWV_0201_14.xml'

SPLIT_MEASURE = 118  # movement 14 starts at measure 118

ET.register_namespace('', 'http://www.w3.org/1999/xhtml')

tree = ET.parse(SRC)
root = tree.getroot()
ns = root.tag.split('}')[0].lstrip('{') if '}' in root.tag else ''

def q(t):
    return ('{' + ns + '}' + t) if ns else t

def make_score(root, measure_range):
    """Return a new score-partwise element with only measures in measure_range."""
    new_root = copy.deepcopy(root)
    parts = new_root.findall(q('part'))
    for part in parts:
        measures = part.findall(q('measure'))
        keep = [m for m in measures if int(m.get('number', 0)) in measure_range]
        # renumber from 1
        for i, m in enumerate(keep, 1):
            m.set('number', str(i))
        # remove all measures, re-add only kept ones
        for m in measures:
            part.remove(m)
        for m in keep:
            part.append(m)
        # ensure first measure has full attributes (clef, key, time)
        # copy from original first measure of this range if needed
    return new_root

# Determine ranges
tree_orig = ET.parse(SRC)
root_orig = tree_orig.getroot()
parts_orig = root_orig.findall(q('part'))
p0 = parts_orig[0]
measures_orig = p0.findall(q('measure'))
all_nums = [int(m.get('number', 0)) for m in measures_orig]
range_13 = set(n for n in all_nums if n < SPLIT_MEASURE)
range_14 = set(n for n in all_nums if n >= SPLIT_MEASURE)

print(f'Movement 13: measures 1-{max(range_13)} ({len(range_13)} measures)')
print(f'Movement 14: measures {min(range_14)}-{max(range_14)} ({len(range_14)} measures)')

# Build two trees
root_13 = make_score(root_orig, range_13)
root_14 = make_score(root_orig, range_14)

# Write
decl = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
doctype = ('<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 2.0 Partwise//EN"'
           ' "http://www.musicxml.org/dtds/partwise.dtd">\n')

for out_path, new_root in [(OUT_13, root_13), (OUT_14, root_14)]:
    tree_out = ET.ElementTree(new_root)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(decl + doctype)
        tree_out.write(f, encoding='unicode', xml_declaration=False)
    print(f'Written: {out_path}')

print('Done.')

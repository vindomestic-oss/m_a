import re

with open('C:/m_a/lilypond/mutopia_bach.html', encoding='utf-8') as f:
    html = f.read()

print('Total size:', len(html))
rows = html.count('<tr>')
print('Table rows:', rows)

# Pagination
pages = re.findall(r'(page=\d+|RFrom=\d+|start=\d+)', html)
print('Pagination refs:', pages[:20])

next_links = re.findall(r'href=["\']([^"\']*make-table[^"\']*)["\']', html)
print('make-table links:', next_links[:10])

# Count BWV refs
bwv = re.findall(r'BWV[\w/]+', html)
bwv_unique = sorted(set(bwv))
print(f'Unique BWV refs: {len(bwv_unique)}')
for b in bwv_unique[:30]:
    print(' ', b)

print()
print('--- Last 500 chars ---')
print(html[-500:])

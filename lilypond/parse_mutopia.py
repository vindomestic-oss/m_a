import re, json

with open('C:/m_a/lilypond/mutopia_bach.html', encoding='utf-8') as f:
    html = f.read()

# Find all .ly links
ly_links = re.findall(r'href=["\']([^"\']*\.ly)["\']', html)
print('LY href links:', len(ly_links))
for l in ly_links[:20]:
    print(' ', l)

print()
# All .ly refs in page
all_ly = re.findall(r'https?://[^\s"\'<>]+\.ly', html)
print('HTTP .ly refs:', len(all_ly))
for l in all_ly[:20]:
    print(' ', l)

print()
# Look at a chunk of HTML to understand structure
idx = html.find('.ly')
if idx > 0:
    print('Context around first .ly:')
    print(html[max(0,idx-200):idx+200])

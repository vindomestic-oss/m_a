import re, urllib.request, ssl, os, zipfile, io

ctx = ssl.create_default_context()

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return r.read().decode('utf-8')

base_url = 'https://www.mutopiaproject.org/cgibin/make-table.cgi'
params = 'searchingfor=&Composer=BachJS&Instrument=&Style=&collection=&id=&solo=&recent=&timelength=&timeunit=&lilyversion=&preview='

# Collect all pages
all_ly_zips = []
all_ly_singles = []

startat = 0
page_num = 0
while True:
    url = f'{base_url}?startat={startat}&{params}'
    print(f'Fetching page (startat={startat})...')
    html = fetch(url)

    ly_zips = re.findall(r'href=["\']([^"\']*-lys\.zip)["\']', html)
    ly_singles_raw = re.findall(r'href=["\']([^"\']*\.ly)["\']', html)

    all_ly_zips.extend(ly_zips)
    all_ly_singles.extend(ly_singles_raw)

    print(f'  Found {len(ly_zips)} zips, {len(ly_singles_raw)} singles on this page')

    # Check for next page link
    next_match = re.search(r'href=["\']make-table\.cgi\?startat=(\d+)[^"\']*["\']', html)
    if not next_match:
        break
    next_start = int(next_match.group(1))
    if next_start <= startat:
        break
    startat = next_start
    page_num += 1

# Deduplicate
all_ly_zips = list(dict.fromkeys(all_ly_zips))
all_ly_singles = list(dict.fromkeys(all_ly_singles))

print(f'\nTotal: {len(all_ly_zips)} zip bundles, {len(all_ly_singles)} single .ly files')

# Build download list: prefer zips
zip_bases = set()
download = []
for z in all_ly_zips:
    base = z.replace('-lys.zip', '')
    zip_bases.add(base)
    download.append(('zip', z))

for s in all_ly_singles:
    base = '/'.join(s.split('/')[:-1])
    if base not in zip_bases:
        download.append(('ly', s))

print(f'Total items to download: {len(download)}')

out_dir = 'C:/m_a/lilypond/bach'
os.makedirs(out_dir, exist_ok=True)

errors = []
for i, (kind, url) in enumerate(download):
    print(f'[{i+1}/{len(download)}] {url.split("/")[-1]}')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            data = r.read()
        if kind == 'zip':
            z = zipfile.ZipFile(io.BytesIO(data))
            ly_files = [n for n in z.namelist() if n.endswith('.ly')]
            z.extractall(out_dir)
            print(f'  -> {len(ly_files)} .ly files')
        else:
            fname = url.split('/')[-1]
            with open(os.path.join(out_dir, fname), 'wb') as f:
                f.write(data)
            print(f'  -> {fname}')
    except Exception as e:
        print(f'  ERROR: {e}')
        errors.append((url, str(e)))

print(f'\nDone. {len(download) - len(errors)} ok, {len(errors)} errors.')
if errors:
    for url, err in errors:
        print(f'  FAIL: {url}: {err}')

ly_count = sum(1 for root, dirs, files in os.walk(out_dir) for f in files if f.endswith('.ly'))
print(f'Total .ly files in {out_dir}: {ly_count}')

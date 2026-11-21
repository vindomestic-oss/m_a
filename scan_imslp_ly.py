"""
Scan IMSLP Bach work pages for LilyPond (.ly) source files.
Uses the MediaWiki API to get all Bach work URLs, then fetches each page
and searches for "Engraving files (Lilypond)" or "Engraving Files (ly)".
"""
import json
import re
import time
import urllib.request
import urllib.parse
import sys
import concurrent.futures
import threading

HEADERS = {'User-Agent': 'Mozilla/5.0 (music analysis research)'}
_rate_lock = threading.Semaphore(5)  # max 5 concurrent requests

def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        return None

def extract_ly_files(page_title, content):
    """Extract LilyPond file info from page HTML content."""
    results = []
    pattern = r'(?i)Engraving [Ff]iles?\s*\((?:Lilypond|ly)\)'
    matches = list(re.finditer(pattern, content))

    for m in matches:
        idx = m.start()
        before = content[max(0, idx-4000):idx]
        after = content[idx:idx+2000]

        # IMSLP file ID - last IMSLP[id] div before the match
        id_matches = list(re.finditer(r'id="IMSLP(\d+)"', before))
        file_id = id_matches[-1].group(1) if id_matches else '?'

        # Direct image URL
        url_m = re.search(r'href="(/images/[^"]+\.(?:zip|ly|LY))"', before[-2000:] + after[:1000])
        file_url = 'https://imslp.org' + url_m.group(1) if url_m else '?'

        # Filename from the URL
        filename = file_url.split('/')[-1] if file_url != '?' else '?'

        # Also try title= attribute for filename
        title_m = re.search(r'title="([^"]+\.(?:zip|ly|LY))"', before[-2000:] + after[:1000])
        if title_m and filename == '?':
            filename = title_m.group(1)

        # Uploader - search wider window; also check before (link appears before format text too)
        user_m = re.search(r'User:([^\"/&<\s"]+)', before[-500:] + after[:2500])
        user = user_m.group(1) if user_m else '?'

        # Upload date
        date_m = re.search(r'\(\s*(\d{4}/\d+/\d+)\s*\)', after[:2500])
        date = date_m.group(1) if date_m else '?'

        # File size
        size_m = re.search(r'(\d+\.\d+)MB', after[:500])
        size = size_m.group(1) + 'MB' if size_m else '?'

        # Edition/description: look for the download text label before format line
        # The label is in the <b><a> link just before "Engraving files"
        label_m = re.search(r'<span[^>]*><span[^>]*>&#160;</span></span>([^<]{3,200})</span>', before[-1000:])
        label = label_m.group(1).strip() if label_m else ''

        # Misc notes - look for "Typeset in LilyPond" or similar in context
        misc_m = re.search(r'Misc\.\s*Notes.*?</td>', before[-2000:] + after[:2000], re.DOTALL)
        misc = ''
        if misc_m:
            misc_text = re.sub(r'<[^>]+>', '', misc_m.group(0))
            misc = misc_text.strip()[:200]

        results.append({
            'work': page_title,
            'imslp_id': file_id,
            'filename': filename,
            'file_url': file_url,
            'label': label,
            'uploader': user,
            'date': date,
            'size': size,
            'misc': misc,
            'format_text': m.group(0).strip(),
        })

    return results

def scan_page(work):
    title = work['title']
    url_title = title.replace(' ', '_')
    url = f'https://imslp.org/wiki/{urllib.parse.quote(url_title, safe="/:()_,.-")}'

    with _rate_lock:
        content = fetch(url, timeout=20)
        time.sleep(0.15)  # polite delay

    if content is None:
        return title, None, 'fetch_error'

    if not re.search(r'(?i)Engraving [Ff]iles?\s*\((?:Lilypond|ly)\)', content):
        return title, [], 'ok'

    ly_files = extract_ly_files(title, content)
    return title, ly_files, 'ok'

def main():
    print("Loading Bach works list from saved JSON...", file=sys.stderr)
    with open('C:/m_a/bach_works.json', encoding='utf-8', errors='replace') as f:
        works = json.load(f)
    print(f"Loaded {len(works)} works", file=sys.stderr)

    all_ly = []
    errors = []
    done = [0]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(scan_page, w): w for w in works}
        for future in concurrent.futures.as_completed(futures):
            title, ly_files, status = future.result()
            done[0] += 1

            if done[0] % 100 == 0:
                print(f"Progress: {done[0]}/{len(works)} ({len(all_ly)} LilyPond files so far)", file=sys.stderr)

            if status == 'fetch_error':
                errors.append(title)
            elif ly_files:
                print(f"  FOUND {len(ly_files)} in: {title}", file=sys.stderr)
                all_ly.extend(ly_files)

    print(f"\nTotal LilyPond files found: {len(all_ly)}", file=sys.stderr)
    print(f"Errors: {len(errors)}", file=sys.stderr)

    with open('C:/m_a/imslp_bach_ly_files.json', 'w', encoding='utf-8') as f:
        json.dump(all_ly, f, indent=2, ensure_ascii=False)

    # Print report to stdout
    print("\n" + "="*80)
    print("BACH LilyPond FILES ON IMSLP")
    print("="*80 + "\n")

    # Sort by work title
    all_ly.sort(key=lambda x: x['work'])

    for entry in all_ly:
        print(f"Work:      {entry['work']}")
        print(f"IMSLP#:    {entry['imslp_id']}")
        print(f"Format:    {entry['format_text']}")
        if entry['label']:
            print(f"Label:     {entry['label']}")
        print(f"Filename:  {entry['filename']}")
        print(f"URL:       {entry['file_url']}")
        print(f"Uploader:  {entry['uploader']}")
        print(f"Date:      {entry['date']}")
        print(f"Size:      {entry['size']}")
        if entry['misc']:
            print(f"Misc:      {entry['misc']}")
        print()

    if errors:
        print(f"\nFailed to fetch {len(errors)} pages:")
        for e in errors[:20]:
            print(f"  - {e}")

if __name__ == '__main__':
    main()

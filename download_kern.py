#!/usr/bin/env python3
"""Download all Bach Johann kern files from kern.humdrum.org."""

import re
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

SEARCH_URL = "https://kern.humdrum.org/search?s=t&keyword=Bach+Johann"
BASE_URL = "https://kern.humdrum.org/cgi-bin/ksdata?location={location}&file={file}&format=kern"
OUT_DIR = os.path.join(os.path.dirname(__file__), "kern")

def fetch_url(url, retries=3, delay=2):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise e

def get_entries():
    print("Fetching search results...")
    html = fetch_url(SEARCH_URL).decode("utf-8", errors="replace")
    pattern = re.compile(r'location=([^&]+)&file=([^&]+\.krn)')
    entries = list(dict.fromkeys(pattern.findall(html)))  # deduplicate preserving order
    print(f"Found {len(entries)} unique kern files.")
    return entries

def download_entry(location, filename):
    url = BASE_URL.format(location=location, file=filename)
    # Mirror directory structure
    dest_dir = os.path.join(OUT_DIR, location)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)
    if os.path.exists(dest_path):
        return dest_path, "skip"
    data = fetch_url(url)
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_path, "ok"

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    entries = get_entries()
    total = len(entries)
    done = 0
    errors = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download_entry, loc, fn): (loc, fn) for loc, fn in entries}
        for future in as_completed(futures):
            loc, fn = futures[future]
            done += 1
            try:
                path, status = future.result()
                tag = "[skip]" if status == "skip" else "[ok]  "
                print(f"  {tag} ({done}/{total}) {loc}/{fn}")
            except Exception as e:
                errors.append((loc, fn, str(e)))
                print(f"  [ERR] ({done}/{total}) {loc}/{fn} => {e}", file=sys.stderr)

    print(f"\nDone. {total - len(errors)} downloaded/skipped, {len(errors)} errors.")
    if errors:
        print("\nFailed files:")
        for loc, fn, err in errors:
            print(f"  {loc}/{fn}: {err}")

if __name__ == "__main__":
    main()

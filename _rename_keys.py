"""Append the German key name (c_dur, cis_moll, des_dur ...) to the file names of
WTC preludes/fugues (kern), inventions (kern) and sinfonias (lilypond xml + ly).

  python _rename_keys.py            dry run: print the plan and every disagreement
  python _rename_keys.py --apply    rename (git mv for tracked files)

The key comes from the file itself (kern tonality interpretation `*E-:` or, failing that, key
signature + mode from the BWV table below); the table is only used to check / to supply the mode.
"""
import os, re, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
# mode per piece: (WTC1 prelude, WTC1 fugue, WTC2 prelude, WTC2 fugue) = same mode for both; 'M'/'m'
WTC_MODE = 'MmMmMmMmMmMmMmMmMmmMMmMm'            # placeholder, replaced below
# index 0..23 -> expected (tonic, mode) per piece n=1..24 (German spelling by the usual titles)
WTC1 = ['c M', 'c m', 'cis M', 'cis m', 'd M', 'd m', 'es M', 'es m', 'e M', 'e m', 'f M', 'f m',
        'fis M', 'fis m', 'g M', 'g m', 'as M', 'gis m', 'a M', 'a m', 'b M', 'b m', 'h M', 'h m']
WTC1_FUGUE_OVERRIDE = {8: 'dis m'}                # fugue 8 is in D-sharp minor, its prelude in E-flat minor
WTC2 = ['c M', 'c m', 'cis M', 'cis m', 'd M', 'd m', 'es M', 'dis m', 'e M', 'e m', 'f M', 'f m',
        'fis M', 'fis m', 'g M', 'g m', 'as M', 'gis m', 'a M', 'a m', 'b M', 'b m', 'h M', 'h m']
INVENTIONS = ['c M', 'c m', 'd M', 'd m', 'es M', 'e M', 'e m', 'f M', 'f m', 'g M', 'g m', 'a M', 'a m', 'b M', 'h m']
SINFONIAS = ['c M', 'c m', 'd M', 'd m', 'es M', 'e M', 'e m', 'f M', 'f m', 'g M', 'g m', 'a M', 'a m', 'b M', 'h m']

# circle of fifths -> tonic name (German), per mode
MAJOR = {-7: 'ces', -6: 'ges', -5: 'des', -4: 'as', -3: 'es', -2: 'b', -1: 'f', 0: 'c', 1: 'g', 2: 'd',
         3: 'a', 4: 'e', 5: 'h', 6: 'fis', 7: 'cis'}
MINOR = {-7: 'as', -6: 'es', -5: 'b', -4: 'f', -3: 'c', -2: 'g', -1: 'd', 0: 'a', 1: 'e', 2: 'h',
         3: 'fis', 4: 'cis', 5: 'gis', 6: 'dis', 7: 'ais'}


def german_tonic(letter, acc):
    letter = letter.upper()
    if letter == 'B':
        return {'': 'h', '-': 'b', '#': 'his'}[acc]
    base = letter.lower()
    if acc == '':
        return base
    if acc == '#':
        return base + 'is'
    if acc == '-':
        return {'E': 'es', 'A': 'as'}.get(letter, base + 'es')
    raise ValueError(acc)


def kern_key(path):
    """-> (tonic, 'M'|'m', fifths|None) from the kern interpretations"""
    fifths = None
    tonic = None
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.startswith('*'):
                continue
            for tok in line.rstrip('\n').split('\t'):
                m = re.match(r'^\*k\[(.*)\]$', tok)
                if m and fifths is None:
                    acc = re.findall(r'[a-g][#-]', m.group(1))
                    n = len(acc)
                    fifths = n if (acc and acc[0][1] == '#') else -n if acc else 0
                m = re.match(r'^\*([A-Ga-g])([#-]*):$', tok)
                if m and tonic is None:
                    tonic = (german_tonic(m.group(1), m.group(2)), 'M' if m.group(1).isupper() else 'm')
            if fifths is not None and tonic is not None:
                break
    return tonic, fifths


def xml_key(path):
    s = open(path, encoding='utf-8', errors='replace').read(400000)
    m = re.search(r'<fifths>(-?\d+)</fifths>', s)
    md = re.search(r'<mode>(\w+)</mode>', s)
    fifths = int(m.group(1)) if m else None
    mode = {'major': 'M', 'minor': 'm'}.get(md.group(1)) if md else None
    return fifths, mode


def plan():
    rows = []      # (old_path, new_path, expected, got, note)
    for set_, d_pre, d_fug, tbl_p, tbl_f in (
            (1, r'kern\musedata\bach\keyboard\wtc-1', r'kern\osu\classical\bach\wtc-1', WTC1,
             {**{i + 1: t for i, t in enumerate(WTC1)}, **WTC1_FUGUE_OVERRIDE}),
            (2, r'kern\musedata\bach\keyboard\wtc-2', r'kern\osu\classical\bach\wtc-2', WTC2,
             {i + 1: t for i, t in enumerate(WTC2)})):
        for kind, d in (('p', d_pre), ('f', d_fug)):
            for fn in sorted(os.listdir(os.path.join(ROOT, d))):
                m = re.match(r'^wtc%d%s(\d\d)\.krn$' % (set_, kind), fn)
                if not m:
                    continue
                n = int(m.group(1))
                exp = (tbl_p[n - 1] if kind == 'p' else tbl_f[n]).split()
                p = os.path.join(ROOT, d, fn)
                tonic, fifths = kern_key(p)
                name = None
                note = ''
                if tonic:
                    name = tonic
                    if tonic[0] != exp[0] or tonic[1] != exp[1]:
                        note = 'kern says %s %s, table %s %s' % (tonic[0], tonic[1], exp[0], exp[1])
                elif fifths is not None:
                    tbl = MAJOR if exp[1] == 'M' else MINOR
                    name = (tbl[fifths], exp[1])
                    note = 'no *X: tonality; from signature %+d + table mode' % fifths
                    if name[0] != exp[0]:
                        note += ' (table says %s)' % exp[0]
                if name is None:
                    name = (exp[0], exp[1])
                    note = 'no key info in the file; table'
                new = fn[:-4] + '_%s_%s.krn' % (name[0], 'dur' if name[1] == 'M' else 'moll')
                rows.append((os.path.join(d, fn), os.path.join(d, new), exp, name, note))
    d = r'kern\osu\classical\bach\inventions'
    for fn in sorted(os.listdir(os.path.join(ROOT, d))):
        m = re.match(r'^inven(\d\d)\.krn$', fn)
        if not m:
            continue
        n = int(m.group(1))
        exp = INVENTIONS[n - 1].split()
        tonic, fifths = kern_key(os.path.join(ROOT, d, fn))
        name = tonic or ((MAJOR if exp[1] == 'M' else MINOR)[fifths if fifths is not None else 0], exp[1])
        note = '' if (name[0] == exp[0] and name[1] == exp[1]) else 'file %s %s, table %s %s' % (name + tuple(exp))
        rows.append((os.path.join(d, fn), os.path.join(d, fn[:-4] + '_%s_%s.krn' % (name[0], 'dur' if name[1] == 'M' else 'moll')),
                     exp, name, note))
    d = r'lilypond\musicxml'
    for k in range(15):
        fn = 'bwv%d.xml' % (787 + k)
        exp = SINFONIAS[k].split()
        p = os.path.join(ROOT, d, fn)
        if not os.path.exists(p):
            continue
        fifths, mode = xml_key(p)
        mode = mode or exp[1]
        name = ((MAJOR if mode == 'M' else MINOR)[fifths], mode) if fifths is not None else (exp[0], exp[1])
        note = '' if (name[0] == exp[0] and name[1] == exp[1]) else 'file %s %s, table %s %s' % (name + tuple(exp))
        base = fn[:-4] + '_%s_%s' % (name[0], 'dur' if name[1] == 'M' else 'moll')
        rows.append((os.path.join(d, fn), os.path.join(d, base + '.xml'), exp, name, note))
        ly = os.path.join(r'lilypond\bach', fn[:-4] + '.ly')
        if os.path.exists(os.path.join(ROOT, ly)):
            rows.append((ly, os.path.join(r'lilypond\bach', base + '.ly'), exp, name, note))
    return rows


def main():
    apply = '--apply' in sys.argv
    rows = plan()
    bad = [r for r in rows if r[4]]
    print('files to rename:', len(rows), ' notes/disagreements:', len(bad))
    for r in bad:
        print('  !', r[0], '->', os.path.basename(r[1]), '|', r[4])
    if not apply:
        for r in rows[:6] + rows[48:52] + rows[-8:]:
            print('   ', r[0], '->', os.path.basename(r[1]))
        return
    for old, new, *_ in rows:
        o, n = os.path.join(ROOT, old), os.path.join(ROOT, new)
        assert os.path.exists(o) and not os.path.exists(n), (old, new)
        tracked = subprocess.run(['git', '-C', ROOT, 'ls-files', '--error-unmatch', old.replace('\\', '/')],
                                 capture_output=True).returncode == 0
        if tracked:
            subprocess.run(['git', '-C', ROOT, 'mv', old.replace('\\', '/'), new.replace('\\', '/')], check=True)
        else:
            os.rename(o, n)
    print('renamed', len(rows))


if __name__ == '__main__':
    main()

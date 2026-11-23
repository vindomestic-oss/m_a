"""Check letter examples of motif_rules_examples.txt.  Letters = NOTES (scale degrees, a<b<c<...),
space = rest up to the next beat, '|' separates voices.  Every note is a 16th.
Usage: python motif_examples_check.py "abc abc|abc abc" ..."""
import sys
sys.path.insert(0, r'C:\m_a')
import kern_reader as kr
from reader import motif_analysis as ma
STEP_NAME = {v: k for k, v in ma._DIATONIC_STEP.items()}
BASE = 28
def build(spec, dur=0.25):
    notes = []; t = 0.0
    for k, ch in enumerate(spec):
        if ch == ' ':
            t = int(t + 1e-9) + 1.0 if (t - int(t + 1e-9)) > 1e-9 else t + 1.0
            continue
        dp = BASE + (ord(ch) - ord('a'))
        notes.append((f'{ch}{k}', STEP_NAME[dp % 7], dp // 7, dur, 0, t)); t += dur
    return notes
def letters_of(nids): return ''.join(n[0] for n in nids)
def shape(nids_first, name_of):
    return ''
def run(spec, min_count=2):
    voices = spec.split('|')
    nmap = {}
    all_seqs = []
    for i, s in enumerate(voices):
        notes = [(f'v{i}_{n[0]}',) + n[1:] for n in build(s)]
        for n in notes: nmap[n[0]] = n[0].split('_')[1].rstrip('0123456789')
        all_seqs.append((f'v{i}', ma._interval_seq(notes, 1.0, 0.0)))
    ms = ma._find_motifs(all_seqs, min_count=min_count, beat_dur_q=1.0, pickup_dur_q=0.0)
    res = []
    for m in ms:
        iv = ''.join(f'{d:+d}' for d, _ in [(p[0], p[1]) for p in m['pattern']])
        first = m['occurrences'][0]
        notes = ''.join(nmap[n] for n in first)
        res.append(f"{notes:<10} shape {iv:<14} phase{m['phase']} n={len(m['occurrences'])} (dir {m['n_direct_only']} inv {m['n_inv_only']} both {m['n_both']})")
    return res
if __name__ == '__main__':
    for s in sys.argv[1:]:
        print(repr(s)); [print('   ', o) for o in run(s)]

"""Check letter examples of motif_rules_examples.txt.  Letters = INTERVALS (a=+1 ... j=+10, capital = negative,
'0' = unison), space = rest up to the next beat, '|' separates voices.  Every note is a 16th.
Usage: python motif_examples_check.py "abc abc|abc abc" ..."""
import sys
sys.path.insert(0, r'C:\m_a')
import kern_reader as kr
from reader import motif_analysis as ma
VAL = {c: i + 1 for i, c in enumerate('abcdefghij')}   # a=1 .. j=10 ; ' ' = 11 across a rest
STEP_NAME = {v: k for k, v in ma._DIATONIC_STEP.items()}
def val(ch):
    if ch == ' ': return 11
    if ch == '0': return 0
    return VAL[ch] if ch.islower() else -VAL[ch.lower()]
def letter(iv):
    if iv == 11: return ' '
    if iv == 0: return '0'
    return [k for k, v in VAL.items() if v == abs(iv)][0] if iv > 0 else [k for k, v in VAL.items() if v == abs(iv)][0].upper()
def build(spec, dur=0.25, start_dp=28, onset0=0.0):
    notes = []; dp = start_dp; t = onset0
    notes.append(('n0', STEP_NAME[dp % 7], dp // 7, dur, 0, t)); t += dur
    for k, ch in enumerate(spec):
        if ch == ' ': t = int(t + 1e-9) + 1.0          # rest up to the next beat
        dp += val(ch)
        notes.append((f'n{k+1}', STEP_NAME[dp % 7], dp // 7, dur, 0, t)); t += dur
    return notes
def run(specs, min_count=2):
    if isinstance(specs, str): specs = [specs]
    all_seqs = [(f'v{i}', ma._interval_seq(build(s, onset0=0.0), 1.0, 0.0)) for i, s in enumerate(specs)]
    ms = ma._find_motifs(all_seqs, min_count=min_count, beat_dur_q=1.0, pickup_dur_q=0.0)
    out = []
    for m in ms:
        pat = ''.join(letter(iv) for iv, d in m['pattern'])
        out.append(f"{pat!r} phase{m['phase']} n={len(m['occurrences'])} (dir {m['n_direct_only']} inv {m['n_inv_only']} both {m['n_both']})")
    return out
if __name__ == '__main__':
    for s in sys.argv[1:]:
        print(repr(s)); [print('   ', o) for o in run(s.split('|'))]

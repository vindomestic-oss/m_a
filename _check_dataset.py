import json
from collections import Counter

records = [json.loads(l) for l in open('train_data.jsonl', encoding='utf-8')]
print(f'Files: {len(records)}')

pitches, durs, phases, mtypes, poss, dp0s, dists, verts = (set() for _ in range(8))
n_note = n_motif = 0

for rec in records:
    for t in rec['tokens']:
        if t['t'] == 'N':
            n_note += 1
            pitches.add(t['p'])
            durs.add(t['d'])
            phases.add(t.get('ph', 0))
            m = t.get('m')
            if m:
                mtypes.add(m[0])
                poss.add(m[1])
                dp0s.add(m[2])
            for v in t.get('v', []):
                verts.add(v)
        else:
            n_motif += 1
            mtypes.add(t['id'])
            dp0s.add(t.get('dp0', 0))
            dists.add(t.get('dist', 0))

print(f'Note tokens: {n_note}  Motif tokens: {n_motif}')
print(f'Pitch range:   {min(pitches)}-{max(pitches)}  ({len(pitches)} unique)')
print(f'Dur range:     {min(durs)}-{max(durs)}  ({len(durs)} unique values: {sorted(durs)})')
print(f'Phase range:   {min(phases)}-{max(phases)}')
print(f'Motif types:   {len(mtypes)} unique, max={max(mtypes)}')
print(f'Pos in motif:  max={max(poss) if poss else 0}')
print(f'dp0 range:     {min(dp0s)}-{max(dp0s)}')
print(f'Dist range:    {min(dists)}-{max(dists)}')
print(f'Vert ivs:      {sorted(verts)}')

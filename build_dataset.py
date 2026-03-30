#!/usr/bin/env python3
"""
Build training dataset from Bach kern corpus.

For each file:
  - runs _voice_notes_from_mei + _find_motifs (same pipeline as kern_mdl)
  - annotates every note with motif membership, metric phase, vertical intervals
  - inserts MOTIF_START tokens before each motif occurrence
  - writes one JSON line per file to train_data.jsonl

Token types:
  {"t":"N", "p":int, "d":int, "o":int, "ph":int,
   "m":[type_id, pos, dp0_rel, is_inv] or null, "v":[int,...]}
  {"t":"M", "id":int, "dp0":int, "inv":0|1, "o":int, "dist":int}

  p   = diatonic pitch  oct*7 + step  (C=0,D=1,...,B=6)
  d   = duration in 16ths  (round(dur_q * 4))
  o   = onset in 16ths from piece start
  ph  = metric phase
  m   = [vocab_type_id, pos_in_motif, dp0_relative_to_ref, is_inv(0/1)]
  v   = sorted diatonic intervals from lowest sounding note at note onset
  id  = vocab_type_id
  dp0 = diatonic pitch of first note
  inv = inversion flag
  dist= distance in 16ths from previous occurrence of same motif type

Usage:
  python build_dataset.py
  python build_dataset.py --filter bach/keyboard
  python build_dataset.py --output my_data.jsonl
"""

import argparse
import json
import multiprocessing
import os
import sys

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
VOCAB_PATH = os.path.join(BASE_DIR, 'motif_vocab.json')
OUT_PATH   = os.path.join(BASE_DIR, 'train_data.jsonl')
_TIMEOUT   = 90

sys.path.insert(0, BASE_DIR)
import kern_mdl as kr


# ── vocabulary loading ────────────────────────────────────────────────────────

def load_vocab(path):
    """Return {body_key: type_id} where body_key = tuple of (iv,dur) pairs."""
    entries = json.load(open(path, encoding='utf-8'))
    vocab = {}
    for e in entries:
        key = tuple(tuple(s) for s in e['body'])
        vocab[(key, e['phase'])] = e['id']
    return vocab


# ── vertical intervals ────────────────────────────────────────────────────────

def _vertical_intervals(voices_dict):
    """
    For each note, find diatonic intervals from the lowest sounding note
    at the moment of its onset.
    Returns {nid: (int, ...) } — sorted tuple of intervals (bass=0 excluded).
    """
    # build flat list: (onset_q, end_q, dp, nid)
    all_notes = []
    for notes in voices_dict.values():
        for nid, pname, oct_int, dur_q, midi_val, onset_q in notes:
            dp = oct_int * 7 + kr._DIATONIC_STEP.get(pname.lower(), 0)
            all_notes.append((onset_q, onset_q + dur_q, dp, nid))

    # for each note find all simultaneously sounding notes
    result = {}
    for onset_q, end_q, dp, nid in all_notes:
        sounding = [n[2] for n in all_notes
                    if n[0] <= onset_q < n[1]]   # n.onset <= this.onset < n.end
        if len(sounding) < 2:
            result[nid] = ()
            continue
        bass = min(sounding)
        ivs  = sorted(set(s - bass for s in sounding if s != bass))
        result[nid] = tuple(ivs)

    return result


# ── subprocess worker ─────────────────────────────────────────────────────────

def _worker_func(path, vocab_path, q):
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        import kern_mdl as _kr

        # load vocab in subprocess
        _vocab = {}
        for e in json.loads(open(vocab_path, encoding='utf-8').read()):
            key = (tuple(tuple(s) for s in e['body']), e['phase'])
            _vocab[key] = e['id']

        _kr.check_file(path)
        ext = path.rsplit('.', 1)[-1].lower()

        if ext == 'mxl':
            import zipfile as _zf
            with _zf.ZipFile(path) as z:
                xml_name = next(
                    n for n in z.namelist()
                    if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n
                )
                raw = z.read(xml_name)
                content = (raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff')
                           else raw.decode('utf-8-sig') if raw[:3] == b'\xef\xbb\xbf'
                           else raw.decode('utf-8', errors='replace'))
        elif ext in ('xml', 'musicxml'):
            with open(path, 'rb') as f:
                raw = f.read()
            content = (raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff')
                       else raw.decode('utf-8-sig') if raw[:3] == b'\xef\xbb\xbf'
                       else raw.decode('utf-8', errors='replace'))
        else:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

        if ext == 'krn':
            content = _kr.prepare_grand_staff(content)
            content = _kr.add_beam_markers(content)

        _kr._vtk.setOptions({
            'pageWidth': 2200, 'adjustPageHeight': True,
            'scale': 35, 'font': 'Leipzig',
        })
        if not _kr._vtk.loadData(content):
            q.put(None); return

        mei_str = _kr._vtk.getMEI()
        voices, beat_dur_q = _kr._voice_notes_from_mei(mei_str)

        # ── vertical intervals ────────────────────────────────────────────────
        # build dp map and vertical intervals
        nid_dp     = {}   # nid → diatonic pitch
        nid_onset  = {}   # nid → onset in 16ths (int)
        nid_end    = {}   # nid → end in 16ths (int)
        nid_phase  = {}   # nid → metric phase
        nid_dur16  = {}   # nid → duration in 16ths
        all_flat   = []

        for notes in voices.values():
            for nid, pname, oct_int, dur_q, _midi, onset_q in notes:
                dp     = oct_int * 7 + _kr._DIATONIC_STEP.get(pname.lower(), 0)
                o16    = round(onset_q * 4)
                d16    = max(1, round(dur_q * 4))
                phase  = _kr._metric_phase(onset_q, dur_q, beat_dur_q)
                nid_dp[nid]    = dp
                nid_onset[nid] = o16
                nid_end[nid]   = o16 + d16
                nid_dur16[nid] = d16
                nid_phase[nid] = phase
                all_flat.append((o16, o16 + d16, dp, nid))

        # vertical intervals per note
        vert = {}
        for o16, e16, dp, nid in all_flat:
            sounding = [n[2] for n in all_flat if n[0] <= o16 < n[1]]
            if len(sounding) < 2:
                vert[nid] = []
            else:
                bass = min(sounding)
                vert[nid] = sorted(set(s - bass for s in sounding if s != bass))

        # ── motif analysis ────────────────────────────────────────────────────
        all_seqs   = [(vk, _kr._interval_seq(notes, beat_dur_q))
                      for vk, notes in voices.items() if len(notes) >= 4]
        raw_motifs = _kr._find_motifs(all_seqs)

        # nid → motif annotation: [type_id, pos_in_motif, dp0_rel, is_inv]
        nid_motif = {}
        # track last onset per type for dist computation
        last_onset_by_type = {}
        # collect motif events: (onset_16, type_id, dp0, inv, dist, nids)
        motif_events = []

        for m in raw_motifs:
            body  = m['pattern']
            phase = m.get('phase', 0)
            key   = (body, phase)
            type_id = _vocab.get(key)
            if type_id is None:
                continue

            for t in m['transforms']:
                inv    = 1 if t['inversion'] else 0
                oq     = t['onset_q']
                o16    = round(oq)
                dp0    = t.get('transposition', 0)   # relative to ref_pitch
                dist   = 0
                if type_id in last_onset_by_type:
                    dist = o16 - last_onset_by_type[type_id]
                last_onset_by_type[type_id] = o16
                motif_events.append((o16, type_id, dp0, inv, dist))

            # use transforms + occurrences (dedup_occs = list of nid lists)
            dedup_occs = m.get('occurrences', [])
            for occ_nids, t in zip(dedup_occs, m['transforms']):
                inv = 1 if t['inversion'] else 0
                for pos, nid in enumerate(occ_nids):
                    nid_motif[nid] = [type_id, pos, t['transposition'], inv]

        # ── build token list ─────────────────────────────────────────────────
        # assign stable voice indices sorted by (staff, layer)
        voice_keys   = sorted(voices.keys())
        voice_id_map = {k: min(i, 3) for i, k in enumerate(voice_keys)}

        note_tokens  = []
        for vk, notes in voices.items():
            vid = voice_id_map[vk]
            for nid, pname, oct_int, dur_q, _midi, onset_q in notes:
                dp   = nid_dp[nid]
                o16  = nid_onset[nid]
                d16  = nid_dur16[nid]
                ph   = nid_phase[nid]
                note_tokens.append({
                    't':    'N',
                    'p':    dp,
                    'd':    d16,
                    'o':    o16,
                    'ph':   ph,
                    'voice': vid,
                    'm':    nid_motif.get(nid),
                    'v':    vert.get(nid, []),
                })

        motif_tokens = []
        for o16, type_id, dp0, inv, dist in motif_events:
            motif_tokens.append({
                't':    'M',
                'id':   type_id,
                'dp0':  dp0,
                'inv':  inv,
                'o':    o16,
                'dist': dist,
            })

        # sort: motif_start token before notes at same onset
        all_tokens = sorted(
            note_tokens + motif_tokens,
            key=lambda x: (x['o'], 0 if x['t'] == 'M' else 1)
        )

        # ── onset_delta: time gap from previous token in stream ───────────────
        prev_o = 0
        for tok in all_tokens:
            tok['od'] = tok['o'] - prev_o
            prev_o    = tok['o']

        # ── interval: pitch delta from previous note in the same voice ────────
        last_dp = {}   # voice_id -> last absolute dp
        for tok in all_tokens:
            if tok['t'] == 'N':
                vid = tok['voice']
                dp  = tok['p']
                tok['iv'] = max(-14, min(14, dp - last_dp[vid])) if vid in last_dp else 0
                last_dp[vid] = dp

        q.put(all_tokens)

    except Exception as e:
        import traceback
        q.put(('error', traceback.format_exc()))


def _process_file(ctx, path, vocab_path):
    q = ctx.Queue()
    p = ctx.Process(target=_worker_func, args=(path, vocab_path, q))
    p.start()
    try:
        result = q.get(timeout=_TIMEOUT)
    except Exception:
        result = None
    p.join(timeout=5)
    if p.is_alive():
        p.terminate(); p.join()
    return result


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--filter', default=None,
                        help='Only files whose rel path contains substring')
    parser.add_argument('--output', default=OUT_PATH)
    args = parser.parse_args()

    if not os.path.exists(VOCAB_PATH):
        print(f"ERROR: {VOCAB_PATH} not found. Run build_vocab.py first.")
        sys.exit(1)

    all_files = kr.find_kern_files(kr.KERN_DIR)

    # add LilyPond-derived MusicXML files
    ly_xml_dir = os.path.join(os.path.dirname(__file__), 'lilypond', 'musicxml')
    if os.path.isdir(ly_xml_dir):
        for fname in sorted(os.listdir(ly_xml_dir)):
            if fname.endswith('.xml'):
                full = os.path.join(ly_xml_dir, fname)
                all_files.append((f'lilypond/{fname}', full))

    if args.filter:
        terms = [t.strip().lower() for t in args.filter.split(',')]
        all_files = [(r, f) for r, f in all_files
                     if any(t in r.lower() for t in terms)]

    total = len(all_files)
    print(f"Building dataset from {total} files -> {args.output}")

    ctx  = multiprocessing.get_context('spawn')
    ok   = err = 0

    with open(args.output, 'w', encoding='utf-8') as out:
        for idx, (rel, full) in enumerate(all_files):
            if (idx + 1) % 10 == 0 or idx == 0:
                print(f"  {idx+1}/{total}  {rel}", flush=True)

            tokens = _process_file(ctx, full, VOCAB_PATH)
            if tokens is None or (isinstance(tokens, tuple) and tokens[0] == 'error'):
                if isinstance(tokens, tuple):
                    print(f"  ERROR {rel}: {tokens[1].splitlines()[-1]}", flush=True)
                err += 1
                continue

            record = {'file': rel, 'n_tokens': len(tokens), 'tokens': tokens}
            out.write(json.dumps(record, separators=(',', ':')) + '\n')
            ok += 1

    print(f"\nDone. OK={ok}  errors={err}")
    print(f"Dataset: {args.output}")

    # quick stats
    total_tokens = sum(
        json.loads(line)['n_tokens']
        for line in open(args.output, encoding='utf-8')
    )
    motif_tokens = sum(
        sum(1 for t in json.loads(line)['tokens'] if t['t'] == 'M')
        for line in open(args.output, encoding='utf-8')
    )
    print(f"Total tokens: {total_tokens}  "
          f"(note={total_tokens-motif_tokens}, motif={motif_tokens})")


if __name__ == '__main__':
    main()

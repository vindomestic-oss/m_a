#!/usr/bin/env python3
"""
Generate multi-voice music using the trained motif-aware model.

The model generates a single interleaved token stream (exactly like training data).
onset_delta=0 means the next note is simultaneous → different voice.
After generation, notes are separated into voices using greedy voice assignment.

Usage:
  python generate.py                          # 2 voices, WTC prelude seed
  python generate.py --seed-name inven01      # seed from Invention 1
  python generate.py --n 300 --temp 0.9
  python generate.py --voices 1               # monophonic
  python generate.py --list-seeds             # show available seed pieces
"""

import argparse
import json
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from train import (
    MusicModel, encode_piece,
    PITCH_VOCAB, DUR_VOCAB, PHASE_VOCAB, TYPE_VOCAB,
    INTERVAL_VOCAB, VOICE_VOCAB, OD_VOCAB,
    D_MODEL, N_LAYERS, MAX_SEQ,
    _OD_BREAKS, _od_bucket,
)

CKPT_DIR    = BASE_DIR / 'checkpoints'
MEASURE_DUR = 16   # 4/4: 16 sixteenths per measure
BEAT_DUR_16 = 4

_STEP_NAMES = ['c', 'd', 'e', 'f', 'g', 'a', 'b']
_DUR_TABLE  = {1:'16', 2:'8', 3:'8.', 4:'4', 6:'4.',
               8:'2', 12:'2.', 16:'1', 24:'1.', 32:'0', 48:'0.'}


# ── helpers ───────────────────────────────────────────────────────────────────

def dp_to_kern_pitch(dp: int) -> str:
    step = dp % 7
    oct  = dp // 7
    name = _STEP_NAMES[step]
    return name * (oct - 3) if oct >= 4 else name.upper() * (4 - oct)


def dur16_to_kern(d16: int) -> str:
    return _DUR_TABLE.get(d16, _DUR_TABLE[min(_DUR_TABLE, key=lambda x: abs(x - d16))])


def _phase(onset_16: int, dur_16: int) -> int:
    if dur_16 <= 0:
        return 0
    n = max(1, round(BEAT_DUR_16 / dur_16))
    return min(round((onset_16 % BEAT_DUR_16) / dur_16) % n, PHASE_VOCAB - 1)


def sample_top_k(logits: torch.Tensor, top_k: int, temperature: float) -> int:
    logits = logits / max(temperature, 1e-8)
    if 0 < top_k < logits.size(-1):
        vals, idx = torch.topk(logits, top_k)
        return idx[torch.multinomial(F.softmax(vals, dim=-1), 1).item()].item()
    return torch.multinomial(F.softmax(logits, dim=-1), 1).item()


# ── batch builder ─────────────────────────────────────────────────────────────

def _make_batch(tokens: list, device) -> dict:
    if not tokens:
        tokens = [{'t':'N','p':28,'d':4,'ph':0,'iv':0,'voice':0,'od':0,'m':None,'v':[]}]
    enc   = encode_piece(tokens)
    n     = len(enc['tok_type'])
    start = max(0, n - MAX_SEQ)
    L     = MAX_SEQ

    def grab(key, pad=0):
        arr = enc[key][start: start + L]
        if len(arr) < L:
            arr = arr + [pad] * (L - len(arr))
        return torch.tensor(arr, dtype=torch.long)

    vert_raw = enc['vert'][start: start + L]
    vert_t   = torch.zeros(L, 6, dtype=torch.long)
    for i, iv_list in enumerate(vert_raw[:L]):
        for j, v in enumerate(iv_list[:6]):
            vert_t[i, j] = v

    batch = {
        'tok_type': grab('tok_type'),
        'pitch':    grab('pitch'),
        'dur':      grab('dur'),
        'phase':    grab('phase'),
        'mtype':    grab('mtype', pad=TYPE_VOCAB - 1),
        'mpos':     grab('mpos'),
        'mdp0':     grab('mdp0', pad=25),
        'minv':     grab('minv'),
        'vert':     vert_t,
        'motif_id': grab('motif_id'),
        'dist':     grab('dist'),
        'iv':       grab('iv',    pad=14),
        'voice':    grab('voice'),
        'od':       grab('od'),
    }
    return {k: v.unsqueeze(0).to(device) for k, v in batch.items()}


# ── voice state for generation ────────────────────────────────────────────────

class VoiceTracker:
    """Tracks per-voice last pitch and end time for greedy voice assignment."""

    def __init__(self, n_voices: int = 4):
        self.n_voices    = n_voices
        self.last_pitch  = {}   # voice_id → last absolute dp
        self.end_time    = {}   # voice_id → when note ends (onset + dur)

    def assign(self, onset: int) -> int:
        """Return voice_id for a note starting at onset (greedy: first free voice)."""
        for vid in range(self.n_voices):
            if self.end_time.get(vid, 0) <= onset:
                return vid
        return self.n_voices - 1   # all busy: reuse last voice

    def update(self, vid: int, pitch: int, onset: int, dur: int):
        self.last_pitch[vid] = pitch
        self.end_time[vid]   = onset + dur

    def get_pitch(self, vid: int, default: int = 28) -> int:
        return self.last_pitch.get(vid, default)


# ── generation loop ───────────────────────────────────────────────────────────

def generate(model, seed_tokens: list, n_new: int,
             temperature: float = 1.0, top_k: int = 50,
             n_voices: int = 2, device: str = 'cpu') -> list:
    """
    Generate n_new tokens as an interleaved multi-voice stream.
    Returns only the newly generated tokens (not the seed).
    Each N token has: p (absolute pitch), d, ph, iv, voice, od, t='N'
    """
    model.eval()
    context       = list(seed_tokens)
    stream_onset  = sum(t.get('d', 0) for t in context if t['t'] == 'N')
    tracker       = VoiceTracker(n_voices)
    result        = []

    # initialise voice tracker from seed
    voice_onset = {}
    for tok in context:
        if tok['t'] == 'N':
            vid = tok.get('voice', 0)
            tracker.last_pitch[vid] = tok['p']
            tracker.end_time[vid]   = voice_onset.get(vid, 0) + tok['d']
            voice_onset[vid]        = voice_onset.get(vid, 0) + tok['d']

    with torch.no_grad():
        for _ in range(n_new):
            batch  = _make_batch(context, device)
            logits = model(batch)
            pos    = min(len(context), MAX_SEQ) - 1

            # ── onset_delta: when does the next token start? ───────────────
            od_bucket   = sample_top_k(logits['od'][0, pos], top_k, temperature)
            od_raw      = _OD_BREAKS[od_bucket]          # approximate 16ths
            new_onset   = stream_onset + od_raw

            # ── token type ────────────────────────────────────────────────
            tok_type = sample_top_k(logits['type'][0, pos], top_k, temperature)

            if tok_type == 0:  # Note
                iv_bucket = sample_top_k(logits['iv'][0, pos], top_k, temperature)
                interval  = iv_bucket - 14                  # -14..+14
                dur       = max(1, sample_top_k(logits['dur'][0, pos], top_k, temperature))

                vid        = tracker.assign(new_onset)
                prev_pitch = tracker.get_pitch(vid)

                # soft centering: nudge toward mid-range (dp=28) if drifting
                center = 28
                if abs(prev_pitch - center) > 10:
                    interval = interval - int(0.3 * (prev_pitch - center))

                abs_pitch = max(7, min(PITCH_VOCAB - 8, prev_pitch + interval))
                tracker.update(vid, abs_pitch, new_onset, dur)

                tok = {
                    't':     'N',
                    'p':     abs_pitch,
                    'd':     dur,
                    'o':     new_onset,
                    'ph':    _phase(new_onset, dur),
                    'iv':    interval,
                    'voice': vid,
                    'od':    od_raw,
                    'm':     None,
                    'v':     [],
                }

            else:  # Motif announcement
                mid  = sample_top_k(logits['mid'][0, pos],  top_k, temperature)
                dist = sample_top_k(logits['dist'][0, pos], top_k, temperature)
                tok  = {'t':'M', 'id':mid, 'dp0':0, 'inv':0,
                        'o':new_onset, 'od':od_raw, 'dist':dist}

            # always advance stream_onset (od is relative to previous token, any type)
            stream_onset = new_onset

            context.append(tok)
            result.append(tok)

    return result


# ── kern export ───────────────────────────────────────────────────────────────

def _build_voice_timeline(events: dict, total_dur: int) -> list:
    """
    Given {onset: (dur, pitch)}, build a complete list of (onset, dur, pitch_or_None)
    that covers 0..total_dur exactly, filling gaps with rests (None)
    and truncating notes at measure boundaries.
    """
    result = []
    pos    = 0
    for onset in sorted(events):
        if onset >= total_dur:
            break
        # fill gap before this note with rest
        if onset > pos:
            result.append((pos, onset - pos, None))
            pos = onset
        dur, pitch = events[onset]
        # truncate at next measure boundary
        mbar_end = ((onset // MEASURE_DUR) + 1) * MEASURE_DUR
        dur = min(dur, mbar_end - onset, total_dur - onset)
        dur = max(1, dur)
        result.append((onset, dur, pitch))
        pos = onset + dur
    # trailing rest to fill last measure
    if pos < total_dur:
        result.append((pos, total_dur - pos, None))
    return result


def voices_to_kern(tokens: list, n_voices: int) -> str:
    """
    Split generated token stream into voices by tok['voice'],
    ensure both voices fill each measure completely (pad with rests),
    write as n_voices-spine kern.
    """
    note_toks = [t for t in tokens if t['t'] == 'N']
    if not note_toks:
        return ''
    offset = min(t['o'] for t in note_toks)

    voice_events = {v: {} for v in range(n_voices)}
    for tok in note_toks:
        vid   = tok.get('voice', 0)
        onset = tok['o'] - offset
        if vid < n_voices and onset not in voice_events[vid]:
            voice_events[vid][onset] = (tok['d'], tok['p'])

    # total duration: round up to full measures
    import math
    max_end  = max(o + d for ev in voice_events.values() for o, (d, _) in ev.items()) if any(voice_events.values()) else MEASURE_DUR
    total    = math.ceil(max_end / MEASURE_DUR) * MEASURE_DUR

    # build complete timelines (notes + rests, measure-aligned)
    timelines = {v: _build_voice_timeline(voice_events[v], total)
                 for v in range(n_voices)}

    # all distinct event onsets across all voices
    all_times = sorted(set(o for tl in timelines.values() for o, d, p in tl))

    n   = n_voices
    TAB = '\t'

    lines = [
        TAB.join(['**kern'] * n),
        TAB.join(['*MM90']  * n),
        TAB.join(['*M4/4']  * n),
        TAB.join(['*k[]']   * n),
        TAB.join(['*C:']    * n),
        TAB.join(['=1-']    * n),
    ]

    measure_start = 0
    measure_num   = 1
    # index pointer per voice
    ptrs = {v: 0 for v in range(n)}

    for t in all_times:
        while t >= measure_start + MEASURE_DUR:
            measure_start += MEASURE_DUR
            measure_num   += 1
            lines.append(TAB.join([f'={measure_num}'] * n))

        cols = []
        for vid in range(n):
            tl  = timelines[vid]
            ptr = ptrs[vid]
            if ptr < len(tl) and tl[ptr][0] == t:
                onset, dur, pitch = tl[ptr]
                ptrs[vid] += 1
                if pitch is None:
                    cols.append(dur16_to_kern(dur) + 'r')
                else:
                    cols.append(dur16_to_kern(dur) + dp_to_kern_pitch(pitch))
            else:
                cols.append('.')
        lines.append(TAB.join(cols))

    lines += [TAB.join(['=='] * n), TAB.join(['*-'] * n)]
    return '\n'.join(lines) + '\n'


# ── seed loading ──────────────────────────────────────────────────────────────

def load_seed(data_path: Path, seed_file: int, seed_name: str,
              seed_n: int) -> tuple:
    if not data_path.exists():
        return [], '(none)'
    with open(data_path, encoding='utf-8') as f:
        for i, line in enumerate(f):
            rec = json.loads(line)
            match_name = not seed_name or seed_name.lower() in rec['file'].lower()
            match_idx  = seed_name or i == seed_file
            if match_name and match_idx:
                return rec['tokens'][:seed_n], rec['file']
    return [], '(not found)'


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', default=str(CKPT_DIR / 'best.pt'))
    parser.add_argument('--n',          type=int,   default=300,
                        help='new tokens to generate')
    parser.add_argument('--seed-file',  type=int,   default=0)
    parser.add_argument('--seed-name',  default='',
                        help='filename fragment, e.g. wtc1p01 or inven01')
    parser.add_argument('--seed-n',     type=int,   default=64,
                        help='seed length in tokens')
    parser.add_argument('--temp',       type=float, default=0.9)
    parser.add_argument('--top-k',      type=int,   default=40)
    parser.add_argument('--voices',     type=int,   default=2)
    parser.add_argument('--out',        default='generated/generated.krn')
    parser.add_argument('--device',     default='auto')
    parser.add_argument('--list-seeds', action='store_true')
    args = parser.parse_args()

    data_path = BASE_DIR / 'train_data_full.jsonl'
    if not data_path.exists():
        data_path = BASE_DIR / 'train_data.jsonl'

    if args.list_seeds:
        with open(data_path, encoding='utf-8') as f:
            for i, line in enumerate(f):
                rec = json.loads(line)
                print(f'{i:4d}  {rec["file"]}')
        return

    device = ('cuda' if torch.cuda.is_available() else 'cpu') \
             if args.device == 'auto' else args.device
    print(f'Device: {device}')

    ckpt_path = Path(args.checkpoint)
    if not ckpt_path.exists():
        print(f'ERROR: {ckpt_path} not found — train first')
        sys.exit(1)

    ckpt       = torch.load(ckpt_path, map_location=device, weights_only=False)
    saved_args = ckpt.get('args', {})
    model = MusicModel(
        d_model  = saved_args.get('d_model',  D_MODEL),
        n_layers = saved_args.get('layers',   N_LAYERS),
    ).to(device)
    model.load_state_dict(ckpt['model'])
    print(f'Loaded: epoch {ckpt["epoch"]+1}  '
          f'best_val={ckpt.get("best_val", float("nan")):.4f}')

    seed_tokens, seed_file = load_seed(data_path, args.seed_file,
                                       args.seed_name, args.seed_n)
    print(f'Seed: {len(seed_tokens)} tokens from "{seed_file}"')

    print(f'Generating {args.n} tokens  voices={args.voices}  '
          f'temp={args.temp}  top_k={args.top_k} ...')
    new_tokens = generate(model, seed_tokens, args.n,
                          temperature=args.temp, top_k=args.top_k,
                          n_voices=args.voices, device=device)

    n_notes  = sum(1 for t in new_tokens if t['t'] == 'N')
    n_motifs = sum(1 for t in new_tokens if t['t'] == 'M')
    print(f'Done: {n_notes} notes, {n_motifs} motif events')

    kern     = voices_to_kern(new_tokens, args.voices)
    out_path = BASE_DIR / args.out
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(kern, encoding='utf-8')
    print(f'Written: {out_path}')
    print('\n--- preview ---')
    print('\n'.join(kern.split('\n')[:20]))


if __name__ == '__main__':
    main()

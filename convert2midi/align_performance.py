#!/usr/bin/env python3
"""
Audio-to-score alignment (step 1: coarse DTW) between a real recording and our score.

The score is rendered with a constant tempo (piano timbre via fluidsynth), chroma features of
the rendering and of the recording are compared with DTW, and the resulting path gives
score position (quarter notes) -> time in the recording.

Usage:
  python convert2midi/align_performance.py kern/osu/classical/bach/inventions/inven01.krn \
        convert2midi/recordings/inven01_meyer/meyer_bwv772.ogg
"""
import argparse, os, subprocess, sys

import numpy as np

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
import midi_export as me

FLUID = os.path.join(_here, '_audio_tools', 'fluidsynth', 'fluidsynth-v2.6.2-win10-x64-cpp11',
                     'bin', 'fluidsynth.exe')
SF2 = os.path.join(_here, '_audio_tools', 'soundfont', 'GeneralUser-GS.sf2')
SR = 22050
HOP = 512
SYNTH_BPM = 90.0


def render_score(path, out_dir):
    """Score -> constant-tempo piano MIDI + wav. Returns (wav_path, notes) where notes is
    [(nid, onset_q, dur_q, midi)]."""
    nid_to_note, _motifs, _seqs, mei = me.analyse(path)
    fixed = me.sounding_midi(mei, nid_to_note)
    notes = [(nid, v[5], v[3], fixed.get(nid, v[4])) for nid, v in nid_to_note.items()]
    track = ('piano', 0, me.BACKGROUNDS['piano'],
             sorted((o, d, m, 80) for _n, o, d, m in notes))
    base = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(out_dir, exist_ok=True)
    mid = os.path.join(out_dir, base + '_ref_piano.mid')
    wav = os.path.join(out_dir, base + '_ref_piano.wav')
    me.write_midi(mid, [track], SYNTH_BPM)
    subprocess.run([FLUID, '-ni', '-g', '0.8', '-r', str(SR), '-F', wav, SF2, mid],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wav, notes


def chroma(wav):
    import librosa
    y, _ = librosa.load(wav, sr=SR, mono=True)
    c = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
    return c, len(y) / SR


def align(ref_wav, rec_wav):
    import librosa
    Xr, dur_ref = chroma(ref_wav)
    Xp, dur_rec = chroma(rec_wav)
    D, wp = librosa.sequence.dtw(X=Xr, Y=Xp, metric='cosine')
    wp = wp[::-1]                       # ascending
    t_ref = wp[:, 0] * HOP / SR
    t_rec = wp[:, 1] * HOP / SR
    return t_ref, t_rec, dur_ref, dur_rec, float(D[-1, -1] / len(wp))


def refine_notes(rec_path, notes, uq, rec_at, win=0.12, hop=128, bpo=36, bias=None):
    """Step 2: per-note attack time. For every note the onset of energy at its own pitch is
    searched in +-`win` seconds around the DTW expectation (shrunk when the same pitch is
    repeated nearby). Returns rows (nid, onset_q, dur_q, midi, t_exp, t_found, z) where z is the
    robust z-score of the chosen onset-flux peak (>3 = reliable).
    `bias` {midi: seconds}: systematic early detection of the CQT flux (long kernels of low
    notes smear the attack backwards); the search window is shifted by it and it is subtracted."""
    import librosa
    y, _ = librosa.load(rec_path, sr=SR, mono=True)
    fmin = librosa.note_to_hz('C1')
    n_bins = bpo * 7
    C = np.abs(librosa.cqt(y, sr=SR, hop_length=hop, fmin=fmin, n_bins=n_bins,
                           bins_per_octave=bpo))
    L = np.log1p(30.0 * C)
    flux = np.maximum(0.0, np.diff(L, axis=1, prepend=L[:, :1]))
    flux = np.apply_along_axis(lambda r: np.convolve(r, np.ones(3) / 3.0, mode='same'), 1, flux)
    fps = SR / hop
    c1 = librosa.note_to_midi('C1')
    by_pitch = {}
    for n in notes:
        by_pitch.setdefault(n[3], []).append(n[1])
    for k in by_pitch:
        by_pitch[k].sort()
    rows = []
    stats = {}
    for nid, oq, dq, midi in sorted(notes, key=lambda n: n[1]):
        b = int(round((midi - c1) * bpo / 12.0))
        if b < 1 or b >= n_bins - 1:
            continue
        f = flux[b - 1:b + 2].max(axis=0)          # +-1/3 semitone tolerance
        if midi not in stats:
            med = float(np.median(f)); mad = float(np.median(np.abs(f - med))) + 1e-9
            stats[midi] = (med, mad)
        med, mad = stats[midi]
        t_exp = float(np.interp(oq, uq, rec_at))
        bs = (bias or {}).get(midi, 0.0)
        w = win
        same = by_pitch[midi]
        i = same.index(oq)
        for j in (i - 1, i + 1):
            if 0 <= j < len(same):
                gap = abs(same[j] - oq) * 60.0 / SYNTH_BPM
                w = min(w, 0.45 * gap)
        lo = max(0, int((t_exp + bs - w) * fps)); hi = min(len(f), int((t_exp + bs + w) * fps) + 1)
        if hi - lo < 2:
            continue
        seg = f[lo:hi]
        k = int(np.argmax(seg))
        z = (float(seg[k]) - med) / (1.4826 * mad)
        rows.append((nid, oq, dq, midi, t_exp, (lo + k) / fps - bs, z))
    return rows


def calibrate_bias(ref_wav, notes, wobble=0.05):
    """Detector bias per midi pitch, measured on the score rendering whose onsets are exactly
    known (the expectation is perturbed by a +-`wobble` s sinusoid to mimic DTW error)."""
    q = np.linspace(0, max(n[1] for n in notes) + 8, 4000)
    rows = refine_notes(ref_wav, notes, q, q * 60.0 / SYNTH_BPM + wobble * np.sin(q / 3.0))
    err = {}
    for r in rows:
        if r[6] > 3:
            err.setdefault(r[3], []).append(r[5] - r[1] * 60.0 / SYNTH_BPM)
    pitches = sorted(err)
    out = {}
    for m in sorted({n[3] for n in notes}):
        near = [e for p in pitches if abs(p - m) <= 4 for e in err[p]]
        if not near:
            p = min(pitches, key=lambda x: abs(x - m)); near = err[p]
        out[m] = float(np.median(near))
    return out


def _cqt_db(path, hop=128, bpo=36):
    import librosa
    y, _ = librosa.load(path, sr=SR, mono=True)
    C = np.abs(librosa.cqt(y, sr=SR, hop_length=hop, fmin=librosa.note_to_hz('C1'),
                           n_bins=bpo * 7, bins_per_octave=bpo))
    return 20.0 * np.log10(C + 1e-6), SR / hop


def _note_levels(path, items, hop=128, bpo=36):
    """items: [(midi, t_attack, t_limit)] -> [(attack_peak_db, drop_time_or_None)].
    attack_peak_db: peak level (max over +-1/3 semitone) in the 120 ms after the attack.
    drop_time: seconds after the attack at which the level has fallen 18 dB below that peak
    (a damped / short note), None if it has not before t_limit."""
    import librosa
    db, fps = _cqt_db(path, hop, bpo)
    c1 = librosa.note_to_midi('C1')
    out = []
    for midi, t0, t1 in items:
        b = int(round((midi - c1) * bpo / 12.0))
        b = min(max(b, 1), db.shape[0] - 2)
        lv = db[b - 1:b + 2].max(axis=0)
        i0 = int(t0 * fps); i1 = max(i0 + 2, int((t0 + 0.12) * fps))
        peak = float(lv[i0:i1].max()) if i0 < len(lv) else -120.0
        drop = None
        j_end = min(len(lv), int(t1 * fps))
        for j in range(i1, j_end):
            if lv[j] < peak - 18.0 and lv[j:j + 4].max() < peak - 18.0:
                drop = (j - i0) / fps
                break
        out.append((peak, drop))
    return out


def smooth_expectation(rows, half=2.5):
    """Robust local-linear fit of attack time vs score position over the reliable notes.
    Returns (unique score positions, fitted times): a tempo curve without the single-note
    detection noise, used as the centre of a narrower second search."""
    rows = sorted(rows, key=lambda r: r[1])
    oq = np.array([r[1] for r in rows]); tf = np.array([r[5] for r in rows])
    ok = np.array([r[6] for r in rows]) > 3
    uq = np.unique(oq)
    fit = np.zeros(len(uq))
    for k, q0 in enumerate(uq):
        m = ok & (np.abs(oq - q0) <= half)
        if m.sum() < 4:
            m = np.abs(oq - q0) <= 2 * half
        x, y = oq[m], tf[m]
        keep = np.ones(len(x), bool)
        for _ in range(3):
            if keep.sum() < 3:
                break
            a, b = np.polyfit(x[keep], y[keep], 1)
            res = y - (a * x + b)
            mad = np.median(np.abs(res[keep])) * 1.4826 + 1e-3
            keep = np.abs(res) < 2.5 * mad
        fit[k] = a * q0 + b
    return uq, fit


def build_performance(rec_path, ref_wav, rows, notes, out_dir, base, micro_scale=1.0,
                      vel_gain=2.2, vel_win=1.0, tag='performed'):
    """Step 3: performed timing, loudness and damping from the note table -> MIDI + CSV.
    Time axis of the written MIDI is seconds (bpm 60, 1 quarter = 1 s)."""
    import csv
    rows = sorted(rows, key=lambda r: r[1])
    oq = np.array([r[1] for r in rows]); t_exp = np.array([r[4] for r in rows])
    t_fnd = np.array([r[5] for r in rows]); z = np.array([r[6] for r in rows])
    good = z > 3
    dev = t_fnd - t_exp
    # unreliable notes: DTW expectation shifted by the median deviation of reliable neighbours
    t_perf = t_fnd.copy()
    for i in np.where(~good)[0]:
        near = good & (np.abs(oq - oq[i]) <= 4.0)
        t_perf[i] = t_exp[i] + (np.median(dev[near]) if near.any() else 0.0)
    # tempo-smoothed timing: local linear fit over +-3 quarters; residual = micro-timing
    micro = np.zeros(len(rows)); tempo_t = np.zeros(len(rows))
    for i in range(len(rows)):
        m = good & (np.abs(oq - oq[i]) <= 3.0)
        if m.sum() >= 4:
            a, b = np.polyfit(oq[m], t_fnd[m], 1)
            tempo_t[i] = a * oq[i] + b
        else:
            tempo_t[i] = t_perf[i]
        micro[i] = t_perf[i] - tempo_t[i]
    # musical mode: keep only `micro_scale` of the single-note deviation; the tempo curve itself
    # (smooth robust fit) carries the agogic. Single-note attack detection is noisy (sd ~40 ms),
    # copying it 1:1 makes 16th-note runs sound uneven.
    uq_b, fit_b = smooth_expectation(rows)
    base_t = np.interp(oq, uq_b, fit_b)
    t_perf = np.where(good, base_t + micro_scale * (t_fnd - base_t), base_t)
    micro = t_perf - base_t

    # levels: recording vs the same notes in the mechanical piano rendering (known onsets)
    dur_real = np.zeros(len(rows))
    for i, r in enumerate(rows):
        # notated duration scaled by the local tempo (seconds per quarter from the smooth fit)
        j = min(len(rows) - 1, i + 1)
        spq = 60.0 / SYNTH_BPM
        lo = max(0, i - 8); hi = min(len(rows) - 1, i + 8)
        if oq[hi] > oq[lo]:
            spq = (tempo_t[hi] - tempo_t[lo]) / (oq[hi] - oq[lo])
        dur_real[i] = r[2] * spq
    lim = t_perf + np.maximum(dur_real, 0.3)
    rec_lv = _note_levels(rec_path, [(r[3], t_perf[i], lim[i]) for i, r in enumerate(rows)])
    ref_lv = _note_levels(ref_wav, [(r[3], r[1] * 60.0 / SYNTH_BPM, r[1] * 60.0 / SYNTH_BPM
                                     + max(0.3, r[2] * 60.0 / SYNTH_BPM)) for r in rows])
    rel = np.array([a[0] - b[0] for a, b in zip(rec_lv, ref_lv)])
    rel -= np.median(rel[good])
    # smooth over +-1 quarter: overlapping voices make single attacks noisy
    rel_s = np.array([np.median(rel[np.abs(oq - oq[i]) <= vel_win]) * 0.5 + rel[i] * 0.5
                      for i in range(len(rows))])
    vel = np.clip(80 + vel_gain * rel_s, 25, 125).astype(int)
    out_notes = []
    damped = []
    for i, r in enumerate(rows):
        dr = rec_lv[i][1]; dd = ref_lv[i][1]
        is_damped = dr is not None and (dd is None or dr < 0.7 * dd)
        damped.append(is_damped)
        dur = dur_real[i] * (0.55 if is_damped else 1.0)
        out_notes.append((float(t_perf[i]), float(dur), int(r[3]), int(vel[i])))
    track = ('piano performed', 0, me.BACKGROUNDS['piano'], sorted(out_notes))
    mid = os.path.join(out_dir, base + '_' + tag + '_piano.mid')
    me.write_midi(mid, [track], 60.0)
    wav = mid[:-4] + '.wav'
    subprocess.run([FLUID, '-ni', '-g', '0.8', '-r', str(SR), '-F', wav, SF2, mid],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(out_dir, base + '_' + tag + '.csv'), 'w', newline='') as fh:
        wr = csv.writer(fh)
        wr.writerow(['nid', 'onset_q', 'midi', 't_perf', 'micro_ms', 'level_rel_db', 'velocity',
                     'damped', 'reliable'])
        for i, r in enumerate(rows):
            wr.writerow([r[0], r[1], r[3], f'{t_perf[i]:.4f}', f'{1000 * micro[i]:.1f}',
                         f'{rel_s[i]:.1f}', vel[i], int(damped[i]), int(good[i])])
    print(f'\nperformance: micro-timing sd {1000 * micro[good].std():.0f} ms, '
          f'velocity {vel.min()}..{vel.max()} (median {int(np.median(vel))}), '
          f'damped (short) notes {sum(damped)}')
    # beat-position profile: on-beat vs off-beat micro-timing and loudness
    ph = np.round((oq % 1.0) * 4).astype(int) % 4
    for k, nm in enumerate(['on the beat', '2nd 16th', '8th (off-beat)', '4th 16th']):
        m = good & (ph == k)
        if m.sum() > 5:
            print(f'  {nm:15s} n={m.sum():3d} micro {1000 * micro[m].mean():+5.1f} ms, '
                  f'level {rel_s[m].mean():+5.1f} dB')
    return mid, wav


def ref_time_to_q(t):
    return t * SYNTH_BPM / 60.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('score')
    ap.add_argument('recording')
    ap.add_argument('--out-dir', default=os.path.join(_here, 'align_out'))
    ap.add_argument('--bar-q', type=float, default=4.0, help='quarters per bar for the report')
    args = ap.parse_args()

    wav, notes = render_score(os.path.abspath(args.score), args.out_dir)
    t_ref, t_rec, dur_ref, dur_rec, cost = align(wav, os.path.abspath(args.recording))
    print(f'reference {dur_ref:.1f}s, recording {dur_rec:.1f}s, mean DTW cost/step {cost:.3f}')

    # score position (quarters) -> recording time, monotone interpolation of the DTW path
    q = ref_time_to_q(t_ref)
    uq, idx = np.unique(q, return_index=False, return_inverse=False), None
    rec_at = np.interp(uq, q, t_rec)
    end_q = max(o + d for _n, o, d, _m in notes)
    bars = np.arange(0, end_q + 1e-9, args.bar_q)
    bt = np.interp(bars, uq, rec_at)
    print('bar  start_s  length_s  local tempo (quarters/min)')
    for i in range(len(bars) - 1):
        ln = bt[i + 1] - bt[i]
        print(f'{i + 1:3d}  {bt[i]:7.2f}  {ln:7.2f}  {args.bar_q * 60 / ln:7.1f}')
    bias = calibrate_bias(wav, notes)
    rows = refine_notes(os.path.abspath(args.recording), notes, uq, rec_at, bias=bias)
    # second pass: narrow window around the smoothed tempo curve built from the first pass
    uq2, fit2 = smooth_expectation(rows)
    rows = refine_notes(os.path.abspath(args.recording), notes, uq2, fit2, win=0.07, bias=bias)
    z = np.array([r[6] for r in rows])
    dev = np.array([r[5] - r[4] for r in rows])
    good = z > 3
    print(f'\nnotes {len(notes)}, searched {len(rows)}, reliable (z>3) {int(good.sum())} '
          f'({100 * good.mean():.0f}%)')
    print('found - DTW expectation, ms: median %.0f, 10%%..90%% %.0f..%.0f  (reliable notes)' % (
        1000 * np.median(dev[good]), 1000 * np.percentile(dev[good], 10),
        1000 * np.percentile(dev[good], 90)))
    import csv
    base = os.path.splitext(os.path.basename(args.score))[0]
    with open(os.path.join(args.out_dir, base + '_notes.csv'), 'w', newline='') as fh:
        wr = csv.writer(fh)
        wr.writerow(['nid', 'onset_q', 'dur_q', 'midi', 't_dtw', 't_found', 'z'])
        for r in rows:
            wr.writerow([r[0], r[1], r[2], r[3], f'{r[4]:.4f}', f'{r[5]:.4f}', f'{r[6]:.2f}'])
    for tag, ms, vg, vw in (('performed', 1.0, 2.2, 1.0),      # everything as measured
                            ('tempo_only', 0.0, 0.0, 1.0),      # smooth tempo, flat dynamics
                            ('musical', 0.25, 1.2, 2.0)):      # smooth tempo + damped detail
        mid, pwav = build_performance(os.path.abspath(args.recording), wav, rows, notes,
                                      args.out_dir, base, ms, vg, vw, tag)
        print('written', pwav)
    np.savez(os.path.join(args.out_dir, os.path.splitext(os.path.basename(args.score))[0] + '_dtw.npz'),
             t_ref=t_ref, t_rec=t_rec, bars=bars, bar_times=bt)


if __name__ == '__main__':
    main()

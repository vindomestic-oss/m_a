#!/usr/bin/env python3
"""
tsd_model.py — Train a TSD harmonic-function classifier and generate predictions.

Usage:
    python tsd_model.py          # train on TSD.txt → generate TSD_generated.txt
    python tsd_model.py --eval   # leave-one-file-out cross-validation

Input:  TSD.txt (manually annotated sequences)
Output: TSD_generated.txt (predictions for all chorales in the kern collection)
        tsd_model.npz            (saved weights for inspection)

Model: 2-layer MLP (numpy, no torch/tf), 75→64→3 (T/S/D)
Features per beat (75 total):
  - 12 all-voice PC histogram, current beat  (key-relative, duration-weighted)
  - 12 bass PC histogram,      current beat
  - 12 all-voice PC histogram, previous beat (zeros at start)
  - 12 bass PC histogram,      previous beat
  - 12 all-voice PC histogram, next beat     (zeros at end)
  - 12 bass PC histogram,      next beat
  - 1 fractional position in piece
  - 1 binary phase: (i % 2) / 2
  - 1 bar phase:    (i % beats_per_bar) / beats_per_bar
  = 75 features total
"""

import os, sys, re
import numpy as np
from fractions import Fraction

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
TSD_TXT          = os.path.join(SCRIPT_DIR, 'TSD.txt')
TSD_GEN_4        = os.path.join(SCRIPT_DIR, 'TSD_generated_4.txt')
TSD_GEN_8        = os.path.join(SCRIPT_DIR, 'TSD_generated_8.txt')
MODEL_PATH       = os.path.join(SCRIPT_DIR, 'tsd_model.npz')
LILYPOND_XML_DIR = os.path.join(SCRIPT_DIR, 'lilypond', 'musicxml')

LABEL_IDX    = {'T': 0, 'S': 1, 'D': 2}
IDX_LABEL    = ['T', 'S', 'D']
N_FEATURES   = 75   # 27 current + 24 prev + 24 next (12 all-voice + 12 bass each)

# ── v2 feature constants ──────────────────────────────────────────────────────
# Per (quantum, voice): state(3) + degree_onehot(7) + octave_norm(1) + alt_onehot(3) + rest_decay(1) = 15
# W_SLOTS_V2 quanta × V_MAX_V2 voices × 15 dims + 3 global = 243 total
QUANTUM_Q_V2  = 0.25   # 1/16 note
W_SLOTS_V2    = 4      # fixed quanta slots per window (pad if shorter)
V_MAX_V2      = 4      # max voices (pad with zeros)
MAX_REST_Q_V2 = 32     # quanta cap for log rest-decay
_DIMS_PER_QV  = 15     # dims per (quantum, voice)
N_FEATURES_V2 = W_SLOTS_V2 * V_MAX_V2 * _DIMS_PER_QV + 3  # 243

_DIATONIC_STEP = {'C': 0, 'D': 1, 'E': 2, 'F': 3, 'G': 4, 'A': 5, 'B': 6}

# ── helpers ───────────────────────────────────────────────────────────────────

def _bar_dur_to_metre(bar_dur_q: float) -> str:
    """0.5 → '1/8',  1.0 → '1/4',  2.0 → '1/2',  3.0 → '3/4'"""
    f = Fraction(bar_dur_q / 4).limit_denominator(32)
    return f"{f.numerator}/{f.denominator}"

# ── TSD.txt loading ───────────────────────────────────────────────────────────

def load_tsd_data() -> dict:
    """Return {filename: (bar_dur_q, beats_per_bar, [labels])} skipping incomplete entries."""
    data = {}
    with open(TSD_TXT, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            filenames_field, metre, tsd_str = parts[0], parts[1], parts[2]
            if '...' in tsd_str:
                continue
            num, den = metre.split('/')
            bar_dur_q    = int(num) * 4.0 / int(den)
            beats_per_bar = int(num)
            labels = [c for c in tsd_str if c in 'TSD']
            if labels:
                for fname in filenames_field.split(','):
                    data[fname.strip()] = (bar_dur_q, beats_per_bar, labels)
    return data

# ── file discovery ────────────────────────────────────────────────────────────

def find_file(filename: str) -> str | None:
    """Search the repo for a file by basename."""
    for root, _dirs, files in os.walk(SCRIPT_DIR):
        if filename in files:
            return os.path.join(root, filename)
    return None

def find_chorales() -> list[str]:
    """Return paths to Bach chorale .mxl files from the music21 corpus (matches browser filenames)."""
    import music21.corpus as _corp
    sep = os.sep
    results = []
    for p in sorted(_corp.getCorePaths(), key=lambda x: str(x).lower()):
        s = str(p)
        norm = s.replace('\\', '/')
        if '/bach/bwv' in norm and s.endswith('.mxl'):
            results.append(s)
    return results

# ── feature extraction ────────────────────────────────────────────────────────

def _parse_kern_notes(path: str):
    """
    Fast kern parser: returns (notes, tonic_pc, mode) where
    notes = [(onset_q, dur_q, midi), ...], tonic_pc in 0..11, mode 'major'/'minor'.
    Uses music21 (already a dependency).
    """
    import music21
    score = music21.converter.parse(path)
    try:
        key = score.analyze('key')
        tonic_pc = key.tonic.pitchClass
        mode     = key.mode
    except Exception:
        tonic_pc, mode = 0, 'major'

    notes = []
    for part in score.parts:
        for el in part.flatten().notes:
            onset = float(el.offset)
            dur   = float(el.duration.quarterLength) or 0.0625
            if hasattr(el, 'pitches'):           # Chord
                for p in el.pitches:
                    notes.append((onset, dur, p.pitchClass, p.midi))
            else:
                notes.append((onset, dur, el.pitch.pitchClass, el.pitch.midi))

    return notes, tonic_pc, mode


def _beat_hists(notes, tonic_pc: int, t0: float, bar_dur_q: float):
    """Return (all_hist, bass_hist) for the beat window [t0, t0+bar_dur_q).
    Falls back to ±bar_dur_q neighbourhood when the window is empty."""
    t1 = t0 + bar_dur_q
    win = [(pc, dur, midi) for (o, dur, pc, midi) in notes if t0 <= o < t1]
    if not win:
        win = [(pc, dur, midi) for (o, dur, pc, midi) in notes
               if abs(o - t0) < bar_dur_q]

    all_hist = np.zeros(12)
    for pc, dur, _ in win:
        all_hist[(pc - tonic_pc) % 12] += dur
    s = all_hist.sum()
    if s > 0:
        all_hist /= s

    bass_onsets = {}
    for (o, dur, pc, midi) in notes:
        if t0 <= o < t1:
            if o not in bass_onsets or midi < bass_onsets[o][1]:
                bass_onsets[o] = (pc, midi)
    bass_hist = np.zeros(12)
    for pc, _ in bass_onsets.values():
        bass_hist[(pc - tonic_pc) % 12] += 1.0
    s = bass_hist.sum()
    if s > 0:
        bass_hist /= s

    return all_hist, bass_hist


# ── v2 feature extraction (voice-aware) ──────────────────────────────────────

def _build_timelines_v2(path: str):
    """
    Parse score into per-part event timelines.
    Returns (timelines, tonic_pc, max_onset_q) where
    timelines = list of sorted [(onset_q, dur_q, info_or_None)] per part where
    info = (degree, octave, alt):
      degree: 0-6 diatonic step key-relative ((note_step - tonic_step) % 7)
      octave: absolute octave (2-6 typically)
      alt:    semitone alteration: -1=flat, 0=natural, +1=sharp
    None = rest.
    """
    import music21
    score = music21.converter.parse(path)
    try:
        key        = score.analyze('key')
        tonic_step = _DIATONIC_STEP[key.tonic.step]
    except Exception:
        tonic_step = 0   # fallback: C

    def _note_info(pitch):
        deg = (_DIATONIC_STEP[pitch.step] - tonic_step) % 7
        oct = pitch.octave if pitch.octave is not None else 4
        alt = int(round(pitch.alter))
        return (deg, oct, alt)

    timelines = []
    max_onset  = 0.0
    for part in score.parts:
        events = []
        for m in part.getElementsByClass('Measure'):
            m_off = float(m.offset)
            for el in m.notesAndRests:
                onset = m_off + float(el.offset)
                dur   = float(el.duration.quarterLength) or QUANTUM_Q_V2
                max_onset = max(max_onset, onset)
                if el.isRest:
                    events.append((onset, dur, None))
                elif hasattr(el, 'pitches'):
                    # chord: take lowest pitch
                    lowest = min(el.pitches, key=lambda p: p.ps)
                    events.append((onset, dur, _note_info(lowest)))
                else:
                    events.append((onset, dur, _note_info(el.pitch)))
        events.sort()
        timelines.append(events)

    return timelines, max_onset


def _quantum_feat_v2(events: list, t_q: float) -> np.ndarray:
    """
    15-dim feature for one voice at one time quantum t_q:
      [0]     is_attack    (note started at this quantum)
      [1]     is_sustained (note started earlier, still sounding)
      [2]     is_rest
      [3..9]  degree one-hot 0-6 (key-relative diatonic step mod 7)
      [10]    octave normalised oct/8  (0 if rest)
      [11..13] alteration one-hot: {-1→[1,0,0], 0→[0,1,0], +1→[0,0,1]} (0s if rest)
      [14]    rest_decay   log(1+q_silence)/log(1+MAX_REST_Q_V2)  (0 if not rest)
    """
    feat = np.zeros(_DIMS_PER_QV, dtype=np.float32)
    active_info   = None
    active_onset  = None
    prev_note_end = None

    for onset, dur, info in events:
        end = onset + dur
        if onset <= t_q < end:
            active_info  = info
            active_onset = onset
            break
        if end <= t_q and info is not None:
            prev_note_end = end
        if onset > t_q:
            break

    if active_info is not None:
        deg, oct, alt = active_info
        q_since = round((t_q - active_onset) / QUANTUM_Q_V2)
        feat[0 if q_since == 0 else 1] = 1.0          # attack / sustained
        feat[3 + deg] = 1.0                            # degree one-hot [3..9]
        feat[10] = oct / 8.0                           # octave normalised
        alt_idx = max(0, min(2, alt + 1))              # -1→0, 0→1, +1→2
        feat[11 + alt_idx] = 1.0                       # alteration one-hot [11..13]
    else:
        feat[2] = 1.0                                  # rest
        if prev_note_end is not None:
            rest_q = round((t_q - prev_note_end) / QUANTUM_Q_V2)
        else:
            rest_q = MAX_REST_Q_V2
        feat[14] = np.log1p(min(rest_q, MAX_REST_Q_V2)) / np.log1p(MAX_REST_Q_V2)

    return feat


def extract_features_v2(path: str, bar_dur_q: float, n_labels: int,
                         beats_per_bar: int = 4) -> np.ndarray | None:
    """
    Voice-aware feature extraction (v2).
    Returns float32 array (n_labels, N_FEATURES_V2) or None on failure.

    Feature layout per label window:
      W_SLOTS_V2 × V_MAX_V2 × 15 dims  (quantum-major, then voice-major)
      + 3 global dims (position, binary_phase, bar_phase)
    Voices = score.parts ordered by appearance; padded to V_MAX_V2 with zeros.
    W_SLOTS_V2 quanta filled from window start; remainder zero-padded.
    """
    try:
        timelines, max_onset = _build_timelines_v2(path)
    except Exception:
        return None
    if not timelines:
        return None

    # Pad / trim to V_MAX_V2 voices
    timelines = (timelines + [[]] * V_MAX_V2)[:V_MAX_V2]
    W = max(1, round(bar_dur_q / QUANTUM_Q_V2))   # actual quanta in this window

    feats = []
    for i in range(n_labels):
        t0       = i * bar_dur_q
        position = t0 / max_onset if max_onset > 0 else 0.0
        b_phase  = (i % 2) / 2
        bar_ph   = (i % beats_per_bar) / beats_per_bar

        row = np.zeros(W_SLOTS_V2 * V_MAX_V2 * _DIMS_PER_QV, dtype=np.float32)
        for k in range(min(W, W_SLOTS_V2)):
            t = t0 + k * QUANTUM_Q_V2
            for vi, tl in enumerate(timelines):
                vf   = _quantum_feat_v2(tl, t) if tl else np.zeros(_DIMS_PER_QV, np.float32)
                base = (k * V_MAX_V2 + vi) * _DIMS_PER_QV
                row[base:base + _DIMS_PER_QV] = vf

        feats.append(np.concatenate([row, [position, b_phase, bar_ph]]))

    return np.array(feats, dtype=np.float32)


def extract_features(path: str, bar_dur_q: float, n_labels: int,
                     beats_per_bar: int = 4) -> np.ndarray | None:
    """
    Return float32 array (n_labels, N_FEATURES) or None on failure.
    Features per beat (75 total):
      12 all-voice PC histogram (current)  + 12 bass PC histogram (current)
      12 all-voice PC histogram (previous) + 12 bass PC histogram (previous)
      12 all-voice PC histogram (next)     + 12 bass PC histogram (next)
      1 position in piece + 1 binary phase + 1 bar phase
    Neighbour histograms are zero-filled at boundaries.
    All PC histograms are key-relative (tonic = 0).
    """
    try:
        notes, tonic_pc, _mode = _parse_kern_notes(path)
    except Exception:
        return None

    if not notes:
        return None

    max_onset = max(o for o, *_ in notes)

    # Pre-compute per-beat histograms for all beats (including neighbours)
    all_hists  = []
    bass_hists = []
    for i in range(n_labels):
        ah, bh = _beat_hists(notes, tonic_pc, i * bar_dur_q, bar_dur_q)
        all_hists.append(ah)
        bass_hists.append(bh)

    zero24 = np.zeros(24)
    feats = []
    for i in range(n_labels):
        t0 = i * bar_dur_q
        position     = t0 / max_onset if max_onset > 0 else 0.0
        binary_phase = (i % 2) / 2
        bar_phase    = (i % beats_per_bar) / beats_per_bar

        prev = np.concatenate([all_hists[i-1], bass_hists[i-1]]) if i > 0             else zero24
        cur  = np.concatenate([all_hists[i],   bass_hists[i]])
        nxt  = np.concatenate([all_hists[i+1], bass_hists[i+1]]) if i < n_labels-1    else zero24

        feats.append(np.concatenate([cur, prev, nxt, [position, binary_phase, bar_phase]]))

    return np.array(feats, dtype=np.float32)

# ── neural network ────────────────────────────────────────────────────────────

class TSDNet:
    """2-layer MLP: N_FEATURES → 64 → 3, ReLU, softmax, L2 regularisation."""

    def __init__(self, n_in=N_FEATURES, n_hid=64, n_out=3, lr=0.01, l2=1e-3):
        rng = np.random.default_rng(42)
        self.W1 = rng.normal(0, 0.1, (n_in, n_hid)).astype(np.float32)
        self.b1 = np.zeros(n_hid, np.float32)
        self.W2 = rng.normal(0, 0.1, (n_hid, n_out)).astype(np.float32)
        self.b2 = np.zeros(n_out, np.float32)
        self.lr = lr
        self.l2 = l2

    def _softmax(self, z):
        e = np.exp(z - z.max(axis=1, keepdims=True))
        return e / e.sum(axis=1, keepdims=True)

    def forward(self, X):
        self._z1 = X @ self.W1 + self.b1
        self._a1 = np.maximum(0, self._z1)
        self._z2 = self._a1 @ self.W2 + self.b2
        self._p  = self._softmax(self._z2)
        return self._p

    def predict(self, X):
        return self.forward(X).argmax(axis=1)

    def _loss(self, y):
        n = len(y)
        ce = -np.log(self._p[np.arange(n), y] + 1e-9).mean()
        reg = self.l2 * (np.sum(self.W1**2) + np.sum(self.W2**2))
        return ce + reg

    def _step(self, X, y):
        n = len(y)
        dz2 = self._p.copy()
        dz2[np.arange(n), y] -= 1
        dz2 /= n
        dW2 = self._a1.T @ dz2 + self.l2 * self.W2
        db2 = dz2.sum(0)
        da1 = dz2 @ self.W2.T
        dz1 = da1 * (self._z1 > 0)
        dW1 = X.T @ dz1 + self.l2 * self.W1
        db1 = dz1.sum(0)
        self.W1 -= self.lr * dW1
        self.b1 -= self.lr * db1
        self.W2 -= self.lr * dW2
        self.b2 -= self.lr * db2

    def train(self, X, y, n_epochs=1000, batch=64, verbose=True):
        n = len(X)
        rng = np.random.default_rng(0)
        for ep in range(1, n_epochs + 1):
            idx = rng.permutation(n)
            for i in range(0, n, batch):
                b = idx[i:i+batch]
                self.forward(X[b])
                self._step(X[b], y[b])
            if verbose and ep % 200 == 0:
                self.forward(X)
                loss = self._loss(y)
                acc  = (self.predict(X) == y).mean()
                print(f"    ep {ep:4d}  loss={loss:.3f}  acc={acc:.1%}")

    def save(self, path):
        np.savez(path, W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2,
                 lr=self.lr, l2=self.l2)

    def load(self, path):
        d = np.load(path)
        self.W1, self.b1, self.W2, self.b2 = d['W1'], d['b1'], d['W2'], d['b2']

# ── training data assembly ────────────────────────────────────────────────────

def build_dataset(tsd_data: dict):
    X_all, y_all = [], []
    for filename, (bar_dur_q, beats_per_bar, labels) in tsd_data.items():
        path = find_file(filename)
        if path is None:
            print(f"  [skip]  {filename}: not found")
            continue
        feats = extract_features(path, bar_dur_q, len(labels), beats_per_bar)
        if feats is None or len(feats) == 0:
            print(f"  [skip]  {filename}: feature extraction failed")
            continue
        n = min(len(feats), len(labels))
        for i in range(n):
            X_all.append(feats[i])
            y_all.append(LABEL_IDX[labels[i]])
        print(f"  [ok]    {filename}: {n} windows")
    return np.array(X_all, dtype=np.float32), np.array(y_all, dtype=np.int32)

# ── evaluation ────────────────────────────────────────────────────────────────

def _lofo_run(tsd_data: dict, feat_fn, n_in: int, n_hid: int = 64, label: str = ''):
    """Generic LOFO engine. Pre-caches features to avoid re-parsing on every fold."""
    files = list(tsd_data.keys())

    # ── 1. Pre-compute features for all files (once) ──────────────────────────
    print(f"  Pre-computing features for {len(files)} files...")
    cache = {}   # fname → (X: np.ndarray, y: np.ndarray)
    for fname, (bdq, bpb, labs) in tsd_data.items():
        p = find_file(fname)
        if p is None:
            print(f"    [skip] {fname}: not found")
            continue
        f = feat_fn(p, bdq, len(labs), bpb)
        if f is None or len(f) == 0:
            print(f"    [skip] {fname}: feature extraction failed")
            continue
        n = min(len(f), len(labs))
        cache[fname] = (
            f[:n].astype(np.float32),
            np.array([LABEL_IDX[l] for l in labs[:n]], np.int32)
        )
        print(f"    [ok]   {fname}: {n} windows")
    print(f"  Cached {len(cache)}/{len(files)} files.\n")

    # ── 2. LOFO loop (only model training varies) ─────────────────────────────
    try:
        from sklearn.neural_network import MLPClassifier
        _use_sklearn = True
    except ImportError:
        _use_sklearn = False

    valid = [f for f in files if f in cache]
    print(f"  Running {len(valid)} folds... ({'sklearn' if _use_sklearn else 'numpy TSDNet'})")
    correct = total = 0
    per_file = []
    for fi, held_out in enumerate(valid):
        X_tr = np.concatenate([cache[f][0] for f in cache if f != held_out])
        y_tr = np.concatenate([cache[f][1] for f in cache if f != held_out])
        if len(X_tr) < 10:
            continue
        if _use_sklearn:
            clf = MLPClassifier(
                hidden_layer_sizes=(n_hid,),
                activation='relu',
                max_iter=300,
                random_state=42,
                early_stopping=False,
            )
            clf.fit(X_tr, y_tr)
            preds = clf.predict(cache[held_out][0])
        else:
            net = TSDNet(n_in=n_in, n_hid=n_hid)
            net.train(X_tr, y_tr, n_epochs=300, batch=len(X_tr), verbose=False)
            preds = net.predict(cache[held_out][0])
        X_ho, y_ho = cache[held_out]
        c = int((preds == y_ho).sum())
        per_file.append((held_out, c, len(y_ho)))
        correct += c
        total   += len(y_ho)
        print(f"  [{fi+1:2d}/{len(valid)}] {held_out:45s}  {c}/{len(y_ho)} = {c/len(y_ho):.0%}", flush=True)

    tag = f' [{label}]' if label else ''
    for fname, c, n in per_file:
        print(f"  {fname:50s}  {c}/{n} = {c/n:.0%}")
    print(f"\nLOFO accuracy{tag}: {correct}/{total} = {correct/total:.1%}")
    return correct / total if total else 0.0


def lofo_eval(tsd_data: dict):
    """Leave-one-file-out cross-validation (v1 features, 75-dim)."""
    _lofo_run(tsd_data, extract_features, N_FEATURES, n_hid=64, label='v1')


def lofo_eval_v2(tsd_data: dict):
    """Leave-one-file-out cross-validation (v2 voice-aware features, 259-dim)."""
    _lofo_run(tsd_data, extract_features_v2, N_FEATURES_V2, n_hid=128, label='v2')

# ── inference on chorales ─────────────────────────────────────────────────────

def generate_chorales(net: TSDNet, label_dur_q: float) -> dict:
    """Apply model to all chorales at given label granularity.
    label_dur_q: 1.0 = quarter note, 0.5 = eighth note.
    Returns {filename: (bar_dur_q, beats_per_bar, [labels])}.
    """
    import music21

    chorales = find_chorales()
    results  = {}
    ok = err = 0

    for path in chorales:
        fname = os.path.basename(path)
        try:
            score = music21.converter.parse(path)
            ts_list = list(score.parts[0].recurse().getElementsByClass('TimeSignature'))
            ts = ts_list[0] if ts_list else None

            bar_dur_q = label_dur_q
            if ts is not None:
                bar_total_q   = ts.numerator * float(ts.beatDuration.quarterLength)
                beats_per_bar = max(1, round(bar_total_q / label_dur_q))
            else:
                beats_per_bar = round(4.0 / label_dur_q)  # assume 4/4

            total_dur = float(score.duration.quarterLength)
            n_labels  = max(1, int(round(total_dur / bar_dur_q)))

            feats = extract_features(path, bar_dur_q, n_labels, beats_per_bar)
            if feats is None or len(feats) == 0:
                raise ValueError("no features")

            preds = net.predict(feats)
            results[fname] = (bar_dur_q, beats_per_bar, list(IDX_LABEL[p] for p in preds))
            ok += 1
        except Exception as e:
            err += 1

    print(f"  {ok} ok, {err} errors")
    return results

# ── inference on local XML files ─────────────────────────────────────────────

def generate_local_xml(net: TSDNet, label_dur_q: float,
                       glob_pattern: str = 'french_suite_*.xml',
                       skip_filenames: set | None = None) -> dict:
    """Apply model to local XML files matching glob_pattern in LILYPOND_XML_DIR.
    Skips filenames already in skip_filenames (e.g. those with manual TSD annotations).
    Returns {filename: (bar_dur_q, beats_per_bar, [labels])}.
    """
    import glob as _glob
    import music21

    if skip_filenames is None:
        skip_filenames = set()

    paths = sorted(_glob.glob(os.path.join(LILYPOND_XML_DIR, glob_pattern)))
    results = {}
    ok = err = 0

    for path in paths:
        fname = os.path.basename(path)
        if fname in skip_filenames:
            continue
        try:
            score = music21.converter.parse(path)
            ts_list = list(score.parts[0].recurse().getElementsByClass('TimeSignature'))
            ts = ts_list[0] if ts_list else None

            bar_dur_q = label_dur_q
            if ts is not None:
                bar_total_q   = ts.numerator * float(ts.beatDuration.quarterLength)
                beats_per_bar = max(1, round(bar_total_q / label_dur_q))
            else:
                beats_per_bar = round(4.0 / label_dur_q)

            total_dur = float(score.duration.quarterLength)
            n_labels  = max(1, int(round(total_dur / bar_dur_q)))

            feats = extract_features(path, bar_dur_q, n_labels, beats_per_bar)
            if feats is None or len(feats) == 0:
                raise ValueError("no features")

            preds = net.predict(feats)
            results[fname] = (bar_dur_q, beats_per_bar, list(IDX_LABEL[p] for p in preds))
            print(f"  [ok]    {fname}")
            ok += 1
        except Exception as e:
            print(f"  [err]   {fname}: {e}")
            err += 1

    print(f"  {ok} ok, {err} errors")
    return results


# ── output ────────────────────────────────────────────────────────────────────

def write_generated(results: dict, out_path: str):
    name = os.path.basename(out_path)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f'# {name} — auto-generated by tsd_model.py\n')
        f.write('# Retrain: python tsd_model.py\n\n')
        for fname, (bar_dur_q, beats_per_bar, labels) in sorted(results.items()):
            metre = _bar_dur_to_metre(bar_dur_q)
            parts = []
            for i, lbl in enumerate(labels):
                parts.append(lbl)
                if (i + 1) % beats_per_bar == 0 and i + 1 < len(labels):
                    parts.append("'")
            f.write(f"{fname}\t{metre}\t{''.join(parts)}\n")
    print(f"Written {len(results)} entries to {out_path}")

# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    eval_mode    = '--eval'    in sys.argv
    eval_v2_mode = '--eval-v2' in sys.argv

    print("Loading TSD.txt...")
    tsd_data = load_tsd_data()
    print(f"  {len(tsd_data)} annotated files")

    if eval_v2_mode:
        print("\nLeave-one-file-out cross-validation (v2 voice-aware, 259-dim):")
        lofo_eval_v2(tsd_data)
        sys.exit(0)

    if eval_mode:
        print("\nLeave-one-file-out cross-validation (v1, 75-dim):")
        lofo_eval(tsd_data)
        sys.exit(0)

    print("\nBuilding training set:")
    X, y = build_dataset(tsd_data)
    if len(X) == 0:
        print("No training data — aborting.")
        sys.exit(1)
    counts = {l: (y == i).sum() for l, i in LABEL_IDX.items()}
    print(f"  {len(X)} windows  T={counts['T']} S={counts['S']} D={counts['D']}")

    print(f"\nTraining ({N_FEATURES}->64->3, L2=1e-3):")
    net = TSDNet(lr=0.008, l2=1e-3)
    net.train(X, y, n_epochs=1000)
    train_acc = (net.predict(X) == y).mean()
    print(f"  Final train accuracy: {train_acc:.1%}")
    net.save(MODEL_PATH)

    annotated = set(tsd_data.keys())   # skip files that already have manual TSD

    print("\nGenerating predictions (1/4 granularity):")
    results_4 = generate_chorales(net, label_dur_q=1.0)
    print("\n  French Suite XML files (1/4):")
    results_4.update(generate_local_xml(net, label_dur_q=1.0, skip_filenames=annotated))
    write_generated(results_4, TSD_GEN_4)

    print("\nGenerating predictions (1/8 granularity):")
    results_8 = generate_chorales(net, label_dur_q=0.5)
    print("\n  French Suite XML files (1/8):")
    results_8.update(generate_local_xml(net, label_dur_q=0.5, skip_filenames=annotated))
    write_generated(results_8, TSD_GEN_8)

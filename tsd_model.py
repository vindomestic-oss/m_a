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

def lofo_eval(tsd_data: dict):
    """Leave-one-file-out cross-validation."""
    files = list(tsd_data.keys())
    correct = total = 0
    for held_out in files:
        train_data = {k: v for k, v in tsd_data.items() if k != held_out}
        X_tr, y_tr = build_dataset(train_data)
        if len(X_tr) < 10:
            continue
        net = TSDNet()
        net.train(X_tr, y_tr, verbose=False)
        path = find_file(held_out)
        if path is None:
            continue
        bar_dur_q, beats_per_bar, labels = tsd_data[held_out]
        feats = extract_features(path, bar_dur_q, len(labels), beats_per_bar)
        if feats is None:
            continue
        n = min(len(feats), len(labels))
        preds = net.predict(feats[:n])
        c = sum(IDX_LABEL[p] == labels[i] for i, p in enumerate(preds))
        print(f"  {held_out:50s}  {c}/{n} = {c/n:.0%}")
        correct += c
        total += n
    print(f"\nLOFO accuracy: {correct}/{total} = {correct/total:.1%}")

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
    eval_mode = '--eval' in sys.argv

    print("Loading TSD.txt...")
    tsd_data = load_tsd_data()
    print(f"  {len(tsd_data)} annotated files")

    if eval_mode:
        print("\nLeave-one-file-out cross-validation:")
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

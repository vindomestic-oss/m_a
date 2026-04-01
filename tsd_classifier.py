#!/usr/bin/env python3
"""
TSD harmonic function classifier.

Reads TSD.txt (filename, metre, tsd_string), extracts chord features from
score files at each beat, trains a small bidirectional Transformer encoder
to classify each beat as T / S / D.

Usage:
  python tsd_classifier.py              # train + eval
  python tsd_classifier.py --eval       # eval only (load best.pt)
  python tsd_classifier.py --predict wtc1p01.krn 1/2   # predict unlabelled file
"""

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

sys.path.insert(0, os.path.dirname(__file__))
import kern_reader as kr

BASE_DIR   = Path(__file__).parent
TSD_FILE   = BASE_DIR / 'TSD.txt'
CKPT_DIR   = BASE_DIR / 'checkpoints_tsd'

# Search paths for score files
SEARCH_DIRS = [
    BASE_DIR / 'kern' / 'musedata' / 'bach' / 'keyboard' / 'wtc-1',
    BASE_DIR / 'kern' / 'musedata' / 'bach' / 'keyboard' / 'wtc-2',
    BASE_DIR / 'kern' / 'osu' / 'classical' / 'bach' / 'wtc-1',
    BASE_DIR / 'kern' / 'osu' / 'classical' / 'bach' / 'wtc-2',
    BASE_DIR / 'kern' / 'osu' / 'classical' / 'bach' / 'inventions',
    BASE_DIR / 'kern' / 'musedata' / 'bach' / 'chorales',
    BASE_DIR / 'kern' / 'users' / 'craig' / 'classical' / 'bach' / 'violin',
    BASE_DIR / 'kern' / 'users' / 'craig' / 'classical' / 'bach' / 'cello',
    BASE_DIR / 'lilypond' / 'musicxml',
]

LABEL2ID = {'T': 0, 'S': 1, 'D': 2}
ID2LABEL = {0: 'T', 1: 'S', 2: 'D'}

# model hyperparams
D_MODEL  = 64
N_HEADS  = 4
N_LAYERS = 3
D_FF     = 256
DROPOUT  = 0.2
MAX_SEQ  = 512

# training
BATCH_SIZE   = 8
LR           = 1e-3
EPOCHS       = 80
GRAD_CLIP    = 1.0
VAL_SPLIT    = 0.15
SEED         = 42
WEIGHT_DECAY = 0.05


# ── file lookup ───────────────────────────────────────────────────────────────

def find_score_file(filename: str) -> Path | None:
    """Search SEARCH_DIRS for filename, return full path or None."""
    for d in SEARCH_DIRS:
        p = d / filename
        if p.exists():
            return p
    # fallback: recursive search under BASE_DIR
    for p in BASE_DIR.rglob(filename):
        return p
    return None


# ── metre parsing ─────────────────────────────────────────────────────────────

def metre_to_beat_dur_q(metre: str) -> float:
    """Bar duration in quarter notes: '3/4' → 3.0,  '1/2' → 4.0,  '6/8' → 3.0"""
    num, den = metre.split('/')
    return int(num) * 4.0 / int(den)


# ── score feature extraction ──────────────────────────────────────────────────

def _load_content(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == '.mxl':
        import zipfile
        with zipfile.ZipFile(path) as z:
            xml_name = next(
                n for n in z.namelist()
                if n.lower().endswith(('.xml', '.musicxml')) and 'META' not in n
            )
            raw = z.read(xml_name)
            if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                return raw.decode('utf-16')
            elif raw[:3] == b'\xef\xbb\xbf':
                return raw.decode('utf-8-sig')
            return raw.decode('utf-8', errors='replace')
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def extract_beat_features(path: Path, beat_dur_q: float):
    """
    Returns list of beat feature vectors (one per beat).
    Each vector: float32 tensor of shape (24,)
      [0:12]  = pitch-class weights (duration-weighted, normalised)
      [12:24] = bass pitch-class one-hot
    Returns None on failure.
    """
    try:
        content = _load_content(path)
        ext = path.suffix.lower()
        if ext == '.krn':
            content = kr.prepare_grand_staff(content)
            content = kr.add_beam_markers(content)
        kr._vtk.setOptions({
            'pageWidth': 2200, 'adjustPageHeight': True,
            'scale': 35, 'font': 'Leipzig',
        })
        if not kr._vtk.loadData(content):
            return None
        mei_str = kr._vtk.getMEI()
        voices, _ = kr._voice_notes_from_mei(mei_str)
    except Exception as e:
        print(f"  [ERR] {path.name}: {e}")
        return None

    # flatten all notes from all voices
    all_notes = []   # (onset_q, dur_q, midi)
    for note_list in voices.values():
        for nid, pname, oct_int, dur_q, midi, onset_q in note_list:
            all_notes.append((onset_q, dur_q, midi))

    if not all_notes:
        return None

    total_dur = max(onset + dur for onset, dur, _ in all_notes)
    n_beats   = max(1, round(total_dur / beat_dur_q))

    feats = []
    for i in range(n_beats):
        t0 = i * beat_dur_q
        t1 = t0 + beat_dur_q

        # notes sounding during [t0, t1)
        pc_weight = [0.0] * 12
        bass_midi = None
        for onset, dur, midi in all_notes:
            overlap = min(onset + dur, t1) - max(onset, t0)
            if overlap <= 0:
                continue
            pc = midi % 12
            pc_weight[pc] += overlap
            if bass_midi is None or midi < bass_midi:
                bass_midi = midi

        # normalise pc weights
        total = sum(pc_weight) or 1.0
        pc_norm = [w / total for w in pc_weight]

        # bass one-hot
        bass_oh = [0.0] * 12
        if bass_midi is not None:
            bass_oh[bass_midi % 12] = 1.0

        feats.append(pc_norm + bass_oh)

    return feats   # list of 24-dim lists


# ── TSD string parsing ────────────────────────────────────────────────────────

def parse_tsd(tsd_str: str) -> list[int]:
    """Extract sequence of T/S/D label ids, ignoring all other chars."""
    return [LABEL2ID[c] for c in tsd_str if c in LABEL2ID]


# ── dataset ───────────────────────────────────────────────────────────────────

def load_dataset(tsd_file: Path) -> list[dict]:
    """
    Returns list of records:
      {'filename': str, 'feats': [[24 floats], ...], 'labels': [int, ...]}
    Lengths of feats and labels must match (shorter side is truncated).
    """
    records = []
    with open(tsd_file, encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 3:
                print(f"  [SKIP] line {lineno}: expected 3 tab-separated columns")
                continue
            filename, metre, tsd_str = parts[0], parts[1], parts[2]

            labels = parse_tsd(tsd_str)
            if not labels:
                print(f"  [SKIP] {filename}: empty TSD string")
                continue

            path = find_score_file(filename)
            if path is None:
                print(f"  [SKIP] {filename}: file not found")
                continue

            beat_dur_q = metre_to_beat_dur_q(metre)
            print(f"  Loading {filename}  ({len(labels)} beats, beat={beat_dur_q}q)…", flush=True)
            feats = extract_beat_features(path, beat_dur_q)
            if feats is None:
                print(f"  [ERR]  {filename}: feature extraction failed")
                continue

            # align: truncate to shorter
            n = min(len(feats), len(labels))
            if abs(len(feats) - len(labels)) > 4:
                print(f"  [WARN] {filename}: score beats={len(feats)}  TSD beats={len(labels)}")
            feats  = feats[:n]
            labels = labels[:n]

            records.append({'filename': filename, 'feats': feats, 'labels': labels})

    print(f"Loaded {len(records)} pieces.")
    return records


def augment_transpositions(records: list[dict]) -> list[dict]:
    """
    Return records augmented with all 12 transpositions.
    Pitch-class features are cyclically shifted; labels unchanged.
    """
    out = []
    for rec in records:
        for shift in range(12):
            if shift == 0:
                out.append(rec)
                continue
            new_feats = []
            for f in rec['feats']:
                pc  = f[:12]
                bas = f[12:]
                pc_s  = pc[-shift:] + pc[:-shift]
                bas_s = bas[-shift:] + bas[:-shift]
                new_feats.append(pc_s + bas_s)
            out.append({'filename': rec['filename'],
                        'feats': new_feats, 'labels': rec['labels']})
    return out


class TSDDataset(Dataset):
    def __init__(self, records: list[dict], seq_len: int = MAX_SEQ):
        self.seq_len = seq_len
        self.windows = []
        for rec in records:
            feats  = rec['feats']
            labels = rec['labels']
            n = len(feats)
            # sliding window with stride = seq_len // 2
            stride = max(1, seq_len // 2)
            for start in range(0, max(1, n - seq_len + 1), stride):
                end = min(start + seq_len, n)
                self.windows.append((feats[start:end], labels[start:end]))
            # always include the last window
            if n > seq_len:
                self.windows.append((feats[n - seq_len:], labels[n - seq_len:]))

    def __len__(self):
        return len(self.windows)

    def __getitem__(self, idx):
        feats, labels = self.windows[idx]
        L = len(feats)
        # pad to seq_len
        pad = self.seq_len - L
        feat_t  = torch.zeros(self.seq_len, 24)
        label_t = torch.full((self.seq_len,), -100, dtype=torch.long)  # -100 = ignore
        feat_t[:L]  = torch.tensor(feats,  dtype=torch.float32)
        label_t[:L] = torch.tensor(labels, dtype=torch.long)
        return feat_t, label_t


# ── model ──────────────────────────────────────────────────────────────────────

class TSDModel(nn.Module):
    """
    Bidirectional Transformer encoder over beat-chord feature sequences.
    Predicts T/S/D at every beat position.
    """
    def __init__(self, d_model=D_MODEL, n_heads=N_HEADS, n_layers=N_LAYERS,
                 d_ff=D_FF, dropout=DROPOUT):
        super().__init__()
        self.input_proj = nn.Linear(24, d_model)
        self.pos_enc    = nn.Embedding(MAX_SEQ, d_model)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_ff,
            dropout=dropout, batch_first=True, norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(layer, num_layers=n_layers,
                                                  enable_nested_tensor=False)
        self.head = nn.Linear(d_model, 3)
        self.drop = nn.Dropout(dropout)
        self._init_weights()

    def _init_weights(self):
        nn.init.xavier_uniform_(self.input_proj.weight)
        nn.init.zeros_(self.input_proj.bias)
        nn.init.normal_(self.pos_enc.weight, std=0.02)

    def forward(self, x):
        # x: (B, L, 24)
        B, L, _ = x.shape
        pos = torch.arange(L, device=x.device).unsqueeze(0)
        h = self.drop(self.input_proj(x) + self.pos_enc(pos))
        # no causal mask → bidirectional
        h = self.transformer(h)
        return self.head(h)   # (B, L, 3)


# ── train / eval ──────────────────────────────────────────────────────────────

def run_epoch(model, loader, optimizer, device, train=True):
    model.train(train)
    total_loss = 0.0
    correct = total = 0
    ctx = torch.enable_grad() if train else torch.no_grad()
    with ctx:
        for feats, labels in loader:
            feats  = feats.to(device)
            labels = labels.to(device)
            logits = model(feats)           # (B, L, 3)
            loss = F.cross_entropy(
                logits.view(-1, 3), labels.view(-1), ignore_index=-100
            )
            if train:
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
                optimizer.step()
            total_loss += loss.item()
            mask = labels.view(-1) != -100
            pred = logits.view(-1, 3).argmax(-1)
            correct += (pred[mask] == labels.view(-1)[mask]).sum().item()
            total   += mask.sum().item()
    acc = correct / max(total, 1)
    return total_loss / max(len(loader), 1), acc


# ── predict ───────────────────────────────────────────────────────────────────

def predict(model, feats_list: list, device) -> list[str]:
    """Predict TSD labels for a list of beat feature vectors."""
    model.eval()
    n = len(feats_list)
    results = []
    with torch.no_grad():
        for start in range(0, n, MAX_SEQ):
            chunk = feats_list[start:start + MAX_SEQ]
            L = len(chunk)
            x = torch.zeros(1, MAX_SEQ, 24)
            x[0, :L] = torch.tensor(chunk, dtype=torch.float32)
            x = x.to(device)
            logits = model(x)[0, :L]   # (L, 3)
            preds = logits.argmax(-1).cpu().tolist()
            results.extend([ID2LABEL[p] for p in preds])
    return results


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs',  type=int,   default=EPOCHS)
    parser.add_argument('--lr',      type=float, default=LR)
    parser.add_argument('--device',  default='auto')
    parser.add_argument('--eval',    action='store_true')
    parser.add_argument('--predict', nargs=2, metavar=('FILE', 'METRE'),
                        help='Predict TSD for an unlabelled score file')
    args = parser.parse_args()

    device = ('cuda' if torch.cuda.is_available() else 'cpu') \
             if args.device == 'auto' else args.device
    print(f"Device: {device}")

    random.seed(SEED)
    torch.manual_seed(SEED)

    CKPT_DIR.mkdir(exist_ok=True)
    model = TSDModel().to(device)
    n_p = sum(p.numel() for p in model.parameters())
    print(f"Parameters: {n_p:,}")

    # ── predict mode ──────────────────────────────────────────────────────────
    if args.predict:
        filename, metre = args.predict
        ckpt_path = CKPT_DIR / 'best.pt'
        if not ckpt_path.exists():
            print("No checkpoint found. Train first.")
            return
        model.load_state_dict(torch.load(ckpt_path, map_location=device)['model'])
        path = find_score_file(filename)
        if path is None:
            print(f"File not found: {filename}")
            return
        feats = extract_beat_features(path, metre_to_beat_dur_q(metre))
        if feats is None:
            print("Feature extraction failed.")
            return
        labels = predict(model, feats, device)
        print(''.join(labels))
        return

    # ── load data ─────────────────────────────────────────────────────────────
    print(f"Loading {TSD_FILE} …")
    records = load_dataset(TSD_FILE)
    if not records:
        print("No data loaded. Check TSD.txt and score file paths.")
        return

    random.shuffle(records)
    n_val    = max(1, int(len(records) * VAL_SPLIT))
    val_rec  = records[:n_val]
    train_rec = records[n_val:]

    print(f"Train: {len(train_rec)} pieces   Val: {len(val_rec)} pieces")
    print("Augmenting with 12 transpositions…")
    train_rec = augment_transpositions(train_rec)
    print(f"After augmentation: {len(train_rec)} pieces")

    train_ds = TSDDataset(train_rec)
    val_ds   = TSDDataset(val_rec)
    print(f"Train windows: {len(train_ds)}   Val windows: {len(val_ds)}")

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs, eta_min=args.lr / 10)

    start_epoch = 0
    best_val    = float('inf')

    if args.eval:
        ckpt_path = CKPT_DIR / 'best.pt'
        if ckpt_path.exists():
            model.load_state_dict(torch.load(ckpt_path, map_location=device)['model'])
        val_loss, val_acc = run_epoch(model, val_loader, None, device, train=False)
        print(f"Val loss: {val_loss:.4f}  acc: {val_acc:.3f}")
        return

    print(f"\nTraining {args.epochs} epochs…")
    for epoch in range(start_epoch, args.epochs):
        tr_loss, tr_acc = run_epoch(model, train_loader, optimizer, device, train=True)
        va_loss, va_acc = run_epoch(model, val_loader,   None,      device, train=False)
        scheduler.step()

        improved = va_loss < best_val
        if improved:
            best_val = va_loss
            torch.save({'epoch': epoch, 'model': model.state_dict(),
                        'best_val': best_val},
                       CKPT_DIR / 'best.pt')

        print(f"Epoch {epoch+1:3d}/{args.epochs}  "
              f"train={tr_loss:.4f} acc={tr_acc:.3f}  "
              f"val={va_loss:.4f} acc={va_acc:.3f}"
              f"{'  *' if improved else ''}", flush=True)

        torch.save({'epoch': epoch, 'model': model.state_dict(),
                    'best_val': best_val},
                   CKPT_DIR / 'latest.pt')

    print(f"\nBest val loss: {best_val:.4f}   Checkpoints: {CKPT_DIR}/")


if __name__ == '__main__':
    main()

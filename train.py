#!/usr/bin/env python3
"""
Bach motif-aware music model — causal Transformer, next-token prediction.

Two interleaved token types:
  N (note):  pitch, duration, phase, motif_membership, vertical_intervals
  M (motif): type_id, transposition, inversion, distance_from_prev

Usage:
  python train.py                        # train with defaults
  python train.py --epochs 100 --lr 1e-3
  python train.py --resume checkpoints/latest.pt
  python train.py --eval               # eval only
"""

import argparse
import json
import math
import os
import random
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

# ── paths ──────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
DATA_PATH = BASE_DIR / 'train_data.jsonl'
CKPT_DIR  = BASE_DIR / 'checkpoints'

# ── vocabulary sizes (from actual data) ───────────────────────────────────────
PITCH_VOCAB = 45      # diatonic pitch 0-44 (range observed in Bach kern files)
DUR_VOCAB   = 81      # duration in 16ths 0-80
PHASE_VOCAB = 16      # metric phase 0-15
TYPE_VOCAB  = 4539    # motif type 0-4537; 4538 = NONE (not in motif)
POS_VOCAB   = 100     # position within motif 0-99
DP0_VOCAB   = 52      # relative transposition: stored as dp0+25, range 0-51
DIST_VOCAB  = 35      # distance between motif occurrences (log-bucketed, see below)
VERT_VOCAB  = 28      # vertical interval: 0=padding, 1-27 = diatonic interval
N_TOK_TYPES = 2       # 0=N, 1=M

# ── model hyperparameters ──────────────────────────────────────────────────────
D_MODEL  = 256
N_HEADS  = 4
N_LAYERS = 4
D_FF     = 1024
DROPOUT  = 0.1
MAX_SEQ  = 512

# ── training ──────────────────────────────────────────────────────────────────
BATCH_SIZE = 8
LR         = 3e-4
EPOCHS     = 80
GRAD_CLIP  = 1.0
VAL_SPLIT  = 0.1
SEED       = 42


# ── encoding helpers ──────────────────────────────────────────────────────────

def _dp0_bucket(dp0: int) -> int:
    """Relative transposition -25..+26 → 0..51."""
    return min(max(dp0 + 25, 0), DP0_VOCAB - 1)


# log-spaced distance breaks: covers 0..5760
_DIST_BREAKS = [0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128,
                192, 256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096, 5760]


def _dist_bucket(dist: int) -> int:
    for i, b in enumerate(_DIST_BREAKS):
        if dist <= b:
            return i
    return len(_DIST_BREAKS) - 1


# ── dataset ───────────────────────────────────────────────────────────────────

def encode_piece(tokens: list) -> dict:
    """Encode a list of token dicts into parallel integer lists."""
    tok_type = []
    pitch, dur, phase = [], [], []
    mtype, mpos, mdp0, minv = [], [], [], []
    vert = []     # list of lists (variable length, max 6)
    motif_id, dist = [], []

    for tok in tokens:
        if tok['t'] == 'N':
            tok_type.append(0)
            pitch.append(min(tok['p'], PITCH_VOCAB - 1))
            dur.append(min(tok['d'], DUR_VOCAB - 1))
            phase.append(min(tok.get('ph', 0), PHASE_VOCAB - 1))
            m = tok.get('m')
            if m:
                mtype.append(min(m[0], TYPE_VOCAB - 2))
                mpos.append(min(m[1], POS_VOCAB - 1))
                mdp0.append(_dp0_bucket(m[2]))
                minv.append(int(bool(m[3])))
            else:
                mtype.append(TYPE_VOCAB - 1)  # NONE
                mpos.append(0)
                mdp0.append(25)               # transposition 0
                minv.append(0)
            # vertical intervals: shift by +1 so 0 = padding
            vert.append([min(v, VERT_VOCAB - 1) for v in tok.get('v', [])])
            motif_id.append(0)
            dist.append(0)
        else:  # M token
            tok_type.append(1)
            pitch.append(0); dur.append(0); phase.append(0)
            mtype.append(0); mpos.append(0); mdp0.append(25); minv.append(0)
            vert.append([])
            motif_id.append(min(tok['id'], TYPE_VOCAB - 2))
            dist.append(_dist_bucket(tok.get('dist', 0)))

    return dict(tok_type=tok_type, pitch=pitch, dur=dur, phase=phase,
                mtype=mtype, mpos=mpos, mdp0=mdp0, minv=minv,
                vert=vert, motif_id=motif_id, dist=dist)


class BachDataset(Dataset):
    def __init__(self, records: list, seq_len: int = MAX_SEQ, stride: int = 256):
        self.seq_len = seq_len
        self.windows = []   # (encoded_dict, start_idx)

        for rec in records:
            enc = encode_piece(rec['tokens'])
            n   = len(enc['tok_type'])
            if n < 4:
                continue
            starts = list(range(0, max(1, n - seq_len), stride))
            if not starts or starts[-1] + seq_len < n:
                starts.append(max(0, n - seq_len))
            for s in starts:
                self.windows.append((enc, s))

    def __len__(self):
        return len(self.windows)

    def __getitem__(self, idx):
        enc, start = self.windows[idx]
        L = self.seq_len

        def grab(key, pad=0):
            arr = enc[key][start: start + L]
            if len(arr) < L:
                arr = arr + [pad] * (L - len(arr))
            return torch.tensor(arr, dtype=torch.long)

        # vertical intervals: pad each position to 6 slots, 0=no interval
        vert_raw = enc['vert'][start: start + L]
        vert_t = torch.zeros(L, 6, dtype=torch.long)
        for i, iv_list in enumerate(vert_raw[:L]):
            for j, v in enumerate(iv_list[:6]):
                vert_t[i, j] = v   # 0 = padding (padding_idx in emb)

        return {
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
        }


# ── model ──────────────────────────────────────────────────────────────────────

class MusicModel(nn.Module):
    """
    Causal Transformer over interleaved note/motif tokens.
    Each token position predicts the next token's fields.
    """

    def __init__(self, d_model=D_MODEL, n_heads=N_HEADS, n_layers=N_LAYERS,
                 d_ff=D_FF, dropout=DROPOUT):
        super().__init__()
        self.d_model = d_model
        e = d_model // 8   # base embedding dim per field

        # ── note token embeddings ──────────────────────────────────────────────
        self.emb_pitch  = nn.Embedding(PITCH_VOCAB,     e * 2)
        self.emb_dur    = nn.Embedding(DUR_VOCAB,       e)
        self.emb_phase  = nn.Embedding(PHASE_VOCAB,     e)
        self.emb_mtype  = nn.Embedding(TYPE_VOCAB,      e)      # membership type
        self.emb_mpos   = nn.Embedding(POS_VOCAB,       e // 2)
        self.emb_mdp0   = nn.Embedding(DP0_VOCAB,       e // 2)
        self.emb_minv   = nn.Embedding(2,               e // 4)
        self.emb_vert   = nn.Embedding(VERT_VOCAB,      e // 2, padding_idx=0)
        note_dim = e*2 + e + e + e + e//2 + e//2 + e//4 + e//2
        self.note_proj  = nn.Linear(note_dim, d_model)

        # ── motif token embeddings ─────────────────────────────────────────────
        self.emb_mid    = nn.Embedding(TYPE_VOCAB - 1,  e * 2)  # motif id
        self.emb_mdp0m  = nn.Embedding(DP0_VOCAB,       e)      # transposition
        self.emb_minvm  = nn.Embedding(2,               e // 2) # inversion flag
        self.emb_dist   = nn.Embedding(DIST_VOCAB,      e)
        motif_dim = e*2 + e + e//2 + e
        self.motif_proj = nn.Linear(motif_dim, d_model)

        # ── shared ────────────────────────────────────────────────────────────
        self.emb_toktype = nn.Embedding(N_TOK_TYPES, d_model)
        self.pos_enc     = nn.Embedding(MAX_SEQ,     d_model)

        # ── transformer ───────────────────────────────────────────────────────
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_ff,
            dropout=dropout, batch_first=True, norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(layer, num_layers=n_layers,
                                                  enable_nested_tensor=False)

        # ── output heads ──────────────────────────────────────────────────────
        self.head_type  = nn.Linear(d_model, N_TOK_TYPES)   # predict N or M
        self.head_pitch = nn.Linear(d_model, PITCH_VOCAB)   # N: pitch
        self.head_dur   = nn.Linear(d_model, DUR_VOCAB)     # N: duration
        self.head_mid   = nn.Linear(d_model, TYPE_VOCAB-1)  # M: motif type
        self.head_dist  = nn.Linear(d_model, DIST_VOCAB)    # M: distance

        self.drop = nn.Dropout(dropout)
        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Embedding):
                nn.init.normal_(m.weight, std=0.02)
                if m.padding_idx is not None:
                    m.weight.data[m.padding_idx].zero_()
            elif isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def _note_emb(self, b):
        ev = self.emb_vert(b['vert']).sum(dim=2)   # (B,L,e//2) — set encoding
        return self.note_proj(torch.cat([
            self.emb_pitch(b['pitch']),
            self.emb_dur(b['dur']),
            self.emb_phase(b['phase']),
            self.emb_mtype(b['mtype']),
            self.emb_mpos(b['mpos']),
            self.emb_mdp0(b['mdp0']),
            self.emb_minv(b['minv']),
            ev,
        ], dim=-1))

    def _motif_emb(self, b):
        return self.motif_proj(torch.cat([
            self.emb_mid(b['motif_id']),
            self.emb_mdp0m(b['mdp0']),
            self.emb_minvm(b['minv']),
            self.emb_dist(b['dist']),
        ], dim=-1))

    def forward(self, b):
        B, L = b['tok_type'].shape
        device = b['tok_type'].device

        note_e  = self._note_emb(b)
        motif_e = self._motif_emb(b)
        is_m    = b['tok_type'].unsqueeze(-1).float()
        x = note_e * (1 - is_m) + motif_e * is_m

        pos = torch.arange(L, device=device).unsqueeze(0)
        x = x + self.emb_toktype(b['tok_type']) + self.pos_enc(pos)
        x = self.drop(x)

        mask = nn.Transformer.generate_square_subsequent_mask(L, device=device)
        x = self.transformer(x, mask=mask, is_causal=True)

        return {
            'type':  self.head_type(x),
            'pitch': self.head_pitch(x),
            'dur':   self.head_dur(x),
            'mid':   self.head_mid(x),
            'dist':  self.head_dist(x),
        }


# ── loss ──────────────────────────────────────────────────────────────────────

def compute_loss(logits, batch):
    def S(t):   return t[:, 1:].contiguous()
    def SL(k):  return logits[k][:, :-1].contiguous()

    tgt_type = S(batch['tok_type'])
    is_note  = (tgt_type == 0).float()
    is_motif = (tgt_type == 1).float()
    n_note   = is_note.sum().clamp(min=1)
    n_motif  = is_motif.sum().clamp(min=1)

    loss_type = F.cross_entropy(
        SL('type').view(-1, N_TOK_TYPES), tgt_type.view(-1))

    def mce(logit_k, tgt_k, mask, n):
        lgt  = SL(logit_k).view(-1, SL(logit_k).shape[-1])
        tgt  = S(batch[tgt_k]).view(-1)
        loss = F.cross_entropy(lgt, tgt, reduction='none')
        return (loss * mask.view(-1)).sum() / n

    loss_pitch = mce('pitch', 'pitch',    is_note,  n_note)
    loss_dur   = mce('dur',   'dur',      is_note,  n_note)
    loss_mid   = mce('mid',   'motif_id', is_motif, n_motif)
    loss_dist  = mce('dist',  'dist',     is_motif, n_motif)

    total = loss_type + 2.0 * loss_pitch + 1.5 * loss_dur + loss_mid + 0.5 * loss_dist
    return total, {
        'type': loss_type.item(), 'pitch': loss_pitch.item(),
        'dur':  loss_dur.item(),  'mid':   loss_mid.item(),
        'dist': loss_dist.item(),
    }


# ── train / eval loops ────────────────────────────────────────────────────────

def run_epoch(model, loader, optimizer, device, train=True):
    model.train(train)
    total = 0.0
    ctx = torch.enable_grad() if train else torch.no_grad()
    with ctx:
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            logits = model(batch)
            loss, parts = compute_loss(logits, batch)
            if train:
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
                optimizer.step()
            total += loss.item()
    return total / max(len(loader), 1)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs',  type=int,   default=EPOCHS)
    parser.add_argument('--lr',      type=float, default=LR)
    parser.add_argument('--batch',   type=int,   default=BATCH_SIZE)
    parser.add_argument('--d-model', type=int,   default=D_MODEL)
    parser.add_argument('--layers',  type=int,   default=N_LAYERS)
    parser.add_argument('--seq-len', type=int,   default=MAX_SEQ)
    parser.add_argument('--device',  default='auto')
    parser.add_argument('--resume',  default=None)
    parser.add_argument('--eval',    action='store_true')
    args = parser.parse_args()

    device = ('cuda' if torch.cuda.is_available() else 'cpu') \
             if args.device == 'auto' else args.device
    print(f"Device: {device}")

    random.seed(SEED)
    torch.manual_seed(SEED)

    # ── data ──────────────────────────────────────────────────────────────────
    print(f"Loading {DATA_PATH} ...")
    records = [json.loads(l) for l in open(DATA_PATH, encoding='utf-8')]
    random.shuffle(records)
    n_val     = max(1, int(len(records) * VAL_SPLIT))
    val_rec   = records[:n_val]
    train_rec = records[n_val:]
    print(f"  Train: {len(train_rec)} files   Val: {len(val_rec)} files")

    seq_len = args.seq_len
    train_ds = BachDataset(train_rec, seq_len=seq_len, stride=seq_len // 2)
    val_ds   = BachDataset(val_rec,   seq_len=seq_len, stride=seq_len)
    print(f"  Train windows: {len(train_ds)}   Val windows: {len(val_ds)}")

    train_loader = DataLoader(train_ds, batch_size=args.batch, shuffle=True,
                              num_workers=0, pin_memory=(device == 'cuda'))
    val_loader   = DataLoader(val_ds,   batch_size=args.batch, shuffle=False,
                              num_workers=0, pin_memory=(device == 'cuda'))

    # ── model ─────────────────────────────────────────────────────────────────
    model = MusicModel(d_model=args.d_model, n_layers=args.layers).to(device)
    n_p   = sum(p.numel() for p in model.parameters())
    print(f"Parameters: {n_p:,}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs, eta_min=args.lr / 10)

    start_epoch = 0
    best_val    = float('inf')

    if args.resume:
        ckpt = torch.load(args.resume, map_location=device)
        model.load_state_dict(ckpt['model'])
        optimizer.load_state_dict(ckpt['optimizer'])
        start_epoch = ckpt['epoch'] + 1
        best_val    = ckpt.get('best_val', float('inf'))
        print(f"Resumed from epoch {start_epoch}  best_val={best_val:.4f}")

    if args.eval:
        val_loss = run_epoch(model, val_loader, None, device, train=False)
        print(f"Val loss: {val_loss:.4f}")
        return

    CKPT_DIR.mkdir(exist_ok=True)

    # ── training loop ─────────────────────────────────────────────────────────
    print(f"\nTraining {args.epochs} epochs on {device}...")
    for epoch in range(start_epoch, args.epochs):
        tr_loss = run_epoch(model, train_loader, optimizer, device, train=True)
        va_loss = run_epoch(model, val_loader,   None,      device, train=False)
        scheduler.step()

        improved = va_loss < best_val
        if improved:
            best_val = va_loss
            torch.save({'epoch': epoch, 'model': model.state_dict(),
                        'optimizer': optimizer.state_dict(),
                        'best_val': best_val, 'args': vars(args)},
                       CKPT_DIR / 'best.pt')

        print(f"Epoch {epoch+1:3d}/{args.epochs}  "
              f"train={tr_loss:.4f}  val={va_loss:.4f}"
              f"{'  *' if improved else ''}", flush=True)

        torch.save({'epoch': epoch, 'model': model.state_dict(),
                    'optimizer': optimizer.state_dict(),
                    'best_val': best_val, 'args': vars(args)},
                   CKPT_DIR / 'latest.pt')

    print(f"\nBest val: {best_val:.4f}   Checkpoints: {CKPT_DIR}/")


if __name__ == '__main__':
    main()

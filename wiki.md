# Project Wiki

## Overview

This project is a **kern file browser and motif analysis tool** for Humdrum kern music files. It renders scores in the browser using verovio and automatically finds repeating melodic motifs, with statistical analysis of occurrence counts.

---

## Running the App

```
python kern_mdl.py
```

- Opens a tkinter file browser (right side of screen, 480×800 px)
- Starts an HTTP server on port 8765
- Opens Chrome/Edge on the left side of the screen at http://127.0.0.1:8765/
- Click any file in the browser to render it

**Do not close the tkinter window** — the HTTP server is a daemon thread and dies with the main process.

---

## File Collections

Eight collections are shown in the browser (from the `kern/` folder):

| Collection | Path |
|---|---|
| WTC1 Preludes | `kern/musedata/bach/keyboard/wtc-1/` |
| WTC2 Preludes | `kern/musedata/bach/keyboard/wtc-2/` |
| WTC1 Fugues | `kern/osu/classical/bach/wtc-1/` |
| WTC2 Fugues | `kern/osu/classical/bach/wtc-2/` |
| Inventions | `kern/osu/classical/bach/inventions/` |
| Chorales | `kern/musedata/bach/chorales/` |
| Violin Partitas/Sonatas | `kern/users/craig/classical/bach/violin/` |
| Cello Suites | `kern/users/craig/classical/bach/cello/` |

---

## Architecture

```
kern_mdl.py
├── FileBrowser (tkinter, main thread)
│   └── file list, search, metadata strip
├── start_server() (daemon thread)
│   └── HTTP server on port 8765
├── load_file_bg() (thread per file selection)
│   └── spawns subprocess → result via Queue → updates _state
├── _render_worker() (subprocess)
│   └── render_score() → HTML → Queue
└── Browser (Chrome/Edge subprocess)
    └── /events (SSE) → auto-reload on score change
```

Verovio is isolated in a subprocess to catch segfaults without crashing the app.

---

## Motif Analysis

### What it does

For each loaded score, the app finds all repeating melodic patterns across all voices and displays them in a table above the score. Notes belonging to each motif are colored; clicking a row draws boxes around all occurrences in the SVG.

### Pipeline

1. **MEI extraction** — verovio converts kern → MEI XML; the app parses it
2. **Per-voice note sequences** — absolute onset times, durations, pitches
3. **Diatonic intervals** — minor/major distinction ignored (C→E = C→Eb = third)
4. **Metric phase** — position of first note within its beat (0 = downbeat)
5. **Pattern finding** — sliding window, non-overlapping greedy selection per voice
6. **Inversion merging** — direct and inverted forms of a motif counted together
7. **MDL scoring** — patterns ranked by description-length saving

### Motif Table Columns

| Column | Meaning |
|---|---|
| Мотив | Motif name with metric phase marker |
| Паттерн | Interval sequence with durations |
| Вхожд. | Occurrence count |
| Нот | Number of notes in pattern |
| MDL | MDL score (bold = positive) |

Click **Вхожд.** header to sort by count; click **MDL** to sort by MDL score.

### Inversion counts

When a motif has both direct and inverted occurrences, the count shows:
`×N_dir ⇅N_inv ⊕N_all`

Each part is clickable to show only direct, only inverted, or all occurrences.

### Note coloring

- Notes start black (no color on page load)
- Clicking a motif row colors its notes (persists after deactivating)
- Colors accumulate across multiple clicked motifs

---

## Manual Search

The search input above the motif table accepts these formats:

### Interval search
```
dur[,dur...];phase;+iv-iv...
```
- `dur` — note duration as fraction, e.g. `1/16`; operators like `>1/16`, `<=1/8` allowed
- `phase` — metric phase of first note (0 = downbeat)
- intervals — signed diatonic steps, e.g. `+2-1+3`

### Rhythm-only search
```
dur[,dur...];phase
```
Matches any intervals between notes of the given durations.

### Contour search
```
dur[,dur...];phase;+-=...
```
Only `+`/`-`/`=` in the interval part (ascending/descending/unison), no digits.

### Inversion modifier
Append `;inv` to find both direct and inverted form.

### Examples
```
1/16;0;+2-1+3       — specific intervals
3/16,1/16;0         — rhythm only (dotted eighth + sixteenth)
1/16;0;-+---        — contour only
1/16;0;+-+;inv      — with inversion
1/24;0;-1-1         — triplet sixteenths
```

Clicking a motif row in the table populates the search field with its pattern.

---

## Triplet Handling

Triplet durations are represented as fractions:
- Triplet eighth = `1/12` of a whole note = `1/3` of a quarter note
- Triplet sixteenth = `1/24` of a whole note

The search field uses whole-note fractions (same as displayed in the motif table). Metric phase for triplet notes uses mod-3 so that phase 0, 3 are treated the same.

---

## Meta-Analysis

`meta_analysis.py` runs motif analysis across all kern files (no SVG rendering) and tests whether smooth numbers (2^a × 3^b ≥ 8) are over-represented in occurrence counts.

```bash
python meta_analysis.py
python meta_analysis.py --filter bach --output report/bach.txt
python meta_analysis.py --filter wtc,inventions --output report/bach_keyboard.txt
python meta_analysis.py --lo 8
```

### Statistical tests

Two null models:
- **Uniform prior** — every integer in [8, max] equally likely
- **Log-uniform prior** — weight 1/k (larger numbers intrinsically rarer)

The log-uniform enrichment ratio is the main result. Values above 1.5x suggest non-trivial alignment between motif repetition and binary/ternary metric structure.

### Shift test

Compares smooth density of real counts vs. counts shifted by ±1. If smooth numbers are genuinely over-represented, shifting should reduce their density. The test starts from count ≥ 14 (to avoid boundary effects near 9 and 12).

### Per-composer reports

Reports are stored in `report/`. Run with `--filter <composer>` to generate a report for a specific composer. Comma-separated filters use OR logic.

### Key findings (as of 2026-03-29)

| Corpus | Files | Enrichment (log-uniform) | Shift +1 ratio (≥16) |
|---|---|---|---|
| Bach keyboard (WTC + inventions) | ~60 | 1.80x | ~2x |
| Bach all kern | 135 | 1.80x | 1.37x |
| Mozart | 16 | modest | 1.56x at ≥24 |
| Beethoven | 26 | modest | consistent at ≥16 |
| Frescobaldi | 40 | 1.70x | — |
| Beethoven opus 132 | 1 | 0.31x | — |

**Asymmetry**: the shift+1 effect is consistently stronger than shift-1. This is partly explained by frequency table asymmetry — smooth+1 positions (17, 37) sometimes have higher raw counts than the smooth numbers themselves (16, 36).

---

## Dependencies

| Library | Use |
|---|---|
| `verovio` 6.1.0 | kern → SVG rendering; kern → MEI conversion |
| `music21` | metadata extraction (title, composer, key, time sig) |
| `tkinter` | file browser GUI |
| `multiprocessing` | subprocess isolation for verovio crashes |
| `http.server` | ThreadingTCPServer, port 8765 |

---

## Known Issues

- Verovio prints harmless C++ warnings to stderr (beamSpan, mixed beam, unknown clef types)
- Some chorales cause verovio segfaults → subprocess isolation handles these gracefully
- `ConnectionAbortedError: [WinError 10053]` in HTTP server — harmless (browser closed connection)
- music21 prints `'Rest' object has no attribute 'beams'` for some chorales — harmless

---

## File Layout

```
kern_mdl.py          — primary development file (all new features go here)
kern_reader.py       — synced from kern_mdl.py when explicitly requested
meta_analysis.py     — meta-analysis across all files
smooth_mc.py         — Monte Carlo smooth-number analysis
report/              — per-composer meta-analysis reports
freq_table.json      — frequency table output from last meta_analysis run
kern/                — 1166 kern files across 8 collections
```

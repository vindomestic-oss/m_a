# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```
python kern_reader.py
```

Starts the tkinter file browser + HTTP server on port 8765. The browser opens automatically at http://127.0.0.1:8765/. Click a file in the panel to render it. **Do not close the tkinter window** — the HTTP server runs as a daemon thread and dies with the main process.

## Architecture

- **kern_reader.py** — single-file application
  - `FileBrowser` (tkinter, main thread): file list (filtered to 8 collections), search, metadata strip; window is resizable, 480×800; positioned at right edge of screen (`+{sw-480}+0`); shows only filename (no path) in list
  - `start_server()` (daemon thread): HTTP server on port 8765 serving rendered HTML
  - `load_file_bg()` (thread per selection): spawns a **subprocess** via `multiprocessing` to isolate verovio segfaults; reads result from queue, updates `_state`
  - `_render_worker()` (subprocess): runs `render_score()` in a separate process, puts HTML into a `Queue`
  - Browser connects to `/events` (SSE) and reloads immediately when score changes
  - Browser launched via Chrome/Edge subprocess with `--window-position=0,0 --window-size={sw-480},{sh}` to fill the left side of the screen

## Key functions

- `add_beam_markers(content)` — injects `L`/`J` beam markers into kern files that have none (OSU inventions and WTC fugues):
  - Groups beamable notes (8th–64th) within each beat per spine
  - 8th → `L`/`J`, 16th → `LL`/`JJ`, 32nd → `LLL`/`JJJ`
  - Never crosses barlines; skips files that already have beam markers (musedata WTC preludes)
  - Beat duration derived from `*M` time signature token

- `prepare_grand_staff(content)` — preprocesses kern content before passing to verovio:
  - **Multi-spine files** (≥2 `**kern` columns in header): adds `*staff`/`*clef` tokens if missing
  - **Single-spine files** with `*^` splits: converts to 2-spine grand-staff format by absorbing the first `*^` into a new `**kern\t**kern` header; subsequent splits stay in place as inner voice splits within the treble spine
  - Key fix for musedata WTC preludes (single spine with `*^` splits)

- `render_score(path, version)` — validates file, applies `prepare_grand_staff` + `add_beam_markers`, loads into verovio, renders all pages to SVG, runs motif analysis, returns `(html, n_pages, version, all_seqs, beat_dur_q)`; also stores `all_seqs`/`beat_dur_q` in `_state` for the `/search` endpoint

- `analyze_motifs(vtk, mei_str=None)` — extracts per-voice note sequences from MEI, computes **diatonic** intervals (ignores minor/major distinction), finds repeating motif patterns; accepts pre-fetched `mei_str` to avoid double call to `vtk.getMEI()`

- `get_metadata(path)` — uses music21 to extract title, composer, key, time signature, parts, duration

## Motif analysis pipeline

1. `_voice_notes_from_mei(mei_str)` — parses MEI XML; recurses into `<beam>` and `<tuplet>` containers; tracks **rests, spaces, mRest** to compute correct absolute onset time per note; returns `{(staff_n, layer_n): [(nid, pname, oct_int, dur_quarters, midi, onset_quarters), ...]}`
   - `onset_quarters` = `measure_onset + within_measure_pos` — absolute from piece start
   - Rests and tied-note continuations advance `pos` but are not added to the voice list
   - **Grace notes** (`grace` attribute in MEI, from kern `q`/`Q`) are skipped entirely; pos is NOT advanced (grace notes borrow time from the next note)
   - Time signature parsed from `<scoreDef>` attrs (`meter.count`/`meter.unit`) **or** from a child `<meterSig count=... unit=.../>` inside `<staffDef>` — verovio uses the latter for violin/cello partita files; code falls back to `sd.iter('meterSig')` if attrs absent
   - Returns `(voices_dict, beat_dur_q)` — beat duration in quarter notes (1.0 for 4/4, 1.5 for 9/8 and **3/8**)
   - **Tie merging** (post-pass): kern-sourced MEI uses `tie="i/m/t"` attributes (filtered in `proc_note`); MusicXML-sourced MEI uses standalone `<tie startid=... endid=...>` elements — these are collected after the per-voice pass and used to merge chained tied notes: the tie-end note's duration is added to the tie-start note, and the tie-end note is removed from the voice list. Prevents false unison intervals from cross-barline ties.
2. `_merge_ornamental_slurs(notes, slur_ends)` — merges 2-note slur/phrase pairs where the first note is strictly shorter (ornament/appoggiatura). Slur map built from `<slur>` and `<phrase>` elements (both used by verovio for kern `(...)` markers). Ornament note dropped; its duration added to main note; onset = onset of ornament.
3. `_interval_seq(notes, beat_dur_q=1.0)` — computes diatonic intervals: `oct*7 + diatonic_step(pname)`; minor/major ignored (C→E = C→Eb = 2); returns **8-element tuples** `(interval, dur, nid0, nid1, onset, phase, contiguous, dp0)` per step; `dp0` = absolute diatonic pitch of first note (used for transposition tracking); `phase = _metric_phase(onset, dur, beat_dur_q)`; `contiguous = round((onset0+dur0)*16)==round(onset1*16)` — False if there is a rest between the two notes
4. `_metric_phase(onset_q, dur_q, beat_dur_q=1.0)` — metric phase of a note within its beat:
   - `n_per_beat = round(beat_dur_q / dur_q)` — how many of this note fit in one beat
   - `phase = round((onset % beat_dur_q) / dur_q) % n_per_beat`
   - Examples: 8th in 4/4 (beat=1.0) → 2 phases; 8th in 9/8 (beat=1.5) → 3 phases; triplet 1/3 (beat=1.0) → 3 phases
   - Compound meter detection: `mc%3==0 and mu>=8` → `beat_dur_q = 4.0/mu * 3` (includes 3/8 → beat=1.5=whole bar; `mc>3` removed)
5. `_find_motifs(all_seqs)` — pattern key = `(body, start_phase)` where `body` = tuple of `(interval, dur)` pairs and `start_phase` = metric phase of the first note. Two occurrences of the same pitch/rhythm pattern at different metric phases = different motifs. Window-shift and sub-pattern dominance deduplication operate on `body` only (not phase).
   - **Rest exclusion**: inner loop `break`s if `seq[start+k][6]` (contiguous) is False — patterns spanning rests are skipped entirely
   - Per-voice greedy non-overlapping selection (`last_end = start + len + 1`)
   - Cross-voice deduplication: same beat (quantised to 16th grid) counts once
   - `_is_window_shift(p, q)`: eliminates cyclic/sliding-window duplicate patterns (inven02 case)
   - **Inversion merging** (Step 3): for each body B, if `body_inv = tuple((-iv, dur) for iv, dur in B)` exists at same phase, absorb inverted occurrences with `is_inv=True`; self-inverse bodies skipped; entries become 4-tuples `(nids, dp0, is_inv, onset_q)`
   - **Three-way count**: `n_direct_only`, `n_inv_only`, `n_both` (coinciding positions); `count = n_direct_only + n_inv_only + n_both` (union, no double-counting)
   - Up to 8 motifs; result sorted by occurrence count descending
6. HTML output: motif dictionary table (sorted by count desc) before score; notes colored; click row → SVG boxes on all occurrences + scroll to first occurrence; occurrence number shown above first group of each box; count shown **bold** if it is a regular number (2^a·3^b) and ≥ 8; motif name shows metric phase as `_|` (phase 1) or `_|_|` (phase 2) subscript
   - **Three-way count display**: `n_dir_total / ⇕n_inv_total / ⊕union` shown when inversions present
   - **Transposition profile**: clicking motif row opens detail row below with pairs `(transposition, distance)` per occurrence; distance in units of motif's minimum note duration; first occurrence always `(+0·0)`
   - **Click motif row** → populates search input with pattern query string (e.g. `1/16;0;+1-1-1`)
   - **Backspace** (when focus not in input field) → scrolls back to motif dictionary
   - **Startup focus** → tkinter piece-search field gets focus automatically

## Kern ornament handling

| Kern token | Meaning | MEI output | Effect on analysis |
|---|---|---|---|
| `q`/`Q` prefix | grace note / acciaccatura | `<note grace="...">` | Skipped, pos not advanced |
| `t`/`T` in token | trill / inverted trill | `<trill>` element | None (note stays single) |
| `m`/`M` in token | mordent / inverted mordent | `<mordent>` element | None |
| `S`/`$`/`R` in token | turn / inverted turn | `<turn>` element | None |
| `(note1 note2)` pair | written-out appoggiatura | 2 `<note>` + `<slur>`/`<phrase>` | Merged by `_merge_ornamental_slurs` |
| `!!` lines with `P` | musedata ornament realization | Ignored (global comment) | None |

## Motif box rendering (JavaScript in HTML)

- Groups note elements by SVG page, then by system (y-gap threshold = `max(minNoteHeight*2, 30px)`)
- Single group → full rect; first group → `[` bracket; last group → `]` bracket; middle → top+bottom lines
- `stroke-width: 2` with `vector-effect: non-scaling-stroke` — always 2px regardless of SVG zoom
- Occurrence number drawn as `<text>` above the first group of each occurrence; font-size = `ypad * 1.5` (proportional to box height, consistent across all occurrences)
- **Tooltip on hover**: hovering over occurrence number shows note names (e.g. `C# E G# B`) in a fixed `<div id="motif-tooltip">`; `noteLabels` JS dict (nid → pitch label) embedded as JSON from `nid_labels` built in `render_score`; accidental reconstructed from MIDI delta vs. natural base

## Interval notation in motif dictionary

- 0-indexed diatonic steps: unison = 0, second = 1, third = 2, … (matches `_DIATONIC_STEP` values)
- `_DIATONIC_NAMES = ['0','1','2','3','4','5','6']`
- Arrow prefix: `↑` ascending, `↓` descending, `—` unison

## Meta-analysis script

`meta_analysis.py` — runs motif analysis across all kern files (no SVG rendering), collects occurrence counts, tests whether smooth numbers (2^a·3^b ≥ 8) are over-represented vs. random expectation. Output: `meta_report.txt`.

```
python meta_analysis.py
python meta_analysis.py --filter frescobaldi --output meta_report_frescobaldi.txt
python meta_analysis.py --filter beethoven/opus132 --output meta_report_beethoven_opus132.txt
```

### Design
- Each file is analyzed in a **fresh subprocess** (`multiprocessing.get_context('spawn')`) with a 90-second timeout — isolates verovio segfaults and hangs
- Worker: `_worker_func(path, q)` — spawned per file, puts result into a `Queue`; main process calls `q.get(timeout=90)`, terminates process if it doesn't respond
- Imports `kern_reader` as module (no HTTP server started); uses `kr.find_kern_files`, `kr.find_music21_files`, `kr.prepare_grand_staff`, `kr.add_beam_markers`, `kr.analyze_motifs`
- Worker handles both `.krn` (text, kern preprocessing applied) and `.mxl` (unzipped, XML extracted, no kern preprocessing)
- `.mxl` inner file may use `.xml` or `.musicxml` extension — both matched
- `main()` always loads `kr.find_kern_files() + kr.find_music21_files()`; without `--filter`, music21 files are excluded; with `--filter`, both sources are searched
- Worker puts `[{'count': m['count'], 'length': m['length']} for m in motifs]` — `count` is the deduplicated union (n_direct_only + n_inv_only + n_both), no double-counting of coinciding inversions
- Last run (135 files, with inversion merging): 135 OK, 1 error; 6283 total motif counts; enrichment **1.80x** (log-uniform)
- Frescobaldi (40 files): enrichment **1.70x**; Beethoven opus132: **0.31x**

### Statistical test
Two null models for smooth-number enrichment among counts ≥ 8:
- **Uniform prior**: every integer in [8, max] equally likely → 3.61x (misleading)
- **Log-uniform prior**: weight 1/k → **1.80x** (modest enrichment)

**Note on inversion effect**: adding inversion merging raised enrichment from 0.84x → 1.80x. The count used is always the union (no double-counting of positions where both forms coincide). Motifs appear irregularly within a piece (scattered across voices, sections, entries at unpredictable bars), so smooth union counts are non-trivial — the smoothness cannot be explained away by piece-length structure and is genuine signal.

## Manual motif search

Browser contains a search input above the motif table. Two formats:

**Interval search**: `dur[,dur...];phase;+iv-iv...`
- **dur**: note duration as fraction, e.g. `1/16`. Operators: `>1/16`, `<=1/8`, etc. One duration = applied to all notes; N durations = one per interval; N+1 = one per note (last note's duration).
- **phase**: metric phase of first note (0 if omitted)
- **intervals**: signed diatonic steps, e.g. `+2-1+3`

**Rhythm-only**: `dur[,dur...];phase` (no intervals — matches any intervals)
- N durations = N notes; any interval accepted between them
- If first duration has operator (`>1/16`, `<=1/8`, etc.) → treated as **pre-gap condition** on the event immediately before the pattern: checks preceding note duration OR rest gap OR start-of-voice; start-of-voice satisfies `>x` and `>=x`

**Contour search**: `dur[,dur...];phase;+-=...` (only `+`/`-`/`=` in interval part, no digits)
- `+` = ascending, `-` = descending, `=` = unison
- e.g. `1/16;0;-+---` finds 6-note pattern with that direction sequence

**Inversion modifier**: append `;inv` to any search — also finds the inverted form
- Exact intervals: negated (`+2-1` → `-2+1`)
- Contour: `+`↔`-` swapped (`+-+` → `-+-`)
- e.g. `1/16;0;+1+1+1;inv` finds `+1+1+1` AND `-1-1-1`

**Phase computation in search**: always uses the *smallest* note duration in the pattern as the phase unit. Uses `beat_dur_q` from `_state["beat_dur_q"]`. In 3/8 (beat_dur_q=1.5), phase 0 = bar start; there are 6 phases for 1/16 notes within the bar.

**Non-overlapping**: greedy per-voice selection — `last_end = i + n + 1`; prevents shared notes between occurrences within the same voice.

Examples: `1/16;0;+2-1+3` — `3/16,1/16;0` — `1/16;0;-+---` — `1/16;0;+-+;inv`

Results added as `M_1`, `M_2`... rows at top of table; auto-activated on add; occurrences sorted by onset; smooth counts shown bold. Click row to toggle boxes / scroll to first occurrence.

Server endpoints: `POST /search` — returns `{"occs": [[nid,...], ...], "count": N}`; `GET /events` — SSE stream pushing version string on each score change; `GET /version` — current version as plain text (legacy, kept for debugging)

## File layout

- `kern/` — 1166 kern files; 8 collections shown in the browser:
  - `kern/musedata/bach/keyboard/wtc-1/` — WTC1 preludes (single-spine with `*^` splits; have beam markers)
  - `kern/musedata/bach/keyboard/wtc-2/` — WTC2 preludes (single-spine with `*^` splits; have beam markers)
  - `kern/osu/classical/bach/wtc-1/` — WTC1 fugues (multi-spine; no beam markers → injected)
  - `kern/osu/classical/bach/wtc-2/` — WTC2 fugues (multi-spine; no beam markers → injected)
  - `kern/osu/classical/bach/inventions/` — Inventions (multi-spine; no beam markers → injected)
  - `kern/musedata/bach/chorales/` — Chorales (multi-spine; have beam markers)
  - `kern/users/craig/classical/bach/violin/` — Violin partitas/sonatas (single-spine, has `**dynam` spines in some files)
  - `kern/users/craig/classical/bach/cello/` — Cello suites

## Dependencies

- `verovio` 6.1.0 — renders kern → SVG; initialized once as global `_vtk`; some files cause segfaults → isolated via subprocess
- `music21` — metadata extraction only
- `multiprocessing` (spawn context) — isolates verovio crashes; **important**: read from queue BEFORE joining subprocess to avoid pipe-buffer deadlock on large HTML payloads
- `tkinter` / `http.server` / `webbrowser` — stdlib
- HTTP server uses `ThreadingTCPServer` (one thread per connection) to support long-lived SSE connections alongside normal requests

## Additional functions in kern_reader.py

- `_dur_q_to_str(d)` — converts duration in quarter notes to search-format string (e.g. 0.5 → `"1/8"`). Formula: `Fraction(d/4.0)` because `_parse_dur` computes `num*4/den`.
- `_pattern_to_query(pattern, phase)` — converts a motif body tuple to a search query string (e.g. `"1/16;0;+1-1-1"`); used to populate the search field when clicking a motif row.
- `_mdl_score(n, L, transforms)` — module-level function. MDL saving = `n*(L-1) - L - transp_cost`. Sequence bonus: if ≥3 occurrences have constant ∆transposition (nonzero), `transp_cost = log2(n+1)` instead of `n * log2(n_distinct+1)`.
- `_fix_implicit_pickup_measures(content)` — fixes MusicXML `number="-1"` implicit measures (LilyPond repeat pickups) where voices 2+ have full-measure rests causing verovio to render an extra barline. Sets hidden-rest and backup durations to match actual voice content.

### File sort order

`find_kern_files` uses a custom sort key: WTC files sorted by `(wtc_set, piece_number, p_before_f)` so prelude and fugue of the same number appear consecutively (wtc1p01 → wtc1f01 → wtc1p02 → wtc1f02 → …); all other files sorted alphabetically by path after WTC.

### MDL column and sort

- Dictionary table has 5 columns: Мотив / Паттерн / Вхожд. / Нот / MDL
- Click "Вхожд." header → sort by count; click "MDL" header → sort by MDL score
- MDL value bold if positive, grey if ≤ 0
- `data-count` and `data-mdl` attributes on each `<tr>` for JS sort

### Inversion filter clicks

Three-way count `×N_dir ⇅N_inv ⊕N_all` — each span is individually clickable:
- Click `×N_dir` → show only direct occurrences (boxes + scroll)
- Click `⇅N_inv` → show only inverted occurrences
- Click `⊕N_all` → show all (default row-click behavior)
- Active filter underlined/bold; repeat click deactivates; row click always resets to 'all'

### Note coloring

- **Initially all notes black** — no coloring on page load
- **Click a motif → colors its notes** (persists even after deactivating boxes)
- Colors accumulate: each newly clicked motif adds its color on top of previous
- `colorMotif(m)` function sets `fill` attribute on all note elements of a motif

### Motif length

- `max_pat_len=None` — no upper limit on pattern length

## Metric phase bug fixes

**2/2 time**: `_parse_meter` previously returned `beat_dur_q = 4.0/mu` giving 2.0 for 2/2 (alla breve). This produced 8 phase slots for 1/16 notes (phases 0-7). Fix: `min(4.0/mu, 1.0)` caps simple-meter beat at one quarter note. Compound meters (6/8, 9/8, 12/8) are unaffected.

**32nd notes (and shorter)**: `_metric_phase` computed `n_per_beat=8` for 32nd notes in 3/4 (phases 0-7), allowing phase=5 which is meaningless. Fix: binary subdivisions (n_per_beat not divisible by 3) are capped at 4 → same resolution as 16th notes. Triplet patterns (n_per_beat divisible by 3) are collapsed to 3 phases as before.

**Compound meter 16th notes (12/8, 9/8, 6/8)**: `n_per_beat=6` for 16th notes in compound meter was collapsed to 3, making phase 0 land on BOTH beat positions AND dotted-eighth positions (0.75, 2.25, 3.75, 5.25 into the bar). Fix: when `round(beat_dur_q * 4) % 3 == 0` (compound meter) and `n_per_beat >= 6`, keep `n_per_beat = min(n_per_beat, 6)` so that phase 0 = beat starts only. Triplet 16ths in simple meter (beat_dur_q=1.0) still collapse to 3 phases.

## LilyPond → MusicXML converter (no MIDI)

`lilypond/convert_ly_direct.py` — converts Bach LilyPond collection to MusicXML by hooking LilyPond's Scheme compilation pipeline. No MIDI involved.

### Architecture

- **`lilypond/ly_dump.ily`** — Scheme include that hooks `toplevel-score-handler`, `book-score-handler`, and `bookpart-score-handler` to intercept every `\score` block during LilyPond compilation. Writes note data as JSON-lines to a temp file.
  - `dump-traverse m onset staff voice` — recursive traversal of LilyPond music AST
  - Handles: `RelativeOctaveMusic` (forces pitch resolution via `ly:relative-octave-music::relative-callback`), `EventChord` (chord = multiple NoteEvents same onset), `NoteEvent`, `RestEvent`, `SkipEvent`, `TimeSignatureMusic`, `KeyChangeEvent`, `SimultaneousMusic` (voice splits), `ContextSpeccedMusic` (named Staff/Voice contexts), `ContextChange` (`\change Staff`) for cross-staff notes, `MultiMeasureRestMusic`
  - Anonymous `\new Staff` contexts assigned auto-numbered IDs (reset per score); named contexts use their ID string
  - Output: one JSON object per line — `{"t":"N","on":"3/4","semi":7,"oct":1,"step":4,"log":3,"dots":0,"st":"upper","vc":"1","tie":false}` for notes; `{"t":"T",...}` for time sigs; `{"t":"K",...}` for key sigs

- **`lilypond/convert_ly_direct.py`** — Python driver
  - For each .ly file: creates a temp wrapper that `#(define ly:dump-output-file "...")` then `\include`s `ly_dump.ily` then the source file; runs LilyPond with `--loglevel=ERROR -dno-point-and-click`; reads JSON-lines output
  - `notes_to_score(events)` — builds music21 Score: staves ordered by **first appearance** in note stream (preserves treble-before-bass); inserts time/key sigs; calls `makeMeasures()` + `makeTies()`; pitch alter computed from `semi - STEP_SEMI[step]` (avoids `ly:pitch-alteration` unit ambiguity)
  - Same `is_toplevel`/`is_skip`/`short_name` helpers as `convert_bach.py`

### Key technical facts

- `\relative` is NOT resolved at `toplevel-score-handler` call time (music still shows `RelativeOctaveMusic`). Solution: call `ly:relative-octave-music::relative-callback m ref` in-place before traversing.
- `\score` inside `\book`: triggers `book-score-handler`, NOT `toplevel-score-handler` — both must be hooked.
- `\change Staff` = `ContextChange` music object with `change-to-id` property; handled in sequential loop to update current staff for subsequent notes.
- `-dbackend=musicxml` (LilyPond built-in): broken in 2.24.4, outputs empty XML.

### Results

494/510 files converted successfully; 14 EMPTY (source syntax errors), 2 ERROR (LilyPond crash). Output: `lilypond/musicxml/*.xml`.

## Known issues

- Verovio prints harmless C++ warnings to stderr (beamSpan, mixed beam, unknown clef types)
- Some chorales files cause verovio segfaults → subprocess isolation catches these, shows error in status bar
- `autoBeam` is not a supported option in verovio 6.1.0 — beam markers must be injected manually
- music21 prints `'Rest' object has no attribute 'beams'` for some chorales — harmless
- `ConnectionAbortedError: [WinError 10053]` in HTTP server — harmless, browser closed connection on page reload
- User communicates in Russian

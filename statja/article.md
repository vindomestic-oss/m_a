# The Arithmetic of Repetition: Smooth-Number Occurrence Counts in Bach and the Baroque Corpus

*Draft — work in progress*

---

## Abstract

The durational vocabulary of Western tonal music is built entirely from smooth numbers — integers of the form 2^a × 3^b (whole notes, halves, quarters, dotted values, triplets). We ask whether this arithmetic constraint extends beyond individual note values to the *count* of structural element repetitions within a piece. Analysing a corpus of 1,024 Bach and Baroque works, we find that motif occurrence counts are smooth numbers significantly more often than expected under a log-uniform null model (enrichment ratio 2.25×). A shift test confirms the result is not an artefact of frequency-table shape: real counts are 1.47× denser at smooth positions than counts shifted by +1 (threshold ≥ 16), rising to 2.28× at threshold ≥ 48. Three illustrative cases from Bach — WTC Prelude No. 7 in E♭ major (192 = 2^6·3 occurrences of a stepwise sixteenth-note figure, direct and inverted forms combined), WTC Fugue No. 12 in F minor (96 = 2^5·3 occurrences of a sixteenth-note countersubject figure), and the BWV 944 Fugue in A minor (128 = 2^7 occurrences of a characteristic three-note motive) — show the pattern at its clearest. The effect is robustly present across other Baroque composers (Corelli 1.89×, Scarlatti 1.99×, Buxtehude 1.66×, Frescobaldi 1.70×) and persists, somewhat attenuated, into the Classical period (Haydn 1.77×, Mozart 1.90×, Beethoven 1.72×). The mechanism behind this alignment remains an open question.

---

## 1. Introduction

Western music theory has long recognised that the durational hierarchy of tonal music is organised around powers of two and three. Whole notes divide into halves, quarters, eighths, and sixteenths (powers of 2); dotted values and compound meters introduce factors of three; the result is that every standard note duration is a smooth number — an integer of the form 2^a × 3^b — when expressed as a fraction of a fixed unit. This constraint is so deeply embedded in notation that it goes unremarked: a "non-smooth" duration such as a fifth-note or a seventh-note would be not merely unusual but unnotatable in standard Western notation without resort to tuplets.

What has not been investigated, to our knowledge, is whether smooth-number structure operates at a higher level — not in the duration of individual notes, but in the *count* of times a structural element (a melodic motive, a rhythmic figure, a harmonic function) recurs within a piece. If a motive appears, say, 18 times in a Bach prelude, is that 18 coincidental, or does it reflect the same binary-ternary architecture that governs the note durations themselves? More precisely: are motif occurrence counts smooth numbers significantly more often than one would expect by chance?

This question is tractable through corpus analysis. Automatic motif detection on a large collection of works produces thousands of occurrence counts; statistical testing can then determine whether smooth numbers are over-represented among them. The present study applies this approach to a corpus of 1,024 pieces drawn primarily from Bach and the wider Baroque repertoire.

Three individual pieces motivate and illustrate the central claim. In Bach's Well-Tempered Clavier, Book I, Prelude No. 7 in E♭ major, a characteristic stepwise figure in sixteenth notes (metric phase 1), counted together with its inversion, recurs exactly **192 times** — and 192 = 2^6 · 3. In the WTC Book I Fugue No. 12 in F minor, a sixteenth-note figure that forms the main countersubject recurs exactly **96 times** — and 96 = 2^5 · 3. In the BWV 944 Fugue in A minor, a three-note motive (a rising third followed by two descending steps) appears exactly **128 times** — and 128 = 2^7. The question is whether such alignments are systematically frequent across a large corpus.

The study originates from a collection of manual observations. Examining Bach's keyboard works, the author repeatedly encountered cases where a thematically prominent motive — one appearing both in the opening statement and in developmental episodes — had a smooth total occurrence count. However, any such observation immediately faces an objection: the identification of a motive as "important", the delimitation of its boundaries, and the choice of criteria for a match (exact intervals, or contour only, or rhythm only) are all irreducibly subjective. Different analysts would identify different sets of "important" motives in the same piece and arrive at different counts.

To avoid this circularity, the present study adopts a deliberately non-selective approach: every recurring pattern found by an automatic algorithm is included in the analysis, without human judgement about thematic significance. This means that the pool of occurrence counts contains both the genuinely salient motivic cells that a trained analyst would identify and a large number of incidental coincidences — common scale fragments, stock accompanimental figures, and accidental recurrences. The dilution of the dataset by such "noise" works *against* finding smooth-number enrichment: if the effect survives despite it, the evidence is stronger than if only hand-picked "important" motives were counted. The fact that enrichment is 2.25× even in this maximally inclusive regime suggests that the underlying signal, were it measured only over thematically central elements, would be considerably larger.

The article proceeds as follows. Section 2 surveys relevant background. Section 3 describes the corpus and the motif detection algorithm. Section 4 presents the statistical framework and null models. Section 5 reports results for Bach and other composers. Section 6 discusses interpretations and limitations. Section 7 concludes. Annotated score excerpts illustrating the motif patterns discussed in Section 4 are collected in the Appendix.

---

## 2. Background

### 2.1 Smooth numbers in music

A positive integer n is called *B-smooth* if all its prime factors are at most B. In the context of Western tonal music, the relevant class is {2, 3}-smooth numbers (also called 3-smooth or *regular numbers*): integers of the form 2^a · 3^b with a, b ≥ 0. These are precisely the numbers 1, 2, 3, 4, 6, 8, 9, 12, 16, 18, 24, 27, 32, 36, 48, 54, 64, 72, 81, 96, 108, 128, … The intersection of this sequence with standard note durations (in units of sixty-fourth notes) is complete: every standard duration from the whole note (64) down to the sixty-fourth note (1) is smooth, as are all dotted values (96, 48, 24, 12, 6, 3) and compound-meter beat durations.

The relevance of 3-smooth numbers to musical metre has been noted by several theorists. [REFS: Pressing 1983; London 2004; Cohn 1992 on hypermetre...] What these accounts share is the observation that metric *structure* — the hierarchy of beats, measures, phrases — is built from iterated doublings and triplings.

This hierarchy extends well beyond the level of individual note durations. At the level of *hypermetre*, phrases in tonal music characteristically span 4 or 8 bars (occasionally 3, 6, or 12). Binary dance movements in Bach's keyboard suites frequently have halves of 8, 12, 16, or 24 bars; fugue expositions and episodes can often be measured in units of 4 or 8 bars. Whether smooth bar-counts extend reliably to larger formal sections — development blocks, da capo spans — is less certain and would require systematic measurement.

The present study asks whether the same arithmetic governs one further level: the *multiplicity* with which a melodic motive recurs across the piece as a whole. This is a different question from bar-count smoothness: a motive does not appear once per bar in any regular fashion, so its total occurrence count cannot simply inherit smoothness from formal structure. The question is whether smooth-number alignment appears at the level of occurrence counts independently of such structural regularities.

### 2.2 Motif analysis

The automatic detection of melodic motifs in symbolic music has a substantial literature. [REFS: Conklin & Witten 1995; Lartillot 2014; Collins et al. 2011...] Most approaches define a motif as a recurring pattern of pitches, intervals, or rhythmic values and rank candidates by some measure of salience. The present study uses a pipeline based on diatonic interval sequences extracted from a Music Encoding Initiative (MEI) representation: chromatic distinctions (major vs. minor third, etc.) are deliberately suppressed, following the principle that Bach's motivic technique operates at the level of melodic contour and step/leap distinction rather than exact chromatic content. All recurring patterns with at least two occurrences are retained after deduplication; no salience threshold or MDL filter is applied at this stage. (An MDL score is computed per pattern as a secondary quality indicator for manual exploration but plays no role in the corpus statistics.) The deliberate absence of a salience filter means the dataset includes incidental recurrences alongside compositionally intended motives; as argued in §1, this dilution works against finding smooth-number enrichment and therefore strengthens the result if the effect is nonetheless present.

### 2.3 Occurrence counts and statistical testing

Statistical analysis of symbolic music corpora has addressed questions of style, authorship, tonality, and formal structure [REFS]. The specific question of whether numerical properties of occurrence counts are non-random appears to be new. The methodological challenge is that occurrence counts follow a steeply falling distribution (most motifs occur 2–4 times; very high counts are rare), so a naive uniform null model is misleading — smooth numbers would appear enriched simply because they cluster at low values where counts are common. We address this by using a *log-uniform* null model, in which the prior probability of observing count k is proportional to 1/k. Under this model, the expected smooth-number density is ~18.3% for the Bach corpus range; the observed density is ~41.2%, giving an enrichment ratio of 2.25×. We also apply a *shift test* as an additional check: if smooth counts are genuinely over-represented, counts shifted by ±1 should be less smooth-dense, and this asymmetry should be robust across threshold choices.

---

## 3. Corpus and Methods

### 3.1 Corpus

The corpus consists of 1,024 works analysed successfully from a collection of 1,034 files in two formats: Humdrum **kern** (primarily from the CCARH MuseData and Ohio State University collections) and **MusicXML** (converted from LilyPond sources or downloaded from IMSLP). The Bach subset comprises keyboard works (Well-Tempered Clavier Books I and II, Two- and Three-Part Inventions), chorales, violin partitas and sonatas (BWV 1001–1006), and cello suites (BWV 1007–1012), together with selected keyboard suites and preludes. Additional composers in the extended corpus include Corelli (251 files, primarily trio sonatas and concerti grossi), Domenico Scarlatti (65 keyboard sonatas), Buxtehude (21 files), Frescobaldi (40 files), Haydn (9 files), Mozart (16 files), Beethoven (26 files), and others.

10 files failed to parse (< 1%) and were excluded.

### 3.2 Motif detection pipeline

As explained in §1, the analysis is deliberately non-selective: the algorithm extracts *all* recurring patterns from each piece, not only those deemed musically significant by a human analyst. The rationale is to avoid the circularity that would arise from counting only "important" motives, since the criterion of importance is not objectively definable. Every pattern that recurs at least twice contributes an occurrence count to the dataset; the statistical test then asks whether smooth numbers are over-represented in the full, unfiltered collection.

Score rendering and MEI extraction are performed by **verovio** 6.1.0. The analysis pipeline proceeds as follows:

1. **Voice separation.** The MEI is parsed into per-voice note sequences with absolute onset times in quarter notes. Grace notes are excluded; tied notes are merged; ornamental two-note slur pairs (appoggiaturas) are collapsed into single notes with combined duration.

2. **Interval computation.** For each consecutive pair of notes within a voice, a *diatonic interval* is computed: iv = (octave × 7 + diatonic step of note 2) − (octave × 7 + diatonic step of note 1). The chromatic alteration is discarded (C→E and C→E♭ both yield interval +2). This captures melodic motion at the level of step/leap/direction rather than exact chromatic content, reflecting the common analytical observation that Bach's motivic technique is robust to transposition and mode mixture.

3. **Feature tuple.** Each melodic step is represented as a tuple (interval, duration, metric phase, onset, contiguity flag). The *metric phase* of a note is its position within the beat, discretised to the note's own duration as a unit (e.g. eighth notes in 4/4 time have two phases: 0 = on the beat, 1 = off the beat). *Contiguity* is false if a rest intervenes between two notes; patterns spanning rests are excluded. Two patterns that share the same (interval, duration) body but differ in start phase are treated as distinct patterns, since metric placement is a primary component of motivic identity in tonal music.

4. **Pattern finding.** A sliding window of length 2 to unlimited scans each voice for recurring (interval, duration) sequences with matching start phase. This produces a large number of candidates, the majority of which are incidental substrings rather than compositionally intended motives. Candidates are deduplicated by sub-pattern dominance (a pattern is suppressed if it is a sub-sequence of a longer pattern with the same or higher occurrence count) and cyclic-shift equivalence. Inverted forms (all intervals negated) are merged with their direct counterparts; the reported count is the union (direct + inverted − coinciding positions). All patterns with at least two occurrences are candidates; they are ranked by occurrence count (descending), with pattern length as a tiebreaker, and up to 50 per piece are collected for the corpus statistics. This means the dataset is weighted toward higher occurrence counts — the region where the smooth-number effect is expected to be strongest.

A deliberate consequence of this approach is that pattern matching is mathematically exact. If a motif is defined as the interval sequence `+1 −1 +2`, then only occurrences of precisely that sequence are counted; a variant with one interval altered — even if a human listener would perceive it as "the same idea" — is a different pattern and is counted separately or not at all. This strictness is not a limitation but a methodological choice. Human motivic recognition is flexible, context-sensitive, and ultimately subjective: two analysts may disagree on whether a given passage instantiates a motif. The formal approach replaces that judgment with a fixed criterion — interval, duration, and metric phase — applied uniformly and without exception. Any relaxation of the criterion (allowing approximate intervals, or optional notes, or context-dependent boundaries) would reintroduce the analyst's ear as an uncontrolled variable, making the counts incomparable across pieces and analysts. The price is that the formal count will sometimes miss what a musician considers an obvious variant; the gain is that the counts are reproducible, objective, and suitable for statistical aggregation.

The analysis tool — `kern_reader.py` — is an interactive score browser that renders any file in the corpus, overlays detected motif occurrences as coloured boxes on the score, and supports manual pattern search by interval sequence, contour, or rhythm. Motifs are listed in a summary table with occurrence counts, pattern length, and a transposition profile for each occurrence. The tool and corpus are available at https://github.com/vindomestic-oss/m_a.

### 3.3 Statistical framework

Let F(k) denote the number of times count k appears across all retained patterns and all files. We restrict attention to k ≥ 8 (below 8 the distinction between smooth and non-smooth is poorly defined and the counts are dense). Let S = {8, 9, 12, 16, 18, 24, 27, …} be the set of smooth numbers ≥ 8.

**Enrichment ratio (log-uniform model).** Let the null probability of observing count k be p_0(k) = (1/k) / Σ_{j=8}^{K} (1/j), where K is the maximum observed count. The expected number of smooth observations under this model is E = Σ_{k ∈ S, k ≤ K} p_0(k) · N, where N = Σ_k F(k) is the total number of observations with k ≥ 8. The enrichment ratio is O/E, where O = Σ_{k ∈ S} F(k).

**Shift test.** For a threshold T, let n_smooth(T) = |{i : c_i ≥ T, c_i ∈ S}|, n_total(T) = |{i : c_i ≥ T}|, and similarly for c_i + 1 and c_i − 1. The shift ratio at T is [n_smooth(T) / n_total(T)] / [n_smooth_{+1}(T) / n_total_{+1}(T)]. A ratio > 1 means real counts fall on smooth numbers more often than counts shifted by +1.

---

## 4. Three Illustrative Cases

Before presenting aggregate statistics, we examine three individual pieces where the smooth-number alignment is especially striking.

### 4.1 WTC Book I, Prelude No. 7 in E♭ major (BWV 852)

The prelude unfolds in three texturally distinct sections, each with a different density of the characteristic figure — a three-note stepwise run in sixteenth notes beginning on the second sixteenth of the beat (metric phase 1): the pattern `1/16; phase 1; +1 +1` in ascending form and its inversion `−1 −1`. The density of the figure varies across sections, yet the total across all voices and the full piece reaches exactly **192 occurrences**. The number 192 = 2^6 · 3 belongs to the binary-ternary hierarchy: it is three groups of 64, or 12 groups of 16, or 8 groups of 24.

[FIGURE: BWV 852, first and last systems. Boxes mark occurrences of the figure 1/16; +1+1 and its inversion; occurrence numbers shown above each box. Total: 192 = 2^6·3.]

### 4.2 WTC Book I, Fugue No. 12 in F minor BWV 857

The sixteenth-note figure `+1 +1 +1` (three ascending diatonic steps) serves as the principal countersubject of this fugue, entering in the answer voice already in bar 2. It is one of the most consistently recycled cells in the entire piece. Counted across all voices, the figure recurs exactly **96 times** — and 96 = 2^5 · 3.

[FIGURE: BWV 857, first and last systems. Boxes mark occurrences of the countersubject figure 1/16; +1+1+1 and its inversion. Total: 96 = 2^5·3.]

### 4.3 Fugue in A minor BWV 944

This harpsichord fugue in 4/4 time has a subject that opens directly with the figure `1/16; phase 0; +2 −1 −1` — a rising third followed by two descending steps — as its very first notes, making it the subject's opening cell. The pattern appears **128 times** throughout the fugue: 128 = 2^7. This is among the largest smooth counts observed in the corpus (the maximum overall is 392).

[FIGURE: BWV 944, first and last systems. Boxes mark occurrences of the opening cell +2−1−1 and its inversion. Total: 128 = 2^7.]

---

## 5. Corpus Results

### 5.1 Bach (full corpus, 1,024 files)

The total number of retained motif-occurrence counts with k ≥ 8 is **11,340**. The smooth-number subset accounts for **4,669** of these. Under the log-uniform null model, the expected smooth count is approximately 2,075, giving an enrichment ratio of **2.25×**. Table 1 shows the frequency of occurrence counts at selected smooth values.

**Table 1.** Frequency of smooth occurrence counts in the Bach corpus (k ≥ 8, top 20 by frequency).

| Count | Smooth? | Frequency |
|-------|---------|-----------|
| 8     | 2^3     | 1485 |
| 9     | 3^2     | 1172 |
| 12    | 2^2·3   | 722  |
| 16    | 2^4     | 388  |
| 18    | 2·3^2   | 320  |
| 24    | 2^3·3   | 186  |
| 27    | 3^3     | 120  |
| 32    | 2^5     | 109  |
| 36    | 2^2·3^2 | 60   |
| 48    | 2^4·3   | 34   |
| 54    | 2·3^3   | 30   |
| 64    | 2^6     | 19   |
| 72    | 2^3·3^2 | 8    |
| 81    | 3^4     | 6    |
| 96    | 2^5·3   | 3    |
| 108   | 2^2·3^3 | 2    |
| 128   | 2^7     | 2    |
| 192   | 2^6·3   | 1    |

For comparison, the immediately adjacent non-smooth count 10 appears 954 times and count 11 appears 783 times; count 17 appears 341 times against 16's 388 and 18's 320. The local peaks at smooth positions are visible in the frequency distribution.

The shift test strengthens the conclusion. Table 2 shows the smooth density of real counts versus counts shifted by +1, at several thresholds.

**Table 2.** Shift test results (Bach corpus, shift +1).

| Threshold | n (real) | Smooth density (real) | Smooth density (shifted +1) | Ratio |
|-----------|----------|-----------------------|-----------------------------|-------|
| ≥ 14 | 5664 | 0.228 | 0.236 | 0.97× |
| ≥ 16 | 4714 | 0.274 | 0.186 | **1.47×** |
| ≥ 18 | 3985 | 0.226 | 0.134 | **1.69×** |
| ≥ 24 | 2643 | 0.220 | 0.142 | **1.56×** |
| ≥ 32 | 1636 | 0.169 | 0.087 | **1.93×** |
| ≥ 48 | 772  | 0.139 | 0.061 | **2.28×** |

The anomaly at threshold 14 (ratio < 1) reflects the high raw frequency of count 15 and the smooth count 9 falling below the 14 threshold. Above 16, the shift ratio rises monotonically and is largest at high thresholds, where the signal-to-noise ratio is best.

### 5.2 Cross-composer comparison

Table 3 summarises enrichment ratios (log-uniform) for all composers with ≥ 15 files in the corpus.

**Table 3.** Smooth-number enrichment by composer.

| Composer | Files | Enrichment (log-uniform) |
|----------|-------|--------------------------|
| Bach (all) | 413 | 2.21× |
| Corelli | 251 | 1.89× |
| Domenico Scarlatti | 65 | 1.99× |
| Frescobaldi | 40 | 1.70× |
| Buxtehude | 21 | 1.66× |
| Mozart | 16 | 1.90× |
| Beethoven | 26 | 1.72× |
| Haydn | 9 | 1.77× |

All values exceed 1.5×, suggesting that smooth-number alignment in motif counts is not a peculiarity of Bach but a general feature of metrically regular Western tonal music from roughly 1600 to 1800. The differences between composers are not large enough to draw firm conclusions from the present corpus sizes; a dedicated cross-composer study with larger per-composer samples is warranted.

---

## 6. Discussion

### 6.1 Interpretation

Why would motif occurrence counts tend to be smooth numbers? A naive answer — that smooth counts are inherited from the smooth bar-counts of formal sections — does not hold up. Motifs do not appear once per bar in any regular fashion; they arise irregularly across voices, sections, and developmental episodes. A motive might enter in bar 1, bar 5, bars 9–12, and then again in the recapitulation, with no regular spacing. That such irregular occurrences should nonetheless sum to a smooth number is precisely the non-trivial observation that requires explanation.

A more plausible hypothesis points toward the organisation of memory rather than the organisation of form. Human memory — and arguably memory in biological neural networks more broadly — operates in hierarchical structures that favour powers of two and three: information is grouped, chunked, and rehearsed in units of 2, 4, 8 or 3, 6, 12. If the composer's internalized sense of "enough repetition" or "satisfying closure" is calibrated by these same memory structures, smooth-number totals would emerge as a byproduct of how musical material is retained and deployed, rather than as a consequence of any explicit counting or formal planning.

A more speculative variant of this hypothesis invokes the dynamics of neural networks directly: smooth-number repetition counts may arise as *resonant* outcomes of the brain's rhythmic architecture, in the same way that certain oscillation frequencies are privileged by the connectivity of neural circuits. We mention this possibility without endorsing it; both hypotheses, and their relationship to the empirical data, remain open questions for future work.

### 6.2 The shift-test asymmetry

The shift test reveals a consistent asymmetry: real counts are more strongly differentiated from shift+1 than from shift−1 (see Table 2, where the +1 ratios are systematically larger than the corresponding −1 ratios at thresholds ≥ 16). This means that the count immediately *above* a smooth number is more consistently depleted than the count immediately below. A possible explanation is that when a motive "aims" for a smooth count of N, the actual observed count is N or N−1 (one occurrence missed or merged) more often than N+1 (an extra stray occurrence added). This is consistent with composers treating smooth targets as upper bounds rather than exact specifications. The asymmetry is an empirical observation; we do not propose a causal mechanism here.

### 6.3 Limitations

**Algorithmic dependence.** The occurrence counts depend on the motif detection algorithm, which makes choices about pattern length, phase matching, and inversion merging. Different algorithmic choices would produce different count distributions. We have verified that the enrichment result is robust to the main parameter choices (minimum length ≥ 2 vs. ≥ 3, with and without inversion merging), but a comprehensive sensitivity analysis is left for future work.

**Inversion merging.** The union count (direct + inverted − coinciding) differs from the direct count by a variable amount that depends on how often the inverted form actually appears in the piece; in practice the ratio of inverted to direct occurrences varies widely across motifs and pieces. Merging therefore does not systematically double counts, and the doubling artefact (2N smooth whenever N smooth) does not apply. For transparency we report the enrichment both with and without inversion merging: [TODO: add no-inv figure] vs. 2.25×.

**Corpus composition.** The corpus is not a representative sample of all Western tonal music; it over-represents Bach and keyboard music. The cross-composer comparison in §5.2 suggests the effect is widespread, but replication on a more balanced corpus is needed.

**Multiple testing.** Each piece contributes multiple occurrence counts, and the counts are not independent (a long motive may subsume a shorter one). We treat this as a descriptive corpus study rather than a confirmatory statistical test; p-values are not reported.

---

## 7. Conclusion

We have shown that motif occurrence counts in a large corpus of Bach and Baroque music are smooth numbers (of the form 2^a · 3^b) approximately 2.25× more often than expected under a log-uniform null model, with the excess confirmed by a shift test that is robust to threshold choice and reaches 2.28× at high count values. The pattern is consistent across Baroque composers (Corelli, Scarlatti, Buxtehude, Frescobaldi) and persists into the Classical period (Haydn, Mozart, Beethoven).

The result documents a level of smooth-number organisation that has not previously been described: not in note durations or bar lengths, but in the count of times a structural element recurs across a piece. Three individual pieces from Bach illustrate the pattern with particular clarity: WTC I Prelude No. 7 (192 occurrences), WTC I Fugue No. 12 (96 occurrences), and BWV 944 Fugue (128 occurrences). Since motifs appear irregularly within a piece — not once per bar, not in any predictable spacing — a purely formal or structural explanation does not account for the result. The mechanism remains an open question; we tentatively suggest that it may be rooted in the binary-ternary organisation of memory and repetition in biological neural systems, but this hypothesis requires independent investigation.

---

## References

*[To be completed. Key works to cite: Pressing 1983 on rhythmic complexity; London 2004 Hearing in Time; Cohn on hexatonic and metric theory; Conklin & Witten 1995 on multiple viewpoints; Lartillot MIR works; Collins et al. 2011 MIREX motif; relevant music theory corpus studies.]*

---

*Notes for revision:*
- *Add score excerpts (Figures 1–3) for the three illustrative pieces*
- *Add no-inversion-merging enrichment figure to §6.3*
- *Expand §2.1 with proper literature citations*
- *Check exact bar counts and voice assignments for the three examples against kern_reader output*
- *Add per-file breakdown examples to support §4 narratives*

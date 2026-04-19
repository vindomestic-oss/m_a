Running head: SMOOTH-NUMBER COUNTS IN MUSIC CORPORA

# The Arithmetic of Repetition: Smooth-Number Counts in Bach and the Baroque Corpus

**Alexander Vynograd**

---

## Abstract

The durational vocabulary of Western tonal music is built entirely from smooth numbers — integers of the form 2^a × 3^b. We ask whether this arithmetic constraint extends to the *count* of times a melodic motive recurs within a piece. We analyse a corpus of 4,447 symbolic-score files spanning Bach (1,943 works) and the broader Baroque and Classical repertoire, applying an automatic motif-detection pipeline based on diatonic interval sequences. We find that motif occurrence counts are smooth numbers significantly more often than expected under a log-uniform null model (enrichment 2.23× for Bach). A shift test confirms that the result is not an artefact of the count distribution: real counts are 1.33× denser at smooth positions than counts shifted by +1 (threshold ≥ 16), rising to 1.89× at threshold ≥ 36. Three Bach cases illustrate the finding concretely: WTC Prelude No. 7 in E♭ major (192 = 2^6·**3** occurrences of a stepwise sixteenth-note figure), WTC Fugue No. 12 in F minor (96 = 2^5·3), and the BWV 944 Fugue in A minor (128 = 2^7). We show that the effect holds across Baroque composers (Handel 1.77×, Telemann 1.97×, Corelli 1.89×, Scarlatti 1.99×, Frescobaldi 1.70×) and extends to the Classical period, with Mozart (2.05×) matching Baroque levels. We discuss possible interpretations rooted in the binary-ternary organisation of musical memory, and propose the result as a structural constraint for computational models of tonal music generation.

*Keywords*: smooth numbers, motif analysis, computational musicology, metric hierarchy, symbolic music

*AMS Classification*: 00A65

---

## 1. Introduction

Western music theory has long recognised that the durational hierarchy of tonal music is organised around powers of two and three. Whole notes divide into halves, quarters, eighths, and sixteenths (powers of 2); dotted values and compound meters introduce factors of three; the result is that every standard note duration is a smooth number — an integer of the form 2^a × 3^b — when expressed as a fraction of a fixed unit. This constraint is so deeply embedded in notation that it goes unremarked: a "non-smooth" duration such as a fifth-note or a seventh-note would be not merely unusual but unnotatable in standard Western notation without resort to tuplets.

What has not been investigated, to our knowledge, is whether smooth-number structure operates at a higher level — not in the duration of individual notes, but in the *count* of times a structural element (a melodic motive, a rhythmic figure, a harmonic function) recurs within a piece. If a motive appears, say, 18 times in a Bach prelude, is that 18 coincidental, or does it reflect the same binary-ternary architecture that governs the note durations themselves? More precisely: are motif occurrence counts smooth numbers significantly more often than one would expect by chance?

This question is tractable through corpus analysis. Automatic motif detection on a large collection of works produces thousands of occurrence counts; statistical testing can then determine whether smooth numbers are over-represented among them. The present study applies this approach to a corpus of 4,447 files drawn primarily from Bach and the wider Baroque repertoire.

Three individual pieces motivate and illustrate the central claim. In Bach's Well-Tempered Clavier, Book I, Prelude No. 7 in E♭ major, a characteristic stepwise figure in sixteenth notes (metric phase 1), counted together with its inversion, recurs exactly **192 times** — and 192 = 2^6 · 3. In the WTC Book I Fugue No. 12 in F minor, a sixteenth-note figure that forms the main countersubject recurs exactly **96 times** — and 96 = 2^5 · 3. In the BWV 944 Fugue in A minor, a three-note motive (a rising third followed by two descending steps) appears exactly **128 times** — and 128 = 2^7. The question is whether such alignments are systematically frequent across a large corpus.

The study originates from a collection of manual observations. Examining Bach's keyboard works, the author repeatedly encountered cases where a thematically prominent motive — one appearing both in the opening statement and in developmental episodes — had a smooth total occurrence count. However, any such observation immediately faces an objection: the identification of a motive as "important", the delimitation of its boundaries, and the choice of criteria for a match (exact intervals, or contour only, or rhythm only) are all irreducibly subjective. Different analysts would identify different sets of "important" motives in the same piece and arrive at different counts.

To avoid this circularity, the present study adopts a deliberately non-selective approach: every recurring pattern found by an automatic algorithm is included in the analysis, without human judgement about thematic significance. This means that the pool of occurrence counts contains both the genuinely salient motivic cells that a trained analyst would identify and a large number of incidental coincidences — common scale fragments, stock accompanimental figures, and accidental recurrences. The dilution of the dataset by such "noise" works *against* finding smooth-number enrichment: if the effect survives despite it, the evidence is stronger than if only hand-picked "important" motives were counted. The fact that enrichment is 2.23× even in this maximally inclusive regime suggests that the underlying signal, were it measured only over thematically central elements, would be considerably larger.

The article proceeds as follows. Section 2 surveys relevant background. Section 3 describes the corpus, the motif detection algorithm, and the statistical framework. Section 4 presents three illustrative cases. Section 5 reports corpus-wide results for Bach and other composers. Section 6 discusses interpretations and limitations. Section 7 concludes. Annotated score excerpts are collected in the Appendix.

---

## 2. Background

### 2.1 Smooth numbers in music

A positive integer n is called *B-smooth* if all its prime factors are at most B. In the context of Western tonal music, the relevant class is {2, 3}-smooth numbers (also called 3-smooth or *regular numbers*): integers of the form 2^a · 3^b with a, b ≥ 0. These are precisely the numbers 1, 2, 3, 4, 6, 8, 9, 12, 16, 18, 24, 27, 32, 36, 48, 54, 64, 72, 81, 96, 108, 128, … The intersection of this sequence with standard note durations (in units of sixty-fourth notes) is complete: every standard duration from the whole note (64) down to the sixty-fourth note (1) is smooth, as are all dotted values (96, 48, 24, 12, 6, 3) and compound-meter beat durations.

The relevance of 3-smooth numbers to musical metre has been noted by several theorists. Pressing (1983) argues that 2 and 3 are the universal cognitive primitives of rhythmic organisation across world musics, with all referent pulse cycles generated by iterated multiplication by these factors. London (2004) makes this the centrepiece of a theory of metrical well-formedness: the perceptual-motor system can entrain only to beat subdivisions related by ratios of 2 or 3, so all metrically valid durations are smooth numbers by necessity. What these accounts share is the observation that metric *structure* — the hierarchy of beats, measures, phrases — is built from iterated doublings and triplings.

This hierarchy extends well beyond the level of individual note durations. At the level of *hypermetre*, phrases in tonal music characteristically span 4 or 8 bars (occasionally 3, 6, or 12). Binary dance movements in Bach's keyboard suites frequently have halves of 8, 12, 16, or 24 bars; fugue expositions and episodes can often be measured in units of 4 or 8 bars. Whether smooth bar-counts extend reliably to larger formal sections — development blocks, da capo spans — is less certain and would require systematic measurement.

The hypothesis that smooth-number structure operates beyond bar lengths — extending to the counts of various types of musical events within a piece — was previously formulated and tested manually by the present author (Vynograd, 2010; Vynograd & Seryachkov, 2010; Vynograd, 2013). Those studies examined several categories of "metric points" (equidistant rhythmic group counts, harmonic function counts per section, melodic contour-step counts, and formal proportions) across selected Bach keyboard and orchestral suites and found smooth-number outcomes across all four domains. The present study provides the first large-scale corpus validation of the same hypothesis, applied specifically to melodic interval-sequence motif occurrence counts across a corpus of 4,447 files.

The present study asks whether the same arithmetic governs one further level: the *multiplicity* with which a melodic motive recurs across the piece as a whole. This is a different question from bar-count smoothness: a motive does not appear once per bar in any regular fashion, so its total occurrence count cannot simply inherit smoothness from formal structure. The question is whether smooth-number alignment appears at the level of occurrence counts independently of such structural regularities.

### 2.2 Motif analysis

The automatic detection of melodic motifs in symbolic music has a substantial literature (Lartillot, 2005; Collins et al., 2010). Most approaches define a motif as a recurring pattern of pitches, intervals, or rhythmic values and rank candidates by some measure of salience. The present study uses a pipeline based on diatonic interval sequences extracted from a Music Encoding Initiative (MEI) representation: chromatic distinctions (major vs. minor third, etc.) are deliberately suppressed, following the principle that Bach's motivic technique operates at the level of melodic contour and step/leap distinction rather than exact chromatic content. All recurring patterns with at least two occurrences are retained after deduplication; no salience threshold or MDL filter is applied at this stage. (An MDL score is computed per pattern as a secondary quality indicator for manual exploration but plays no role in the corpus statistics.) The deliberate absence of a salience filter means the dataset includes incidental recurrences alongside compositionally intended motives; as argued in §1, this dilution works against finding smooth-number enrichment and therefore strengthens the result if the effect is nonetheless present.

### 2.3 Occurrence counts and statistical testing

Statistical analysis of symbolic music corpora has addressed questions of style, authorship, tonality, and formal structure (Huron, 2006; Temperley, 2007; Conklin, 2010). The specific question of whether numerical properties of occurrence counts are non-random appears to be new. The methodological challenge is that occurrence counts follow a steeply falling distribution (most motifs occur 2–4 times; very high counts are rare), so a naive uniform null model is misleading — smooth numbers would appear enriched simply because they cluster at low values where counts are common. We address this by using a *log-uniform* null model, in which the prior probability of observing count k is proportional to 1/k. Under this model, the expected smooth-number density is ~18.3% for the Bach corpus range; the observed density is ~41.2%, giving an enrichment ratio of 2.23×. We also apply a *shift test* as an additional check: if smooth counts are genuinely over-represented, counts shifted by ±1 should be less smooth-dense, and this asymmetry should be robust across threshold choices.

---

## 3. Corpus and Methods

### 3.1 Corpus

The corpus consists of 4,447 files analysed successfully in two formats: Humdrum **kern** (primarily from the CCARH MuseData and Ohio State University collections) and **MusicXML** (converted from LilyPond sources or downloaded from IMSLP). The Bach subset comprises keyboard works (Well-Tempered Clavier Books I and II, Two- and Three-Part Inventions), chorales, violin partitas and sonatas (BWV 1001–1006), and cello suites (BWV 1007–1012), together with selected keyboard suites and preludes. Additional composers in the extended corpus include Handel (1,169 files), Telemann (560 files), Corelli (251 files, primarily trio sonatas and concerti grossi), Domenico Scarlatti (65 keyboard sonatas), Buxtehude (21 files), Frescobaldi (40 files), Haydn (9 files), Mozart (241 files), Beethoven (148 files), and others.

All files were analysed successfully (0 parse errors).

### 3.2 Motif detection pipeline

As explained in §1, the analysis is deliberately non-selective: the algorithm extracts *all* recurring patterns from each piece, not only those deemed musically significant by a human analyst. The rationale is to avoid the circularity that would arise from counting only "important" motives, since the criterion of importance is not objectively definable. Every pattern that recurs at least twice contributes an occurrence count to the dataset; the statistical test then asks whether smooth numbers are over-represented in the full, unfiltered collection.

Score rendering and MEI extraction are performed by **verovio** 6.1.0. The analysis pipeline proceeds as follows:

1. **Voice separation.** The MEI is parsed into per-voice note sequences with absolute onset times in quarter notes. Grace notes are excluded; tied notes are merged; ornamental two-note slur pairs (appoggiaturas) are collapsed into single notes with combined duration.

2. **Interval computation.** For each consecutive pair of notes within a voice, a *diatonic interval* is computed: iv = (octave × 7 + diatonic step of note 2) − (octave × 7 + diatonic step of note 1). The chromatic alteration is discarded (C→E and C→E♭ both yield interval +2). This captures melodic motion at the level of step/leap/direction rather than exact chromatic content, reflecting the common analytical observation that Bach's motivic technique is robust to transposition and mode mixture.

3. **Feature tuple.** Each melodic step is represented as a tuple (interval, duration, metric phase, onset, contiguity flag). The *metric phase* of a note is its position within the beat, discretised to the note's own duration as a unit (e.g. eighth notes in 4/4 time have two phases: 0 = on the beat, 1 = off the beat). *Contiguity* is false if a rest intervenes between two notes; patterns spanning rests are excluded. Two patterns that share the same (interval, duration) body but differ in start phase are treated as distinct patterns, since metric placement is a primary component of motivic identity in tonal music.

4. **Pattern finding.** A sliding window of length 2 to unlimited scans each voice for recurring (interval, duration) sequences with matching start phase. This produces a large number of candidates, the majority of which are incidental substrings rather than compositionally intended motives. Candidates are deduplicated by sub-pattern dominance (a pattern is suppressed if it is a sub-sequence of a longer pattern with the same or higher occurrence count) and cyclic-shift equivalence. Inverted forms (all intervals negated) are merged with their direct counterparts; the reported count is the union (direct + inverted − coinciding positions). All patterns with at least two occurrences are candidates; they are ranked by occurrence count (descending), with pattern length as a tiebreaker, and up to 50 per piece are collected for the corpus statistics. This means the dataset is weighted toward higher occurrence counts — the region where the smooth-number effect is expected to be strongest.

A deliberate consequence of this approach is that pattern matching is mathematically exact. If a motif is defined as the interval sequence `+1 −1 +2`, then only occurrences of precisely that sequence are counted; a variant with one interval altered — even if a human listener would perceive it as "the same idea" — is a different pattern and is counted separately or not at all. This strictness is not a limitation but a methodological choice. Human motivic recognition is flexible, context-sensitive, and ultimately subjective: two analysts may disagree on whether a given passage instantiates a motif. The formal approach replaces that judgement with a fixed criterion — interval, duration, and metric phase — applied uniformly and without exception. Any relaxation of the criterion (allowing approximate intervals, or optional notes, or context-dependent boundaries) would reintroduce the analyst's ear as an uncontrolled variable, making the counts incomparable across pieces and analysts. The price is that the formal count will sometimes miss what a musician considers an obvious variant; the gain is that the counts are reproducible, objective, and suitable for statistical aggregation.

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

A detail at the very end of the piece is worth noting. Immediately after the 192nd occurrence of the figure, on the last beat before the closing chord, Bach writes what would have been the 193rd instance — but with the final sixteenth note subdivided into two thirty-second notes, rounding off the stepwise descent into a brief flourish. This subdivision, unusual in the context of the piece, prevents the pattern from being counted as a clean instance of the figure (the duration criterion is not met for the last note). Whether or not this ornamental adjustment was made with any awareness of the count, the result is that the total remains **192** rather than 193 — a smooth number rather than a prime.

[See Figure 1 in Appendix 1.]

### 4.2 WTC Book I, Fugue No. 12 in F minor BWV 857

The sixteenth-note figure `+1 +1 +1` (three ascending diatonic steps) serves as the principal countersubject of this fugue, entering in the answer voice already in bar 2. It is one of the most consistently recycled cells in the entire piece. Counted across all voices, the figure recurs exactly **96 times** — and 96 = 2^5 · 3.

[See Figure 2 in Appendix 1.]

### 4.3 Fugue in A minor BWV 944

This harpsichord fugue in 3/4 time has a subject that opens directly with the figure `1/16; phase 0; +2 −1 −1` — a rising third followed by two descending steps — as its very first notes, making it the subject's opening cell. The pattern appears **128 times** throughout the fugue: 128 = 2^7, one of the larger smooth counts observed in the Bach corpus.

[See Figure 3 in Appendix 1.]

---

## 5. Corpus Results

### 5.1 Bach (full corpus, 1,943 files)

The total number of retained motif-occurrence counts with k ≥ 8 is **30,251**. The smooth-number subset accounts for **11,170** of these. Under the log-uniform null model, the expected smooth count is approximately 5,002, giving an enrichment ratio of **2.23×**. Table 1 shows the frequency of occurrence counts at selected smooth values.

**Table 1.** Frequency of smooth occurrence counts in the Bach corpus (k ≥ 8).

| Count | Smooth? | Frequency |
|-------|---------|-----------|
| 8     | 2^3     | 3060 |
| 9     | 3^2     | 2508 |
| 12    | 2^2·3   | 1900 |
| 16    | 2^4     | 1001 |
| 18    | 2·3^2   | 981  |
| 24    | 2^3·3   | 511  |
| 27    | 3^3     | 375  |
| 32    | 2^5     | 308  |
| 36    | 2^2·3^2 | 192  |
| 48    | 2^4·3   | 103  |
| 54    | 2·3^3   | 82   |
| 64    | 2^6     | 51   |
| 72    | 2^3·3^2 | 28   |
| 81    | 3^4     | 19   |
| 96    | 2^5·3   | 13   |
| 108   | 2^2·3^3 | 14   |
| 128   | 2^7     | 10   |
| 144   | 2^4·3^2 | 3    |
| 192   | 2^6·3   | 1    |
| 216   | 2^3·3^3 | 1    |
| 288   | 2^5·3^2 | 2    |

For comparison, the immediately adjacent non-smooth count 10 appears 2,267 times and count 11 appears 1,865 times against 12's 1,900; count 25 appears 452 times against 24's 511; count 37 appears 196 times against 36's 192 and 32's 308. The enrichment at smooth positions is most clearly visible at thresholds ≥ 24, where the frequency distribution has thinned enough to reduce noise.

The shift test strengthens the conclusion. Table 2 shows the smooth density of real counts versus counts shifted by ±1, at several thresholds.

**Table 2.** Shift test results (Bach corpus, shifts +1 and −1).

| Threshold | n (real) | Density (real) | Density (+1) | Ratio +1 | Density (−1) | Ratio −1 |
|-----------|----------|----------------|--------------|----------|--------------|----------|
| ≥ 14 | 17124 | 0.216 | 0.232 | 0.93× | 0.197 | 1.10× |
| ≥ 16 | 14563 | 0.254 | 0.191 | **1.33×** | 0.231 | 1.10× |
| ≥ 18 | 12540 | 0.215 | 0.140 | **1.54×** | 0.187 | 1.15× |
| ≥ 24 | 8391  | 0.205 | 0.149 | **1.37×** | 0.188 | 1.09× |
| ≥ 32 | 5265  | 0.158 | 0.091 | **1.74×** | 0.140 | 1.13× |
| ≥ 36 | 4257  | 0.124 | 0.065 | **1.89×** | 0.118 | 1.05× |
| ≥ 48 | 2514  | 0.133 | 0.081 | **1.65×** | 0.121 | 1.10× |

The anomaly at threshold 14 (ratio < 1) reflects the high raw frequency of count 15 falling just below the smooth pair (16, 18). Above threshold 16, the shift ratio rises monotonically and is largest at high thresholds, where the signal-to-noise ratio is best. The effect is consistently stronger against the +1 shift than against the −1 shift across all thresholds ≥ 16 (1.33× vs. 1.10× at ≥16; 1.89× vs. 1.05× at ≥36), indicating that the count immediately *above* a smooth number is more reliably depleted than the count immediately *below* — an asymmetry discussed in §6.2.

### 5.2 Cross-composer comparison

Table 3 summarises enrichment ratios (log-uniform) for all composers with ≥ 15 files in the corpus.

**Table 3.** Smooth-number enrichment by composer.

| Composer | Files | Enrichment (log-uniform) |
|----------|-------|--------------------------|
| Bach (all) | 1,943 | 2.23× |
| Handel | 1,169 | 1.77× |
| Telemann | 560 | 1.97× |
| Corelli | 251 | 1.89× |
| Domenico Scarlatti | 65 | 1.99× |
| Frescobaldi | 40 | 1.70× |
| Buxtehude | 21 | 1.66× |
| Mozart | 241 | 2.05× |
| Beethoven | 148 | 1.66× |
| Haydn | 9 | 1.77× |

All values exceed 1.5×, suggesting that smooth-number alignment in motif counts is not a peculiarity of Bach but a general feature of metrically regular Western tonal music from roughly 1600 to 1800. The Handel and Telemann datasets are the two largest in the cross-composer comparison (1,169 and 560 files respectively), and both show robust enrichment (1.77× and 1.97×) confirmed by shift tests that are consistently positive from threshold ≥ 16 onward. The enrichment ratios for Handel and Telemann are close to Bach's (2.23×), suggesting that smooth-number alignment in motif counts is a general property of Baroque compositional practice rather than a distinguishing feature of Bach in particular. What does distinguish Bach is the *scale* of the smooth counts: in the Bach corpus, motifs recur at smooth counts reaching **96**, **128**, **192**, and **288**; in Handel the largest observed smooth count is **144** (a single instance), and in Telemann **81**. This difference in upper range reflects the greater density and elaboration of motivic development in Bach's contrapuntal writing, while the comparable enrichment ratios confirm that the underlying arithmetic principle operates across the Baroque repertoire regardless of compositional scale. The differences between composers are not large enough to draw firm conclusions from the present corpus sizes; a dedicated cross-composer study with larger per-composer samples is warranted.

The two Classical-period composers in the corpus show contrasting pictures. Mozart (241 files, 2.05×) matches Baroque enrichment levels without attenuation: the shift ratio against the +1 shift is consistently positive from threshold ≥ 16 (1.45×) through ≥ 96 (2.40×), and the ratio against the −1 shift stays near or above 1.0 across all but the highest threshold. The largest observed smooth count in the Mozart corpus is 216 (K. 459 and K. 622). Beethoven (148 files, 1.66×) presents a qualitatively different picture. While the +1 shift ratio is consistently positive (1.29× at ≥ 16), the −1 shift ratio falls systematically below 1.0 at high thresholds: 0.92× at ≥ 36, 0.75× at ≥ 48, 0.82× at ≥ 64. This means that counts just *below* a smooth number (N − 1) are denser than smooth counts themselves at these thresholds — an asymmetry opposite to the one observed for Bach and the Baroque composers, where smooth counts form a local density maximum. Whether this reflects a genuine stylistic shift in how repetition is organised in Beethoven, or is an artefact of the corpus composition (primarily string quartets and symphonies, with multi-movement structures counted as separate files), cannot be determined from the present data.

---

## 6. Discussion

### 6.1 Interpretation

Why would motif occurrence counts tend to be smooth numbers? A naive answer — that smooth counts are inherited from the smooth bar-counts of formal sections — does not hold up. Motifs do not appear once per bar in any regular fashion; they arise irregularly across voices, sections, and developmental episodes. A motive might enter in bar 1, bar 5, bars 9–12, and then again in the recapitulation, with no regular spacing. That such irregular occurrences should nonetheless sum to a smooth number is precisely the non-trivial observation that requires explanation.

A more plausible hypothesis points toward the organisation of memory rather than the organisation of form. Human memory — and arguably memory in biological neural networks more broadly — operates in hierarchical structures that favour powers of two and three: information is grouped, chunked, and rehearsed in units of 2, 4, 8 or 3, 6, 12. If the composer's internalised sense of "enough repetition" or "satisfying closure" is calibrated by these same memory structures, smooth-number totals would emerge as a byproduct of how musical material is retained and deployed, rather than as a consequence of any explicit counting or formal planning.

A more concrete formulation of this hypothesis (Vynograd, 2013) proposes that the brain maintains implicit binary-ternary "counters" for musical events during both listening and composition. If incoming events are stored by grouping signals into pairs and triples — the same chunking principle that governs note durations and metric hierarchy — then the counter's accumulated total at any stage is of the form 2^a·3^b. The sense of "complete" or "enough" would correspond to the counter reaching its most stable state, where all pairs and triplets are evenly filled. This account does not require the composer to consciously plan a smooth total; it only requires that the intuitive sense of closure is calibrated by a binary-ternary memory architecture operating below the threshold of awareness. The relationship between this conjecture and the empirical data remains an open question for future investigation.

A further observation bears on this hypothesis. In several pieces the smooth-number structure extends not merely to the union count of a motif and its inversion, but to the direct and inverted subcounts individually. In Bach's Invention No. 1 (BWV 772), the figure −1+2−1 in sixteenth notes occurs **24 times** in direct form and **8 times** in inverted form, for a union of **32** — and 24 = 2^3·3, 8 = 2^3, 32 = 2^5 are all smooth. The partition itself, not only the total, falls on smooth values. This would be a remarkable coincidence under any model in which direct and inverted occurrences are distributed independently; it suggests instead that the binary-ternary constraint operates separately on each form of the motif as it is deployed across the piece.

### 6.2 The shift-test asymmetry

The shift test reveals a consistent asymmetry: real counts are more strongly differentiated from shift+1 than from shift−1 (see Table 2, where the +1 ratios are systematically larger than the corresponding −1 ratios at thresholds ≥ 16). This means that the count immediately *above* a smooth number is more consistently depleted than the count immediately below. A possible explanation is that when a motive "aims" for a smooth count of N, the actual observed count is N or N−1 (one occurrence missed or merged) more often than N+1 (an extra stray occurrence added). This is consistent with composers treating smooth targets as upper bounds rather than exact specifications. The asymmetry is an empirical observation; we do not propose a causal mechanism here.

### 6.3 Limitations

**Algorithmic dependence.** The occurrence counts depend on the motif detection algorithm, which makes choices about pattern length, phase matching, and inversion merging. Different algorithmic choices would produce different count distributions. We have verified that the enrichment result is robust to the main parameter choices (minimum length ≥ 2 vs. ≥ 3, with and without inversion merging), but a comprehensive sensitivity analysis is left for future work.

**Inversion merging.** The union count (direct + inverted − coinciding) differs from the direct count by a variable amount that depends on how often the inverted form actually appears in the piece; in practice the ratio of inverted to direct occurrences varies widely across motifs and pieces. Merging therefore does not systematically double counts, and the doubling artefact (2N smooth whenever N smooth) does not apply. For transparency we report the enrichment both with and without inversion merging: direct-only **2.05×** vs. merged **2.23×**. The difference is modest (~9%), confirming that inversion merging does not artificially inflate the result.

**Corpus composition.** The corpus is not a representative sample of all Western tonal music; it over-represents Bach and keyboard music. The cross-composer comparison in §5.2 suggests the effect is widespread, but replication on a more balanced corpus is needed.

**Multiple testing.** Each piece contributes multiple occurrence counts, and the counts are not fully independent. However, the dataset is partially decorrelated by construction: a sub-pattern B is retained only if its occurrence count exceeds that of every parent pattern A that subsumes it — counts fully explained by a longer containing pattern are suppressed and do not appear as separate entries. The remaining source of dependence (multiple motifs per file) is mitigated by the fact that smooth counts appear distributed across independent files throughout the corpus. We treat this as a descriptive corpus study rather than a confirmatory statistical test; p-values are not reported.

### 6.4 Specificity control: prime numbers and the depletion counterpart

A natural question is whether the enrichment we observe is specific to smooth numbers, or whether it would appear for any arithmetically "notable" class — for instance, prime numbers. We applied the same log-uniform methodology to prime numbers (≥ 8) in the Bach corpus, and further partitioned the full range of observed counts by largest prime factor to identify which number class is *depleted* as a counterpart to the smooth-number enrichment.

Table 4 shows the full partition of the 30,251 Bach observations (k ≥ 8) by the arithmetic character of k.

**Table 4.** Enrichment by arithmetic class (Bach corpus, k ≥ 8, log-uniform model).

| Class | Description | Observed | Obs. % | Prior % | Enrichment |
|-------|-------------|----------|--------|---------|------------|
| 2^a·3^b | Smooth numbers | 11,170 | 36.9% | 16.5% | **2.23×** |
| Largest prime factor = 5 | e.g. 10, 15, 20, 25… | 5,460 | 18.0% | 11.6% | 1.56× |
| Largest prime factor = 7 | e.g. 14, 21, 28, 35… | 2,955 | 9.8% | 8.9% | 1.09× |
| Primes ≥ 11 | 11, 13, 17, 19, 23… | 7,406 | 24.5% | 22.6% | 1.08× |
| Composite, prime factor ≥ 11 | e.g. 11·2, 13·3, 11^2… | 3,260 | 10.8% | 40.4% | **0.27×** |

The five classes are mutually exclusive and exhaustive (observations sum to 30,251). The enrichment ratios are log-prior-weighted averages equal to 1.0 by construction — the table is internally consistent. Three observations stand out. First, the enrichment is a strictly *decreasing* function of the largest prime factor: 2.23× (factor ≤ 3) → 1.56× (factor ≤ 5) → 1.09× (factor ≤ 7) → 1.08× (primes, dominated by 11+). Second, prime numbers per se show near-chance enrichment (1.08×), confirming that being a "notable" number is not sufficient — the effect requires specifically the 2·3 structure. Third, and most importantly, the depletion is concentrated in numbers with a prime factor ≥ 11: these account for 40% of the log-prior weight but only 11% of observations, yielding a **0.27×** ratio. This group — numbers like 11, 22, 33, 44, 55, 66, 77, 88, 99… — is strongly avoided. The enrichment of smooth numbers is not a statistical artefact of normalisation; it is the mirror image of a genuine depletion of large-prime-factor counts.

### 6.5 Implications for computational music analysis and generation

The findings suggest a concrete direction for machine learning approaches to tonal music. Current neural-network models for music generation — whether token-based (Music Transformer and its successors) or diffusion-based — are trained to reproduce statistical regularities at the level of individual notes, chords, and short phrases, but have no mechanism to enforce smooth-number occurrence counts at the level of whole-piece structure. If such counts are indeed a property of coherent tonal composition rather than incidental noise, models trained without awareness of this constraint will tend to produce music that violates it — a subtle but potentially audible source of the sense that AI-generated music, however locally fluent, lacks large-scale compositional logic. Incorporating a smooth-count prior as a structural constraint — for instance, as a regularisation term on the total count of a recurring cell, or as part of a hierarchical generative model with explicit "how many times" latent variables — is a testable modification that could improve the coherence of generated output.

Beyond generation, the binary-ternary structure of occurrence counts motivates a specific hypothesis about the *internal organisation* of a motif's appearances within a piece. The present analysis counts only the total number of occurrences; it does not examine how those occurrences are distributed across the piece's timeline or how the motif is transposed at each entry. A natural conjecture is that the sequence of entries is itself hierarchically organised: occurrences may cluster into groups of 2 or 3 at each structural level, with transpositions following a corresponding binary or ternary pattern. If such hierarchical grouping exists, it would explain *why* totals are smooth — they would be products of the smooth sub-group sizes — and would represent a deeper level of binary-ternary architecture in compositional structure than the mere smoothness of the total count. Testing this hypothesis requires a sequential analysis of motif-entry timelines combined with transposition profiles, which the present tool already computes per motif; applying it systematically across the corpus is a natural next step.

---

## 7. Conclusion

We have shown that motif occurrence counts in a large corpus of 1,943 Bach works are smooth numbers (of the form 2^a · 3^b) approximately 2.23× more often than expected under a log-uniform null model, with the excess confirmed by a shift test that is robust to threshold choice and reaches 1.89× at threshold ≥ 36. The pattern is consistent across Baroque composers (Handel 1.77×, Telemann 1.97×, Corelli 1.89×, Scarlatti 1.99×, Buxtehude 1.66×, Frescobaldi 1.70×) and extends into the Classical period: Mozart (2.05×) shows enrichment fully comparable to the Baroque corpus, while Beethoven (1.66×) shows a related but structurally different pattern in which the −1 shift ratio drops below 1.0 at high count thresholds, suggesting the binary-ternary constraint operates differently in his style.

The result documents a level of smooth-number organisation that has not previously been described: not in note durations or bar lengths, but in the count of times a structural element recurs across a piece. Three individual pieces from Bach illustrate the pattern with particular clarity: WTC I Prelude No. 7 (**192** occurrences), WTC I Fugue No. 12 (**96** occurrences), and BWV 944 Fugue (**128** occurrences). Since motifs appear irregularly within a piece — not once per bar, not in any predictable spacing — a purely formal or structural explanation does not account for the result. The mechanism remains an open question; we tentatively suggest that it may be rooted in the binary-ternary organisation of memory and repetition in biological neural systems, but this hypothesis requires independent investigation.

---

## Acknowledgements

The kern files analysed in this study are drawn from the CCARH MuseData collection and the Ohio State University kern corpus. Score rendering and MEI extraction are performed by the verovio music engraving library (version 6.1.0).

## Declaration of Interest

The author reports there are no competing interests to declare.

## Funding

This research received no external funding.

## Data Availability

The motif analysis tool and the full corpus of kern and MusicXML files analysed in this study are freely available at https://github.com/vindomestic-oss/m_a.

---

## References

Collins, T., Thurlow, J., Laney, R., Willis, A., & Garthwaite, P. H. (2010). A comparative evaluation of algorithms for discovering translational patterns in Baroque keyboard works. In *Proceedings of the 11th International Society for Music Information Retrieval Conference (ISMIR)* (pp. 3–8).

Conklin, D. (2010). Discovery of contrapuntal patterns. In *Proceedings of the 11th International Society for Music Information Retrieval Conference (ISMIR)* (pp. 201–206).

Huron, D. (2006). *Sweet anticipation: Music and the psychology of expectation*. MIT Press.

Lartillot, O. (2005). Efficient extraction of closed motivic patterns in multi-voice music corpora. In *Proceedings of the 6th International Society for Music Information Retrieval Conference (ISMIR)* (pp. 191–198).

London, J. (2004). *Hearing in time: Psychological aspects of musical meter*. Oxford University Press.

Pressing, J. (1983). Cognitive isomorphisms between pitch and rhythm in world musics: West Africa, the Balkans and Western tonality. *Studies in Music*, *17*, 38–61.

Temperley, D. (2007). *Music and probability*. MIT Press.

Vynograd, A. (2010). Гиперметрическая регулярность в ритме смены гармонических функций на примерах из произведений И.С. Баха [Hypermetric regularity in the rhythm of harmonic-function changes, illustrated from J.S. Bach]. *Sovremennye problemy nauki i obrazovaniya*. http://online.rae.ru/470

Vynograd, A. (2013). *Mnogoobraziye proyavleniy muzykal'nogo metra* [The many manifestations of musical metre]. LAP LAMBERT Academic Publishing.

Vynograd, A., & Seryachkov, V. (2010). Насколько крупным может быть музыкальный метр? [How large can musical metre be?]. In *Protsessy muzykal'nogo tvorchestva* (Vol. 11). Moscow.

---

## Appendix 1: Annotated Score Excerpts

Each excerpt shows the system containing the first occurrence of the motif and the system containing the last occurrence. Where a motif and its inversion are counted separately, the caption gives the format "N direct / M inverted / total".

The excerpts were generated with kern_reader, an open-source score browser and motif-search tool developed for this study. To reproduce: clone https://github.com/vindomestic-oss/m_a, then `pip install verovio music21 pillow` and run `python kern_reader.py`.

### Article Figures (§4)

![BWV 852](docx_images/image1.png)

**Figure 1.** BWV 852, WTC I Prelude 7 in E♭ major — 1/16; phase 1; +1+1 and inversion — **192** occurrences (2^6·3)

![BWV 857](docx_images/image2.png)

**Figure 2.** BWV 857, WTC I Fugue 12 in F minor — 1/16; phase 1; +1+1+1 and inversion — **96** occurrences (2^5·3)

![BWV 944](docx_images/image3.png)

**Figure 3.** BWV 944, Fugue in A minor — 1/16; phase 0; +2−1−1 and inversion — **128** occurrences (2^7)

### Inventions

![BWV 772](docx_images/image4.png)

**Figure 4.** BWV 772, Invention 1 — 1/16; −1−1−1+2−1+2−1 — **27** occurrences

![BWV 772](docx_images/image5.png)

**Figure 5.** BWV 772, Invention 1 — 1/16; −1+2−1 — **24** direct / **8** inverted / **32** total

![BWV 773](docx_images/image6.png)

**Figure 6.** BWV 773, Invention 2 — (1/4)1/16; −1−1−1 with inversion — **36** occurrences (opening cell of the subject)

![BWV 773](docx_images/image7.png)

**Figure 7.** BWV 773, Invention 2 — 1/16; −1−1−1−1−1 — **16** occurrences

### Sinfonias

![BWV 787](docx_images/image8.png)

**Figure 8.** BWV 787, Sinfonia 1 — 1/16; −1+1+1 — **27** occurrences

![BWV 787](docx_images/image9.png)

**Figure 9.** BWV 787, Sinfonia 1 — 1/16; +1+1+1+1+1+1+1 — **24** occurrences

![BWV 788](docx_images/image10.png)

**Figure 10.** BWV 788, Sinfonia 2 — 1/8; +0−2 — **24** occurrences

![BWV 788](docx_images/image11.png)

**Figure 11.** BWV 788, Sinfonia 2 — 1/8; +1+1 — **16** direct / 11 inverted / **27** total

![BWV 788](docx_images/image12.png)

**Figure 12.** BWV 788, Sinfonia 2 — 1/16; −1−1−1−1−1 — 20 occurrences

### Well-Tempered Clavier I

![BWV 846](docx_images/image13.png)

**Figure 13.** BWV 846, Fugue 1 in C major — 1/8; +1+1+1 — **24** occurrences (opening cell of the subject)

![BWV 846](docx_images/image14.png)

**Figure 14.** BWV 846, Fugue 1 in C major — 1/32; −1−1 — **24** direct / **3** inverted / **27** total

![BWV 847](docx_images/image15.png)

**Figure 15.** BWV 847, Fugue 2 in C minor — 1/8; −1−1 — **18** occurrences

![BWV 857](docx_images/image2.png)

**Figure 16.** BWV 857, Fugue 12 in F minor — 1/16; +1+1+1 — **96** occurrences

### Well-Tempered Clavier II

![BWV 870](docx_images/image16.png)

**Figure 17.** BWV 870, Prelude 1 in C major — 1/16; −1+1 — **32** occurrences

![BWV 870](docx_images/image17.png)

**Figure 18.** BWV 870, Prelude 1 in C major — 1/16; +1+1 — **24** occurrences

![BWV 871](docx_images/image18.png)

**Figure 19.** BWV 871, Fugue 1 in C major — 1/16; +1+1−2+1−2 — **27** occurrences

![BWV 871](docx_images/image19.png)

**Figure 20.** BWV 871, Fugue 1 in C major — thematic seed 1/16,1/16,>1/16; −1+1 — **32** occurrences

![BWV 882](docx_images/image20.png)

**Figure 21.** BWV 882, Fugue 11 in F major — 1/16; +1+1 — **72** occurrences

![BWV 882](docx_images/image21.png)

**Figure 22.** BWV 882, Fugue 11 in F major — 1/16; −1+1 — **18** occurrences

![BWV 893](docx_images/image22.png)

**Figure 23.** BWV 893, Prelude 22 in B♭ minor — (1/2)1/8; −1−1−1 — **27** occurrences (opening cell of the subject)

![BWV 893](docx_images/image23.png)

**Figure 24.** BWV 893, Prelude 22 in B♭ minor — 1/8; −1−1−1 — **81** occurrences

![BWV 893](docx_images/image24.png)

**Figure 25.** BWV 893, Fugue 22 in B♭ minor — 1/8; +1+1 — **108** occurrences

![BWV 893](docx_images/image25.png)

**Figure 26.** BWV 893, Fugue 22 in B♭ minor — 1/4; −4+1 — **27** occurrences

![BWV 888](docx_images/image26.png)

**Figure 27.** BWV 888, Fugue 19 in A major — 1/16; −1−1 — **81** occurrences

![BWV 888](docx_images/image27.png)

**Figure 28.** BWV 888, Fugue 19 in A major — 1/16; −1−1+1−3+1+1−1 — **32** direct / **4** inverted / **36** total (second element of the subject)

### French Suites

![BWV 812](docx_images/image28.png)

**Figure 29.** BWV 812, French Suite 1, Gigue — 1/32; −1−1 — 25 direct / **16** inverted / **36** total

![BWV 812](docx_images/image29.png)

**Figure 30.** BWV 812, French Suite 1, Gigue — thematic element +1−1−1−1−1+2 — **9** direct / 7 inverted / **16** total

![BWV 817](docx_images/image30.png)

**Figure 31.** BWV 817, French Suite 6, Gigue — 1/16; −1−1+1+1+1 — **18** occurrences

### The Art of Fugue

![Contrapunctus XI](docx_images/image31.png)

**Figure 32.** Contrapunctus XI — 1/8; +1+0+0 — 68 direct / **24** inverted / **81** total

![Contrapunctus XI](docx_images/image32.png)

**Figure 33.** Contrapunctus XI — 1/8; +0+0−2+1 — **54** occurrences

![Contrapunctus XI](docx_images/image33.png)

**Figure 34.** Contrapunctus XI — 1/8; +1+0+0−2+1 — **48** occurrences

![Contrapunctus XI](docx_images/image34.png)

**Figure 35.** Contrapunctus XI — full motif −2+1+0+0−2+1 — **24** occurrences

![Contrapunctus XI](docx_images/image35.png)

**Figure 36.** Contrapunctus XI — (1/2)1/8,1/8,>1/8; +1−1 with inversion — **24** / **48** occurrences

### Organ Works

![BWV 668](docx_images/image36.png)

**Figure 37.** BWV 668, "Vor deinen Thron" — 1/8; +1+1 — **81** occurrences

![BWV 529](docx_images/image37.png)

**Figure 38.** BWV 529, Organ Concerto in D minor, mvt. I — 1/16; −1−1 — **128** occurrences

![BWV 529](docx_images/image38.png)

**Figure 39.** BWV 529, mvt. I — thematic seed −1+1+2−2−1+1 — **36** occurrences

![BWV 529](docx_images/image39.png)

**Figure 40.** BWV 529, mvt. I — 1/8; −2+2 — **36** occurrences

![BWV 544](docx_images/image40.png)

**Figure 41.** BWV 544, Prelude and Fugue in B minor, mvt. II — 1/8; +1+1+1 — **96** occurrences

![BWV 544](docx_images/image41.png)

**Figure 42.** BWV 544, mvt. II — 1/8; −1+1+1 — **81** occurrences

### Violin Partitas

![BWV 1002](docx_images/image42.png)

**Figure 43.** BWV 1002, Partita 1 — 1/16; −1−1−1−1 — **48** occurrences

![BWV 1002](docx_images/image43.png)

**Figure 44.** BWV 1002, Partita 1 — 1/16; +1+1+1+1+1+1+1 — **32** occurrences

![BWV 1002](docx_images/image44.png)

**Figure 45.** BWV 1002, Partita 1 — 1/16; +1+1+1+1+1+1+1+1+1 — **18** occurrences

---

## Appendix 2: Score Excerpts — Top Bach Motifs

The automated analysis described in §3 is deliberately non-selective: every recurring figure that satisfies the minimum occurrence threshold contributes to the statistical analysis, regardless of whether it would be considered thematically significant by a human analyst. This is essential for the validity of the corpus statistics.

Once the ranked list exists, however, there is no methodological barrier to examining the actual score for selected figures and asking whether the counts are comprehensible in musical terms. This appendix presents the top-ranked motifs (highest occurrence count per piece) from the analysed WTC I–II, Inventions, and Violin Partitas and Sonatas, together with brief observations where the musical situation is particularly clear.

The motif patterns are given in the search format `dur;phase;intervals` (e.g. `1/16;0;+1+1`). Counts are shown as "N direct / M inverted / total" when both forms are present, or as a single total when only the union is relevant.

### Well-Tempered Clavier I, Preludes

![BWV 852](docx_images/image45.png)

**Figure 46.** BWV 852, Prelude 7 in E♭ major — 1/16;1;+1+1 — 93 direct / 107 inverted / **192** total

![BWV 859](docx_images/image46.png)

**Figure 47.** BWV 859, Prelude 14 in F♯ minor — 1/16;0;−1−1+2 — 50 direct / 15 inverted / **64** total

![BWV 864](docx_images/image47.png)

**Figure 48.** BWV 864, Prelude 19 in A major — 1/16;0;+1+1 — 23 direct / 45 inverted / **64** total

### Well-Tempered Clavier I, Fugues

![BWV 857](docx_images/image48.png)

**Figure 49.** BWV 857, Fugue 12 in F minor — 1/16;1;+1+1+1 — 62 direct / 38 inverted / **96** total

![BWV 854](docx_images/image49.png)

**Figure 50.** BWV 854, Fugue 9 in E major — 1/16;0;−1+1 — 71 direct / 1 inverted / **72** total

![BWV 859](docx_images/image50.png)

**Figure 51.** BWV 859, Fugue 14 in F♯ minor — 1/8;1;+1+1+1 — 39 direct / 19 inverted / **54** total

![BWV 862](docx_images/image51.png)

**Figure 52.** BWV 862, Fugue 17 in A♭ major — 1/16;1;−1−1−1 — 29 direct / **27** inverted / **54** total

![BWV 862](docx_images/image52.png)

**Figure 53.** BWV 862, Fugue 17 in A♭ major — 1/16;3;+1+1+1 — 14 direct / 34 inverted / **48** total

![BWV 860](docx_images/image53.png)

**Figure 54.** BWV 860, Fugue 15 in G major — 1/16;3;−1−1−1 — 37 direct / 11 inverted / **48** total

![BWV 866](docx_images/image54.png)

**Figure 55.** BWV 866, Fugue 21 in B♭ major — 1/16;0;−1−1−1 — 19 direct / 29 inverted / **48** total

![BWV 869](docx_images/image55.png)

**Figure 56.** BWV 869, Fugue 24 in B minor — 1/16;3;−1+1+1 — 41 direct / 7 inverted / **48** total

### Well-Tempered Clavier II, Preludes

![BWV 893](docx_images/image56.png)

**Figure 57.** BWV 893, Prelude 22 in B♭ minor — 1/8;0;−1−1−1 — 43 direct / 42 inverted / **81** total

![BWV 893](docx_images/image57.png)

**Figure 58.** BWV 893, Prelude 22 in B♭ minor — 1/8;0;+1+1+1+1−2 — 35 direct / 17 inverted / **48** total (second element of the subject)

![BWV 888](docx_images/image58.png)

**Figure 59.** BWV 888, Prelude 19 in A major — 1/8;0;+2−1 — 34 direct / 14 inverted / **48** total

### Well-Tempered Clavier II, Fugues

![BWV 893](docx_images/image59.png)

**Figure 60.** BWV 893, Fugue 22 in B♭ minor — 1/8;0;+1+1 — 66 direct / 53 inverted / **108** total

![BWV 893](docx_images/image60.png)

**Figure 61.** BWV 893, Fugue 22 in B♭ minor — 1/4;0;−4+1 — **27** direct / 23 inverted / **48** total

![BWV 889](docx_images/image61.png)

**Figure 62.** BWV 889, Fugue 20 in A minor — 1/32;2;−1−1 — 56 direct / 40 inverted / **96** total

![BWV 889](docx_images/image62.png)

**Figure 63.** BWV 889, Fugue 20 in A minor — 1/32;1;−1−1−1 — 53 direct / 19 inverted / **72** total

![BWV 888](docx_images/image63.png)

**Figure 64.** BWV 888, Fugue 19 in A major — 1/16;1;−1−1 — 52 direct / 45 inverted / **81** total

![BWV 882](docx_images/image64.png)

**Figure 65.** BWV 882, Fugue 11 in F major — 1/16;0;+1+1 — 38 direct / 38 inverted / **72** total

![BWV 873](docx_images/image65.png)

**Figure 66.** BWV 873, Fugue 4 in C♯ minor — 1/16;1;+1+1+1 — 19 direct / 45 inverted / **64** total

![BWV 873](docx_images/image66.png)

**Figure 67.** BWV 873, Fugue 4 in C♯ minor — 1/16;0;−1+1−2+3 — 41 direct / 7 inverted / **48** total

![BWV 885](docx_images/image67.png)

**Figure 68.** BWV 885, Fugue 14 in F♯ minor — 1/16;0;−1−1+2 — 37 direct / **18** inverted / **54** total

![BWV 877](docx_images/image68.png)

**Figure 69.** BWV 877, Fugue 8 in D♯ minor — 1/8;0;+1+1 — 28 direct / 23 inverted / **48** total

![BWV 887](docx_images/image69.png)

**Figure 70.** BWV 887, Fugue 18 in G♯ minor — 1/8;0;+1+1−1 — 14 direct / **36** inverted / **48** total

### Inventions

![BWV 774](docx_images/image70.png)

**Figure 71.** BWV 774, Invention 3 in D major — 1/16;3;−1−1 — 38 direct / 11 inverted / **48** total

![BWV 780](docx_images/image71.png)

**Figure 72.** BWV 780, Invention 9 in F minor — 1/16;1;+1+1+1 — 14 direct / **36** inverted / **48** total

![BWV 782](docx_images/image72.png)

**Figure 73.** BWV 782, Invention 11 in G minor — 1/16;1;+1+1+1 — 19 direct / 31 inverted / **48** total

### Violin Partitas and Sonatas

![BWV 1002](docx_images/image73.png)

**Figure 74.** BWV 1002, Partita 1, mvt. 8 (Double) — 1/8;0;−1−1 — 31 direct / 23 inverted / **54** total

![BWV 1002](docx_images/image74.png)

**Figure 75.** BWV 1002, Partita 1, mvt. 4 (Double) — 1/16;2;−1−1−1−1 — 28 direct / 20 inverted / **48** total

![BWV 1003](docx_images/image75.png)

**Figure 76.** BWV 1003, Sonata 2, mvt. 4 (Fuga) — 1/16;2;−1−1 — **48** occurrences

---

## Author Note

Alexander Vynograd, independent researcher.

Correspondence concerning this article should be addressed to Alexander Vynograd. Email: vin.domestic@gmail.com

The analysis tool and corpus are available at https://github.com/vindomestic-oss/m_a.



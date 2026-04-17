%% ly_dump.ily
%% Direct LilyPond → note data extractor (no MIDI).
%% Hooks toplevel-score-handler; outputs JSON-lines to ly:dump-output-file.
%%
%% Usage: in a wrapper .ly file:
%%   #(define ly:dump-output-file "/abs/path/to/out.jsonl")
%%   \include "/abs/path/to/ly_dump.ily"
%%   \include "original_file.ly"

\version "2.24.0"

%% Output file path — set before including this file
#(define ly:dump-output-file
   (if (defined? 'ly:dump-output-file) ly:dump-output-file #f))

%% Internal state
#(define %dump-port  #f)
#(define %dump-score 0)
#(define %dump-staff-counter 0)
#(define %cur-staff "1")   %% mutable: updated by ContextChange at any nesting depth

%% ── helpers ──────────────────────────────────────────────────────────────────

#(define (dump-onset m)
   ;; moment → "n/d" string (or "n" if d=1)
   (let ((n (ly:moment-main-numerator m))
         (d (ly:moment-main-denominator m)))
     (if (= d 1) (number->string n)
         (string-append (number->string n) "/" (number->string d)))))

#(define (dump-write . args)
   (when %dump-port
     (for-each (lambda (a) (display a %dump-port)) args)
     (newline %dump-port)))

%% ── recursive music traversal ────────────────────────────────────────────────

#(define (dump-traverse m onset staff voice)
   ;; Returns new onset moment.
   (let ((name (ly:music-property m 'name)))
     (cond

       ;; ── Grace notes (appoggiatura, acciaccatura, \grace) — skip, don't advance onset
       ((memq name '(GraceMusic AppoggiaturaMusic AcciaccaturaMusic SlashedGraceMusic))
        onset)

       ;; ── Relative octave: resolve in-place, then recurse into inner element
       ((eq? name 'RelativeOctaveMusic)
        (let ((ref (ly:music-property m 'pitch (ly:make-pitch 0 0 0))))
          (ly:relative-octave-music::relative-callback m ref))
        (let ((inner (ly:music-property m 'element #f))
              (elts  (ly:music-property m 'elements '())))
          (if inner
              (dump-traverse inner onset staff voice)
              (let loop ((es elts) (t onset))
                (if (null? es) t
                    (loop (cdr es) (dump-traverse (car es) t staff voice)))))))

       ;; ── EventChord: multiple notes at same onset (e.g. <c e g>4)
       ((eq? name 'EventChord)
        (let ((elts (ly:music-property m 'elements '())))
          (let loop ((es elts) (max-end onset))
            (if (null? es) max-end
                (let ((end (dump-traverse (car es) onset staff voice)))
                  (loop (cdr es)
                        (if (ly:moment<? max-end end) end max-end)))))))

       ;; ── Single note
       ((eq? name 'NoteEvent)
        (let* ((pitch (ly:music-property m 'pitch))
               (dur   (ly:music-property m 'duration))
               (arts  (ly:music-property m 'articulations '()))
               (tie   (any (lambda (a)
                             (eq? (ly:music-property a 'name) 'TieEvent))
                           arts))
               ;; b8\rest → NoteEvent with RestEvent in articulations (pitched rest)
               (is-rest (any (lambda (a)
                               (eq? (ly:music-property a 'name) 'RestEvent))
                             arts)))
          (when (and %dump-port (ly:pitch? pitch) (ly:duration? dur))
            (let ((len (ly:duration-length dur)))
              (if is-rest
                  ;; Pitched rest (b8\rest) — emit as R, not N
                  (dump-write
                   "{\"t\":\"R\""
                   ",\"on\":\"" (dump-onset onset) "\""
                   ",\"dur\":\"" (dump-onset len) "\""
                   ",\"st\":\"" %cur-staff "\""
                   ",\"vc\":\"" voice "\""
                   "}")
                  (dump-write
                   "{\"t\":\"N\""
                   ",\"on\":\"" (dump-onset onset) "\""
                   ",\"dur\":\"" (dump-onset len) "\""
                   ",\"semi\":"  (modulo (ly:pitch-semitones pitch) 12)
                   ",\"oct\":"   (ly:pitch-octave pitch)
                   ",\"step\":"  (ly:pitch-notename pitch)
                   ",\"st\":\"" %cur-staff "\""
                   ",\"vc\":\"" voice "\""
                   ",\"tie\":"  (if tie "true" "false")
                   "}"))
              (ly:moment-add onset len)))
          ;; if no duration (shouldn't happen for normal notes) return onset
          (if (ly:duration? dur)
              (ly:moment-add onset (ly:duration-length dur))
              onset)))

       ;; ── Rest — emit R event and advance time; SkipEvent advances only
       ((eq? name 'RestEvent)
        (let ((dur (ly:music-property m 'duration)))
          (when (and %dump-port (ly:duration? dur))
            (let ((len (ly:duration-length dur)))
              (dump-write
               "{\"t\":\"R\""
               ",\"on\":\"" (dump-onset onset) "\""
               ",\"dur\":\"" (dump-onset len) "\""
               ",\"st\":\"" %cur-staff "\""
               ",\"vc\":\"" voice "\""
               "}")))
          (if (ly:duration? dur)
              (ly:moment-add onset (ly:duration-length dur))
              onset)))

       ((eq? name 'SkipEvent)
        (let ((dur (ly:music-property m 'duration)))
          (if (ly:duration? dur)
              (ly:moment-add onset (ly:duration-length dur))
              onset)))

       ;; ── SkipMusic (\skip dur  or  \skip dur*n) — same as SkipEvent but
       ;; produced by the \skip music function (has 'duration, not 'element)
       ((eq? name 'SkipMusic)
        (let ((dur (ly:music-property m 'duration #f)))
          (if (ly:duration? dur)
              (ly:moment-add onset (ly:duration-length dur))
              onset)))

       ;; ── Partial measure (\partial dur) — emit P event, don't advance onset
       ((eq? name 'PartialSet)
        (let ((dur (ly:music-property m 'duration #f)))
          (when (and %dump-port (ly:duration? dur))
            (dump-write
             "{\"t\":\"P\""
             ",\"on\":\"" (dump-onset onset) "\""
             ",\"dur\":\"" (dump-onset (ly:duration-length dur)) "\""
             "}")))
        onset)

       ;; ── ContextChange (\change Staff = "other") — update %cur-staff at any nesting depth
       ((eq? name 'ContextChange)
        (let ((new-id (ly:music-property m 'change-to-id "")))
          (when (not (string-null? new-id))
            (set! %cur-staff new-id)))
        onset)

       ;; ── Property set — detect \set Timing.measurePosition for pickup detection
       ;; \partialPickup = \set Timing.measurePosition = #(ly:make-moment 7/8) pattern
       ;; emits MP event so Python can compute pickup_shift = measurePosition quarters
       ((memq name '(PropertySet ContextPropertySet))
        (let ((sym (ly:music-property m 'symbol #f))
              (val (ly:music-property m 'value #f)))
          (when (and %dump-port
                     (eq? sym 'measurePosition)
                     (ly:moment? val)
                     (> (ly:moment-main-numerator val) 0))
            (dump-write
             "{\"t\":\"MP\""
             ",\"on\":\"" (dump-onset onset) "\""
             ",\"pos\":\"" (dump-onset val) "\""
             "}")))
        onset)

       ;; ── Volta repeat: \repeat "volta" N { body } [\alternative { { a1 } ... }]
       ;; Emits BAR start-repeat/end-repeat and VOLTA start/stop events.
       ((eq? name 'VoltaRepeatedMusic)
        (let* ((body (ly:music-property m 'element #f))
               (alts (ly:music-property m 'elements '()))
               (body-end (begin
                           (when %dump-port
                             (dump-write
                              "{\"t\":\"BAR\""
                              ",\"on\":\"" (dump-onset onset) "\""
                              ",\"bar\":\"start-repeat\""
                              "}"))
                           (if body
                               (dump-traverse body onset staff voice)
                               onset))))
          (if (null? alts)
              ;; No alternatives: simple end-repeat barline
              (begin
                (when %dump-port
                  (dump-write
                   "{\"t\":\"BAR\""
                   ",\"on\":\"" (dump-onset body-end) "\""
                   ",\"bar\":\"end-repeat\""
                   "}"))
                body-end)
              ;; Alternatives: volta brackets
              (let loop ((as alts) (n 1) (cur body-end) (max-end body-end))
                (if (null? as)
                    max-end
                    (begin
                      (when %dump-port
                        (dump-write
                         "{\"t\":\"VOLTA\""
                         ",\"on\":\"" (dump-onset cur) "\""
                         ",\"volta-type\":\"start\""
                         ",\"n\":" n
                         "}"))
                      (let ((a-end (dump-traverse (car as) cur staff voice)))
                        (when %dump-port
                          (dump-write
                           "{\"t\":\"VOLTA\""
                           ",\"on\":\"" (dump-onset a-end) "\""
                           ",\"volta-type\":\"stop\""
                           ",\"n\":" n
                           "}"))
                        (loop (cdr as) (+ n 1) a-end
                              (if (ly:moment<? max-end a-end) a-end max-end)))))))))

       ;; ── Unfolded repeat: \repeat unfold N { body }
       ;; Generic fallback only traverses body once; must loop N times explicitly.
       ((eq? name 'UnfoldedRepeatedMusic)
        (let* ((body (ly:music-property m 'element #f))
               (n    (ly:music-property m 'repeat-count 1)))
          (let loop ((i n) (t onset))
            (if (= i 0) t
                (loop (- i 1)
                      (if body (dump-traverse body t staff voice) t))))))

       ;; ── Multi-measure rest (R1*3/4) — advance onset by total music length
       ;; ly:music-length handles multiplied durations correctly
       ((memq name '(MultiMeasureRestMusic MultiMeasureRestEvent))
        (ly:moment-add onset (ly:music-length m)))

       ;; ── Time signature — emit event and don't advance onset
       ((eq? name 'TimeSignatureMusic)
        (let ((num (ly:music-property m 'numerator 4))
              (den (ly:music-property m 'denominator 4)))
          (when %dump-port
            (dump-write
             "{\"t\":\"T\""
             ",\"on\":\"" (dump-onset onset) "\""
             ",\"num\":" num
             ",\"den\":" den
             ",\"st\":\"" %cur-staff "\""
             "}"))
          onset))

       ;; ── Key change — emit and don't advance
       ;; Note: 'mode property is unreliable in 2.24; compute sharps from pitch-alist instead.
       ;; pitch-alist entries: (step . alteration) where alteration 1/2 = one sharp, -1/2 = one flat.
       ((eq? name 'KeyChangeEvent)
        (let* ((tonic  (ly:music-property m 'tonic))
               (pal    (ly:music-property m 'pitch-alist '()))
               (sharps (apply + (map (lambda (pair)
                                       (cond ((> (cdr pair) 0) 1)
                                             ((< (cdr pair) 0) -1)
                                             (else 0)))
                                     pal))))
          (when (and %dump-port (ly:pitch? tonic))
            (dump-write
             "{\"t\":\"K\""
             ",\"on\":\"" (dump-onset onset) "\""
             ",\"semi\":" (modulo (ly:pitch-semitones tonic) 12)
             ",\"step\":" (ly:pitch-notename tonic)
             ",\"sharps\":" sharps
             ",\"st\":\"" %cur-staff "\""
             "}"))
          onset))

       ;; ── Simultaneous music: voice splits or staff layout
       ((eq? name 'SimultaneousMusic)
        (let* ((elts (ly:music-property m 'elements '()))
               ;; Detect grand-staff layout: SimultaneousMusic with 1+ staff-like children.
               ;; "Staff-like" = anonymous Staff/TabStaff/DrumStaff/RhythmicStaff child, OR
               ;; any StaffGroup/GrandStaff/PianoStaff/ChoirStaff child (which itself contains
               ;; multiple staves).  Threshold >= 1 ensures that a single \new Staff inside a
               ;; StaffGroup (e.g. continuo staff) also gets an auto-numbered ID — otherwise
               ;; its inner SimultaneousMusic would have cnt=1 < 2 and fall through to staff="1".
               ;; \clef/\key expansions are ContextSpeccedMusic{Staff} inside SequentialMusic,
               ;; not direct SimultaneousMusic children, so no false positives.
               (has-staff-children
                (let scan ((es elts) (cnt 0))
                  (if (>= cnt 1) #t
                      (if (null? es) #f
                          (let* ((e (car es))
                                 (ctype (and (ly:music? e)
                                             (eq? (ly:music-property e 'name) 'ContextSpeccedMusic)
                                             (ly:music-property e 'context-type 'x)))
                                 (is-anon-staff
                                  (and ctype
                                       (or (and (memq ctype '(Staff TabStaff DrumStaff RhythmicStaff))
                                                (string-null? (ly:music-property e 'context-id "")))
                                           (memq ctype '(StaffGroup GrandStaff PianoStaff ChoirStaff))))))
                            (scan (cdr es) (if is-anon-staff (+ cnt 1) cnt)))))))) ;; closes: body/let*/inner-if/outer-if/let-scan/binding-pair/binding-list
          (let loop ((es elts) (v 1) (max-end onset))
            (if (null? es) max-end
                (let* ((e (car es))
                       (new-voice (string-append voice "." (number->string v)))
                       ;; Pre-assign staff ID for anonymous Staff children of a grand-staff block
                       (new-staff
                        (if (and has-staff-children
                                 (ly:music? e)
                                 (eq? (ly:music-property e 'name) 'ContextSpeccedMusic)
                                 (memq (ly:music-property e 'context-type 'x)
                                       '(Staff TabStaff DrumStaff RhythmicStaff))
                                 (string-null? (ly:music-property e 'context-id "")))
                            (begin
                              (set! %dump-staff-counter (+ %dump-staff-counter 1))
                              (number->string %dump-staff-counter))
                            staff))
                       (end (dump-traverse e onset new-staff new-voice)))
                  (loop (cdr es) (+ v 1)
                        (if (ly:moment<? max-end end) end max-end)))))))

       ;; ── Context specification — extract staff/voice name
       ((eq? name 'ContextSpeccedMusic)
        (let* ((ctype (ly:music-property m 'context-type 'Voice))
               (cid   (ly:music-property m 'context-id ""))
               (is-new (ly:music-property m 'create-new-context #f))
               (is-staff (memq ctype '(Staff TabStaff DrumStaff RhythmicStaff)))
               (new-staff
                (if is-staff
                    (if (string-null? cid)
                        ;; Use staff ID pre-assigned by SimultaneousMusic for grand-staff layouts.
                        ;; In LilyPond 2.24+, \new Staff no longer sets create-new-context=#t,
                        ;; so we rely on SimultaneousMusic to pre-assign IDs via the staff param.
                        ;; For sequential contexts (\clef, \key, etc.), staff param is already
                        ;; the current staff ID, so using it directly is correct.
                        staff
                        cid)
                    staff))
               (new-voice
                (if (memq ctype '(Voice CueVoice))
                    (if (string-null? cid) voice
                        ;; Qualify named voice IDs with the enclosing staff name so that
                        ;; two separate staves each having a Voice "1" produce distinct IDs
                        ;; ("Upper.1" vs "Lower.1").  Cross-staff \change Staff voices keep
                        ;; the same vc throughout (staff changes, voice context does not),
                        ;; so they are still correctly merged to their home staff by Python.
                        (if (string-null? staff) cid
                            (string-append staff "." cid)))
                    voice))
               (elt  (ly:music-property m 'element #f))
               (elts (ly:music-property m 'elements '())))
          ;; Reset %cur-staff for explicit new-Voice or Staff contexts.
          ;; NOT for oiceTwo/\oneVoice (is-new=#f) which should preserve current staff.
          (when (or is-staff is-new)
            (set! %cur-staff new-staff))
          (let loop ((es (if elt (cons elt elts) elts)) (t onset))
            (if (null? es) t
                (loop (cdr es)
                      (dump-traverse (car es) t new-staff new-voice))))))

       ;; ── Sequential / generic wrapper — recurse through elements
       ;; Also handles ContextChange (\change Staff) by updating current-staff
       ((ly:music? m)
        (let ((elts (ly:music-property m 'elements '()))
              (elt  (ly:music-property m 'element #f)))
          (let loop ((es (if elt (cons elt elts) elts)) (t onset) (cur-staff staff))
            (if (null? es) t
                (let ((e (car es)))
                  (if (eq? (ly:music-property e 'name) 'ContextChange)
                      ;; staff change: update cur-staff and %cur-staff, don't advance time
                      (let ((new-id (ly:music-property e 'change-to-id "")))
                        (when (not (string-null? new-id))
                          (set! %cur-staff new-id))
                        (loop (cdr es) t
                              (if (string-null? new-id) cur-staff new-id)))
                      (loop (cdr es)
                            (dump-traverse e t cur-staff voice)
                            cur-staff)))))))

       (else onset))))

%% ── score handler hook ───────────────────────────────────────────────────────

#(define (%has-layout-outdef? score)
   ;; Returns #t if score has at least one layout (non-MIDI) output-def,
   ;; OR if the score has no explicit output-defs (uses book's default layout).
   ;; Returns #f only when all output-defs are MIDI (mm = ()).
   ;; Layout output-defs have 'mm = 1.0; MIDI output-defs have 'mm = ().
   (let ((ods (ly:score-output-defs score)))
     (or (null? ods)
         (any (lambda (od)
                (number? (ly:output-def-lookup od 'mm)))
              ods))))

#(define (%dump-one-score score)
   ;; Dump notes from a single score to the output file.
   ;; Skip MIDI-only scores (e.g. \score { \articulate ... \midi {} }).
   (when (and (ly:score? score) ly:dump-output-file
              (%has-layout-outdef? score))
     (set! %dump-score (+ %dump-score 1))
     (set! %dump-staff-counter 0)  ;; reset per score
     (set! %cur-staff "1")          ;; reset current staff per score
     (let ((port (open-file ly:dump-output-file
                            (if (= %dump-score 1) "w" "a"))))
       (set! %dump-port port)
       ;; Emit score-boundary marker so Python can split multi-score books
       (dump-write "{\"t\":\"SCORE\",\"score\":" %dump-score "}")
       (dump-traverse (ly:score-music score)
                      (ly:make-moment 0) "1" "1")
       (close-output-port port)
       (set! %dump-port #f))))

%% Hook toplevel-score-handler (bare \score blocks)
#(let ((orig toplevel-score-handler))
   (set! toplevel-score-handler
     (lambda (score)
       (%dump-one-score score)
       ;; Suppress PDF/SVG rendering
       )))

%% Hook book-score-handler (\score inside \book)
#(let ((orig book-score-handler))
   (set! book-score-handler
     (lambda (book score)
       (%dump-one-score score)
       ;; Don't add score to book (suppresses rendering)
       )))

%% Hook bookpart-score-handler (\score inside \bookpart inside \book)
#(let ((orig bookpart-score-handler))
   (set! bookpart-score-handler
     (lambda (bookpart score)
       (%dump-one-score score)
       )))

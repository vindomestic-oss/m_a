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
                           arts)))
          (when (and %dump-port (ly:pitch? pitch) (ly:duration? dur))
            (let ((len (ly:duration-length dur)))
              (dump-write
               "{\"t\":\"N\""
               ",\"on\":\"" (dump-onset onset) "\""
               ",\"semi\":"  (modulo (ly:pitch-semitones pitch) 12)
               ",\"oct\":"   (ly:pitch-octave pitch)
               ",\"step\":"  (ly:pitch-notename pitch)
               ",\"log\":"   (ly:duration-log dur)
               ",\"dots\":"  (ly:duration-dot-count dur)
               ",\"st\":\"" staff "\""
               ",\"vc\":\"" voice "\""
               ",\"tie\":"  (if tie "true" "false")
               "}")
              (ly:moment-add onset len)))
          ;; if no duration (shouldn't happen for normal notes) return onset
          (if (ly:duration? dur)
              (ly:moment-add onset (ly:duration-length dur))
              onset)))

       ;; ── Rest / skip / spacer — advance time only
       ((memq name '(RestEvent SkipEvent))
        (let ((dur (ly:music-property m 'duration)))
          (if (ly:duration? dur)
              (ly:moment-add onset (ly:duration-length dur))
              onset)))

       ;; ── ContextChange (\change Staff = "other") — update staff for subsequent notes
       ;; This is NOT handled here (it's stateful); handled in the sequential loop below.
       ((eq? name 'ContextChange)
        onset)  ;; no-op here; sequential loop handles it

       ;; ── Multi-measure rest — try to get duration, else skip
       ((eq? name 'MultiMeasureRestMusic)
        ;; MultiMeasureRestMusic has 'elements with a MultiMeasureRestEvent
        (let loop ((es (ly:music-property m 'elements '())) (t onset))
          (if (null? es) t
              (loop (cdr es) (dump-traverse (car es) t staff voice)))))

       ((eq? name 'MultiMeasureRestEvent)
        (let ((dur (ly:music-property m 'duration)))
          (if (ly:duration? dur)
              (ly:moment-add onset (ly:duration-length dur))
              onset)))

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
             ",\"st\":\"" staff "\""
             "}"))
          onset))

       ;; ── Key change — emit and don't advance
       ((eq? name 'KeyChangeEvent)
        (let ((tonic  (ly:music-property m 'tonic))
              (mode   (ly:music-property m 'mode 'major)))
          (when (and %dump-port (ly:pitch? tonic))
            (dump-write
             "{\"t\":\"K\""
             ",\"on\":\"" (dump-onset onset) "\""
             ",\"semi\":" (modulo (ly:pitch-semitones tonic) 12)
             ",\"step\":" (ly:pitch-notename tonic)
             ",\"mode\":\"" (symbol->string mode) "\""
             ",\"st\":\"" staff "\""
             "}"))
          onset))

       ;; ── Simultaneous music: voice splits or staff layout
       ((eq? name 'SimultaneousMusic)
        (let ((elts (ly:music-property m 'elements '())))
          (let loop ((es elts) (v 1) (max-end onset))
            (if (null? es) max-end
                (let* ((new-voice (string-append voice "." (number->string v)))
                       (end (dump-traverse (car es) onset staff new-voice)))
                  (loop (cdr es) (+ v 1)
                        (if (ly:moment<? max-end end) end max-end)))))))

       ;; ── Context specification — extract staff/voice name
       ((eq? name 'ContextSpeccedMusic)
        (let* ((ctype (ly:music-property m 'context-type 'Voice))
               (cid   (ly:music-property m 'context-id ""))
               (is-staff (memq ctype '(Staff TabStaff DrumStaff RhythmicStaff)))
               (new-staff
                (if is-staff
                    (if (string-null? cid)
                        ;; anonymous Staff: assign a unique numbered ID
                        (begin
                          (set! %dump-staff-counter (+ %dump-staff-counter 1))
                          (number->string %dump-staff-counter))
                        cid)
                    staff))
               (new-voice
                (if (memq ctype '(Voice CueVoice))
                    (if (string-null? cid) voice cid)
                    voice))
               (elt  (ly:music-property m 'element #f))
               (elts (ly:music-property m 'elements '())))
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
                      ;; staff change: update cur-staff, don't advance time
                      (let ((new-id (ly:music-property e 'change-to-id "")))
                        (loop (cdr es) t
                              (if (string-null? new-id) cur-staff new-id)))
                      (loop (cdr es)
                            (dump-traverse e t cur-staff voice)
                            cur-staff)))))))

       (else onset))))

%% ── score handler hook ───────────────────────────────────────────────────────

#(define (%dump-one-score score)
   ;; Dump notes from a single score to the output file.
   (when (and (ly:score? score) ly:dump-output-file)
     (set! %dump-score (+ %dump-score 1))
     (set! %dump-staff-counter 0)  ;; reset per score
     (let ((port (open-file ly:dump-output-file
                            (if (= %dump-score 1) "w" "a"))))
       (set! %dump-port port)
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

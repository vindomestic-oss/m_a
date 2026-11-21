%%  Copyright (c) 2018 Pietro Brenna <pietrobrenna@zoho.com>
%%                All Rights Reserved
%%
%% This work is licensed under the Creative Commons
%% Attribution-NonCommercial-ShareAlike 4.0 International License.
%% To view a copy of this license, visit 
%% http://creativecommons.org/licenses/by-nc-sa/4.0/ or send a letter
%% to Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.

% Typeset based on IMSLP#01326

\version "2.18.0"
AutoEndMovementBarline = \bar "|."


beamed-stem-length = #(define-music-function (parser location num notes) (number? ly:music?)
                        (let ((asd (list num num num)))
                          #{\override Stem.details.beamed-lengths = #num
                            \override Stem.details.beamed-extreme-minimum-free-lengths=#asd
                            #notes
                            \revert Stem.details.beamed-lengths
                            \revert Stem.details.beamed-extreme-minimum-free-lengths
                          #}))
stem-length = #(define-music-function (parser location num notes) (number? ly:music?)         
                 #{\override Stem.length = #num
                   #notes
                   \revert Stem.length #})
offset-tie = #(define-music-function (parser location offset-x offset-y) (number? number?)
                (let* ((list1 (cons offset-x  offset-y))
                       (list2 (list list1 list1 list1 list1)))
                  #{
                    \shape #list2 Tie
                  #}))

offset-rest = #(define-music-function (parser location num ) (number?)         
                 #{\once \override MultiMeasureRest.staff-position = #num #})

offset-rests = #(define-music-function (parser location num notes) (number? ly:music?)
                  #{\override MultiMeasureRest.staff-position = #num 
                    #notes
                    \revert MultiMeasureRest.staff-position #})

% The music follows
%Prelude
MvmntIVoiceI = {
  \tempo Vivace  r16 g' b' d'' g''8 fis''16 e'' d'' c'' b' a'
  b' d'' g' b' d' b' a' g' fis' e' d' c'
  d' g' b d' \change Staff="Organ_LH"  g16 d' c' b a g fis e
  fis a d fis a c' fis a d c' b a
  %5
  g b d g b d' g b d d' c' b
  a c' fis a c' fis' a c' d e' d' c'
  b d' g b d' g' b d' g b d g
  b d' g b d g b, d g b d g
  b, d g, b, d g b, d g, b, d, g,
  %10
  b, g, b, d b, d g d g b g b
  \change Staff="Organ_RH"  d'16 b d' g' d' g' b' g' b' d'' b' d''
  \voiceOne \offset-tie 0 1 g''2.~
  g''16 b'' a'' g'' fis'' e'' d'' c'' \voiceTwo  b'16 a' c'' b'
  c''2.~
  %15
  c''16 e'' d'' c'' b' a' g' fis' e' d' f' e'
  \change Staff="Organ_LH"  f'2.
  e'~
  e'8 e' d' c' b a
  b a b b a g
  %20
  fis a d'2~
  d'8 \voiceOne  \change Staff="Organ_RH" \beamed-stem-length #2.5 { b''8[ b''8 b'' b'' b''] }
  \beamed-stem-length #3 {b''8 a'' a'' a'' a'' a''
                          a'' g'' g'' g'' g'' g'' }
  g''16 b'' e'' g'' cis'' fis'' e'' d'' cis'' b' a' g'
  %25
  a''8 r r4 r
  b''8 r r4 r
  r8 b'' a'' g'' fis'' e''
  d''4 r16 a' d''8~  d''16 d''8 cis''16
  d''8 cis''16 b' a' g' fis' e' fis' a' d' fis'
  %30
  \change Staff="Organ_LH"  a16 d' cis' b a g fis e fis a d fis
  a d' fis a \change Staff="Organ_RH"  d'16 fis' a d' fis' a' d' fis'
  \voiceTwo  a'2.~
  a'16 g' fis' e' dis' e' fis' g' a' g' a' fis'
  g'2.~
  %35
  g'16 g' fis' e' \change Staff="Organ_LH"  \voiceOne  d'16 c' b a g fis e d
  \change Staff="Organ_RH"  \offset-tie #0 #2 c''2.~
  c''8 r r4 r
  b' r8 b' e''4~
  e''16 g'' fis'' g'' e'' g'' d'' g'' cis'' g'' b' g''
  %40
  ais' e'' d'' e'' cis'' e'' b' e'' ais' e'' g'!16 e''
  fis' e' g' fis' e' d' cis' b r4
  r8 fis'' e''16 d'' cis'' b' d'' cis'' b' ais'
  b' ais' b' g'' b' fis'' fis' e'' gis' d'' ais' cis''
  b' ais' b' d'' b' e'' ais' fis'' b' gis'' cis'' ais''
  %45
  b''8 fis'' e''16 d'' cis'' b' fis'8 ais'-\mordent
  b'8 d''16 cis'' d'' f'' b' d'' gis' b' d' f'
  d''2.~
  d''16 c'' b' c'' d'' e'' f'' e'' d'' c'' d'' b'
  c''2.~
  %50
  c''16 b' c'' a'' fis'' a'' d'' fis'' a' d'' fis' a'
  c''2.~
  c''16 b' a' b' c'' d'' e'' d'' c'' b' c'' a'
  b'8 g'16 fis' g'8 d' b' g'
  a' a'16 g' a'8 d' c'' a'
  %55
  b' b'16 a' b'8 g' d'' b'
  cis'' cis''16 b' cis''8 g' e'' cis''!8
  d''16 a' c''!16 b' r b'' a'' g'' fis'' e'' d'' c''
  b'4~  b'16 b' a' g' fis' a' g' fis'
  g' fis' g' a' g' b' d' b' g' b' d' b'
  %60
  a' g' a' b' a' c'' d' c'' a' c'' d' c''
  b'8 d'' d'' d'' d'' d''
  d'' c'' c'' c'' c'' c''
  c''4 r8 fis''8 g'' a''
  d''4 r8 g'' a'' b''
  %65
  fis''16 e'' fis'' g'' fis'' a'' e'' a'' d'' a'' c'' a''
  b' g'' fis'' g'' e'' g'' d'' g'' cis'' g'' b' g''
  a' fis'' e'' fis'' d'' fis'' c'' fis'' b' fis'' a' fis''
  g' e'' d'' e'' cis'' e'' bes' e'' a' e'' g' e''
  fis' ees'' c'' a' fis' r r8 r16 e' d' c'
  %70
  b g' fis' e' d' b' a' g' fis' e'' d'' c''
  b' a'' g'' f'' e''2~
  e''4 r8 d'' e'' fis''
  g''4 r8 e'' a'' g''
  fis''16 d'' fis'' a'' c''' b'' a'' g'' fis'' e'' d'' c''
  %75
  g''8 r r4 r
  g''8 r r4 r
  r16 d' e' fis' g' a' g' a' b' d'' c'' e''
  d'' fis'' e'' g'' fis'' d'' g'' b' a' g'' c'' fis''
  g''4 r8 fis' g' a'
  %80
  b'16 a' b' c'' b' e'' a' fis'' b' g'' c'' a''
  b''8 d'' c''16 b' a' g' d'8 fis'-\mordent
  g'4 r r
  \AutoEndMovementBarline
}


MvmntIVoiceII = {
  s1*3/4          s1*3/4          s1*3/4          s1*3/4 %5
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %10
  s1*3/4          s1*3/4
  \voiceOne r8 d''8 d'' d'' d'' b'
  \change Staff="Organ_LH"  a'4 a' r
  \change Staff="Organ_RH"  r8 fis''16 e'' fis'' g'' fis'' g'' a'' b'' a'' b''
  %15
  d''4 r r
  r8 \beamed-stem-length #3 {d'' d'' d'' d'' d''}
  \beamed-stem-length #2.3 {e'' e'' e'' e'' e'' e''}
  fis''16 e'' fis'' g'' fis'' a'' d'' a'' e'' a'' fis'' a''
  g'' fis'' g'' a'' g'' b'' e'' b'' fis'' b'' g'' b''
  %20
  a'' g'' a'' b'' a'' c''' g'' c''' fis'' c''' e'' c'''
  d''8 \voiceThree g''8[ g''8 g'' g'' g'']
  g''8 e'' fis'' fis'' fis'' fis''
  fis'' d'' e'' e'' e'' e''
  e'' s s4 s %visible rests in the original
  %25
  fis''8 r r4 r
  f''8 r r4 r
  \voiceTwo r8 g''8 fis'' e'' d'' cis''
  d''16 b' a' g' fis'8. fis'16 e'8 e'
  d' r r4 r
  %30
  s2.
  s2.
  \voiceOne  r8 fis''16 e'' fis'' g'' fis'' e'' dis'' cis'' b' c''
  b'8 r r4 r
  r8 g''16 fis'' g'' a'' g'' fis'' e'' d'' c'' b'
  %35
  a'8 r r4 r
  \voiceThree r8 a'16 b' a'2~
  a'8 \voiceTwo  r8 d'16 e' fis' g' a' b' c'' fis'
  \voiceThree  g'4 s4 s4
  s1*3/4 %40
  \voiceTwo  r16 g' fis' g' e' g' d' g' cis' g' b g'
  \change Staff="Organ_LH"  ais4 r s4
  \change Staff="Organ_RH"  r8 fis' b' g' fis' fis'
  fis' \change Staff="Organ_LH"  \voiceOne  e'8 fis' cis' d' e'
  fis' e' fis' r r \change Staff="Organ_RH"  \voiceTwo  cis''8
  %45
  d'' fis' g' g' fis' e'
  fis' r r4 r
  r8 b'16 a' b' c'' b' a' gis' a' b' gis'
  e'8 r r4 r
  a' r8 e' a' g'
  %50
  fis'4 r r
  r8 a'16 g' a' b' a' g' fis' g' a' fis'
  d'4 r r
  r r r8 \voiceThree  d'8
  e'4 r r8 fis'
  %55
  g'4 r r8 g'
  g'4 r r8 g'
  fis' s8 s2
  \voiceTwo  r16 a' g' fis' e'4 d'
  d' \change Staff="Organ_LH" \voiceOne r8 b8 d' b
  %60
  d'4 r8 d' d' d'
  d' \change Staff="Organ_RH"  \voiceTwo  r8 r b' b' b'
  b' a'16 g' a'8 a' a' a'
  a'4 r8 e'' d'' c''
  b'4 r8 fis'' e'' d''
  %65
  c''4 r r
  s1*3/4          s1*3/4          s1*3/4          s1*3/4 %70
  s1*3/4          s4 r8 d'' c'' b'
  a'4 r8 fis' g' a'
  b'4 a'2~
  a'4 r r
  %75
  d''8 r r4 r
  \voiceThree  e''8 s s4 s
  s1*3/4          s2 s8 \voiceTwo  a'8
  <g' b' d''>4 s2
  %80
  s1*3/4          r8 g' g' r r d'
  d'4 r r
}


MvmntIVoiceIII = {
  s1*3/4          s1*3/4          s1*3/4          s1*3/4 %5
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %10
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %15
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %20
  s1*3/4          s8 \voiceTwo d''8 d'' d'' d'' d''
  e'' cis'' cis'' cis'' cis'' cis''
  d'' b' b' b' b' b'
  cis'' r r4 r
  %25
  d''8 r r4 r
  d''8 r r4 r
  s1*3/4          s4 s4 s8 \voiceThree  g'8
  fis' s8 s4 s4
  %30
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %35
  s1*3/4          \voiceTwo  r4 r16 g' fis' e' fis'4~
  fis'8 s8 s4 s4
  d'8 d' g'4~  g'8 g'
  fis'4 r r
  %40
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %45
  s1*3/4          \change Staff="Organ_LH"  \voiceOne  d'8 s8 s2
  s1*3/4          s1*3/4          s1*3/4 %50
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          \change Staff="Organ_RH"  \voiceTwo  s4 s4 s8 d'8
  %55
  d'4 r r8 d'
  e' e'16 d' e'4 r8 e'
  d' \voiceTwo  r8 a'16 \change Staff="Organ_LH"  \voiceOne  g'16 fis' e' d' c' b a
  g4 s4 s4
  s1*3/4 %60
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %65
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %70
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %75
  s1*3/4          \change Staff="Organ_RH"  \voiceTwo  bes'8 r8 r4 r
  \change Staff="Organ_LH"  \voiceOne  r4 r8 d' d' d'
  d' c'16 b a8 e' a d'
  d'4 s2
  %80
  s1*3/4          g'8 d' e' e' d' c'
  b4 r r
}


MvmntIVoiceIV = {
  s1*3/4          s1*3/4          s1*3/4          s1*3/4 %5
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %10
  s1*3/4          s1*3/4          \voiceTwo  r8 g' g' g' g' g'
  \voiceOne  \change Staff="Organ_LH" e'4 d' r
  \voiceOne  r8 a' a' a' fis' fis'
  %15
  g'4 g' r
  \change Staff="Organ_RH"  r8 \voiceThree  b'8 b' b' b' b'
  c'' c'' c'' c'' c'' c''
  c'' \change Staff="Organ_LH"  \voiceOne  c''8[ b'8 a' g' fis']
  \change Staff="Organ_RH"  \voiceTwo  d''8 r r \change Staff="Organ_LH"  \voiceOne  g'8 fis' e'
  %20
  d'4 \change Staff="Organ_RH"  \voiceTwo  r8 \change Staff="Organ_LH"  \voiceOne  fis'8 g' a'
  b' g'[ g'8 g' g' g']
  e'8 e' a' a' a' a'
  fis' g' g' g' g' g'
  a' r r4 r
  %25
  fis'16 a' d' fis' a g' fis' e' d' cis' b a
  \clef bass gis b d f b, d f a gis b e d
  cis a, b, cis d e d e fis a g b
  a8 b cis' d' a a
  a r r4 r
  %30
  s1*3/4          s1*3/4          r8 \voiceOne  fis'8 fis' fis' fis' fis'
  e' r r4 r
  r8 e' e' e' e' e'
  %35
  e' r s4 s4
  r8 d' d' d' d'4~
  d'8 s8 s4 r4
  g r8 fis' e' d'
  cis'4 r r
  %40
  s1*3/4          s1*3/4          \voiceOne  r8 d' e' e' d' e'
  \voiceTwo  b8 s8 s2
  s1*3/4 %45
  \voiceThree  r8 d' e' e' d' cis'
  b r r4 r
  r8 e' e' e' e' e'
  e' r r4 r
  e' r r
  %50
  d' r r
  r r8 d' d' d'
  d'4 r r
  s1*3/4          s1*3/4 %55
  s1*3/4          s1*3/4          s1*3/4          \voiceTwo  s4 r16 d' c' b a c' b a
  b4 r8 g g g
  %60
  fis4 r8 fis a fis
  g r r \clef treble \voiceOne  d'8 g' f'
  e'4 r8 e' d' e'
  fis'16 e' fis' g' fis' a' d' a' e' a' fis' a'
  g' fis' g' a' g' b' e' b' fis' b' g' b'
  %65
  a' g' a' b' a' c'' g' c'' fis' c'' e' c''
  d' b' a' b' g' b' fis' b' e' b' d' b'
  c'!16 a' g' a' fis' a' e' a' d' a' c' a'
  bes g' fis' g' e' g' d' g' cis' g' \voiceOne  bes!8
  a s8 s2
  %70
  s1*3/4          s4 r8 e' fis' g'
  c'4 d'2~
  d'16 c' b d' c'2~
  c'4 r r
  %75
  \clef treble b'16 d'' g' b' d' c'' b' a' g' fis' e' d'
  \clef bass cis' e' g bes e g bes d' cis' e' a g
  \voiceTwo  fis8 c' b a g fis
  g4 r8 g d' a
  g16 fis g a g b d b e b fis b
  %80
  g fis g a g c' fis d' g e' a fis'
  r8 g g c' b a
  g4 r r
}


MvmntIVoiceV = {
  s1*3/4          s1*3/4          s1*3/4          s1*3/4 %5
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %10
  s1*3/4          s1*3/4          \clef treble \voiceTwo  r8 b16 a b c' b c' d' e' d' e'
  c'4 c' r
  r8 d' d' d' d' d'
  %15
  d'4 d' r
  \change Staff="Organ_RH"  r8 g' g' g' g' g'
  g' g' <g' a'> <g' a'> <g' a'> <g' a'>
  <fis' a'> r r \change Staff="Organ_LH"  \voiceThree  fis'8 d' c'
  d' c' d' d' c' b
  %20
  c'4 r e'8 fis'
  g' \voiceTwo  d'8[ d'8 d' d' d']
  g'8 a' cis' cis' fis' e'
  d' d' d' b e' d'
  cis' r r4 r
  %25
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %30
  s1*3/4          s1*3/4          r8 \voiceTwo  b8 b b b b
  b r r4 r
  r8 b b b b c'
  %35
  c' r r4 r
  r8 a a a a16 c' b a
  g a b c' s4 r4
  s1*3/4          s1*3/4 %40
  s1*3/4          \voiceTwo  s4 s4 ais16 g fis e
  d8 b b b b cis'
  \voiceFour  d'8 cis' d' ais b cis'
  d' cis' d' cis' d' e'
  %45
  fis' b b b b fis
  fis r r4 r
  b2.~
  b16 a gis a b c' d' c' b a b gis
  a4 r8 a a a
  %50
  a4 r r
  a2.~
  a16 g fis g a b c' b a g a fis
  g d b, d g, d e fis g a b g
  c' d' c' b a g fis e d c b, a,
  %55
  g, d e f g a b c' b a g a
  bes a g fis g a bes a g bes a g
  a8 d r4 r
  s1*3/4          s1*3/4 %60
  s1*3/4          s1*3/4          s1*3/4          s1*3/4          s1*3/4 %65
  s1*3/4          s1*3/4          s1*3/4          s4 s4 s8 \voiceTwo  r16 cis'!16
  \stem-length #10 {d'8} r r16 \clef bass c' 16 a fis d8 e16 fis
  %70
  g fis g a b a b c' d' c' b a
  g f' e' d' c'2~
  c'16 g' fis' e' b2~
  b8 e a2~
  a4 r r
  %75
  s1*3/4          s1*3/4          r4 r8 \voiceTwo  \voiceFour  c'8 b a
  \voiceThree  g4 s4 s4
  s1*3/4 %80
  s1*3/4          s1*3/4          s1*3/4
}


MvmntIVoiceVI = {
  R1*3/4
  R1*3/4
  R1*3/4
  R1*3/4
  %5
  R1*3/4
  R1*3/4
  R1*3/4
  R1*3/4
  R1*3/4
  %10
  R1*3/4
  R1*3/4
  r8 g16 fis g8 d b g
  a4 d r
  r8 a16 g a8 d c' a
  %15
  b4 d r
  r16 b a b g a f g e f d e
  c c' b c' a b g a fis g e fis
  d4 r8 d d d
  d4 r8 d d d
  %20
  d4 r8 d d d
  g,16 b a b g b fis b e b d b
  cis a g a fis a e a d a cis a
  b, g fis g e g d g cis g b, g
  a,8 r r4 r
  %25
  a,8 r r4 r
  a,8 r r4 r
  r8 a, b, cis d e
  fis g a gis a a,
  d4 r r
  %30
  R1*3/4
  R1*3/4
  r8 dis16 cis dis8 b, fis dis
  e4 e, r
  r8 e16 dis e8 b, g e
  %35
  fis4 fis, r
  r8 fis16 e fis8 d a fis
  g4 g, r
  r16 g fis g e g d g cis g b, g
  ais,4 r r
  %40
  cis r r
  e r r
  r8 d g e fis fis,
  b,4 r r
  b, r r
  %45
  r8 d g e fis fis,
  b,4 r r
  r8 gis16 fis gis8 e b gis
  a4 a, r
  r16 c' b c' a c' g c' fis c' e c'
  %50
  d4 d' r
  r8 fis16 e fis8 d a fis
  g4 g, r
  r g2~
  g4 fis2
  %55
  f2.
  e
  fis4 r r
  r8 b, c a, d d,
  g,4 r8 g, b, g,
  %60
  d4 r8 d fis d
  g16 b a b g a f g e f d e
  c c' b c' a b g a fis!16 g e fis
  d4 r8 d d d
  d4 r8 d d d
  %65
  d4 r8 d d d
  d4 r8 d d d
  d4 r8 d d d
  d4 r8 d d d
  d4 r8 d d d
  %70
  d d d d d d
  e g c16 c' b c' a c' g c'
  fis4 r16 b a b g b fis b
  e4 r16 a g a fis a e a
  d4 r r
  %75
  d r r
  d r r
  r8 d, e, fis, g, a,
  b, c d c d d,
  g,4 r r
  %80
  g, r r
  r8 b, e c d d,
  g,4 r r
}



%Fuga
MvmntIIVoiceI = {
  \voiceOne  R1*4/4
  R1*4/4
  R1*4/4
  R1*4/4
  %5
  R1*4/4
  \offset-rests #5 { R1*4/4
  R1*4/4}
  R1*4/4
  \offset-rest #5 R1*4/4
  %10
  \offset-rest #8 R1*4/4
  \offset-rest #5 R1*4/4
  R1*4/4
  R1*4/4
  r8 a' a' a' d'' d'' d'' d''
  %15
  d'' cis''16 b' cis''8 a' fis'' fis'' fis'' fis''
  fis'' e''16 d'' e''8 e'' e'' a' d''4~
  d''8 e''16 d'' cis'' d'' b' cis'' d''8 a'16 g' a' c'' b' d''
  c''2 r8 b'16 a' b' d'' c'' e''
  d''2~  d''8 c''16 b' c''8 a'
  %20
  f'' f'' f'' f'' f'' e''16 d'' e''8 e''
  e'' a' d'' d'' d'' c''16 b' c''8 a'
  b' cis'' d'' e'' cis'' a' a'' a''
  a'' g''16 fis'' g'' fis'' e'' g'' fis'' e'' d'' fis'' e'' g'' fis'' a''
  g'' e'' fis'' g'' a'' g'' fis'' e'' d''8 g'' g'' g''
  %25
  g'' f''16 e'' f'' e'' d'' f'' e'' f'' e'' d'' c'' b' a' g'
  fis' e' fis' a' d''2 cis''4
  d''8 a' a''4~  a''16 d'' e'' fis'' g'' a'' fis'' g''
  c''4~  c''16 e'' d'' c'' b' a' b' c'' b' c'' d'' e''
  fis'' g'' fis'' g'' a' d'' c'' d'' b'4~  b'16 a' b' cis''
  %30
  dis'' e'' dis'' e'' fis' b' a' b' g'8 b'' b'' b''
  b'' a''16 g'' a''8 a'' a'' d'' g'' g''
  g'' fis''16 e'' fis''8 fis'' fis''16 e'' dis'' fis'' e'' d'' c'' b'
  c''2~  c''16 b' a' c'' b' a' g' fis'
  g' b' e''8~  e''16 g'' c'''8~  c'''16 g'' fis'' e'' dis''8. e''16
  %35
  e''8 r r4 r8 dis'' e'' fis''
  g'' fis''16 e'' fis''8 d'' b'' b'' b'' b''
  b'' a''16 g'' a''8 a'' a'' g''16 fis'' g''8 e''
  c'''16 b'' a'' g'' fis'' b'' a'' b'' g''2~
  g'' fis''~
  %40
  fis'' e''~
  e'' d''4 r16 d'' b' gis'
  c''4 r16 c'' a' fis' b'4 e''8 c''
  a'4~  a'16 c'' b' a' g' a' b' g' e' b' g' e'
  d' b' gis' d' b' f' e' d' c' d' e' c' a8 a'
  %45
  cis'' e'' cis'' a' d''16 e'' fis'' d'' a'' fis'' d'' a'
  ees'' c'' a' fis' fis'' c'' b' a' g' d'' b' g' e'' b' a' g'
  fis' cis'' a' fis' d'' a' g' fis' e' b' g' e' cis'' g' fis' e'
  d' a' fis' d' d'' a' g' fis' e' b' g' e' e'' b' a' g'
  fis' cis'' a' fis' fis'' c'' b' a' g' d'' b' g' g'' fis'' e'' d''
  %50
  cis'' e'' cis'' a' a'' e'' cis'' a' d'' fis'' d'' a' a'' fis'' d'' a'
  e'' g'' e'' cis'' a'' e'' cis'' a' fis'' a'' fis'' d'' g'' e'' cis'' a'
  fis'' d'' b' a' g' e'' cis'' g' fis' a' d'' fis' e' d'' g' cis''
  d''4 r r2
  \offset-rests #5 {R1*4/4
  %55
  R1*4/4
  R1*4/4
  R1*4/4}
  R1*4/4
  r2 r8 e'' e'' e''
  %60
  a'' a'' a'' a'' a'' gis''16 fis'' gis''8 e''
  c''' c''' c''' c''' c''' b''16 a'' b''8 b''
  b'' e'' a''4~  a''8 b''16 a'' gis'' a'' fis'' gis''
  a''4 r r2
  R1*4/4
  %65
  r8 d'' g'' g'' g'' f''16 e'' f''8 f''
  f'' e''16 d'' e'' g'' f'' e'' d'' c'' d'' e'' d'' f'' e'' d''
  cis''8 a' a''4~  a''8 g''16 fis'' g''8 d''
  ees''4~  ees''8 d''16 c'' d''4~  d''16 f'' ees'' d''
  c'' b'!16 c'' d'' c'' ees'' d'' c'' b' a' g' d''~  d''4~
  %70
  d''16 c''32 bes' aes'16 c''~  c''4~  c'' r8 c''
  bes'4 r8 bes' bes'4-\fermata r16 a' bes' g'
  fis'8 r r4 r2
  R1*4/4
  R1*4/4
  %75
  r2 r8 d'' d'' d''
  g'' g'' g'' g'' g'' fis''16 e'' fis''8 d''
  b'' b'' b'' b'' b'' a''16 g'' a''8 a''
  a'' d'' g''4~  g''8 a''16 g'' fis'' g'' e'' fis''
  g''1~
  %80
  g''~
  g''~
  g''2~  g''8 a''16 g'' fis'' g'' e'' fis''
  g''1-\fermata
  \AutoEndMovementBarline
}


MvmntIIVoiceII = {
  \voiceTwo  r8 d' d' d' g' g' g' g'
  g' fis'16 e' fis'8 d' b' b' b' b'
  b' a'16 g' a'8 a' a' d' g'4~
  g'8 a'16 g' fis' g' e' fis' g' fis' g' a' g' b' a' g'
  %5
  fis' e' fis' g' fis' a' g' fis' e'4 e''~
  e''16 a' b' cis'' d'' e'' cis'' d'' g'4~  g'16 b' a' g'
  fis'4~  fis'16 g' a' b' cis'' d'' cis'' d'' e'8 a'
  fis'16 e' fis' g' fis' g' a'8~  a' g' r g'
  c''16 b' a' b' c'' d'' b' c'' d''4 r8 d''
  %10
  e''16 d'' e'' f'' e'' g'' fis'' a'' d'' c'' d'' e'' d'' g'' fis'' g''
  a' b' a' b' c'' d'' c'' d'' b' c'' b' a' g' b' e'' d''
  cis'' b' a' g' fis'4~  fis'16 fis' g' a' b' c'' b' a'
  g'2~  g'16 e' fis' g' a' b' a' g'
  fis'4 r8 e' fis' e' e' e'
  %15
  e'4 r r8 a' d'' c''
  b'2 r16 g' fis' e' d'8 fis'
  b' g' e'4 d' r
  r8 e'16 d' e' g' fis' a' g'2
  r8 fis'16 e' fis' a' gis' b' a'8 e'4 c'8
  %20
  c'4 r8 b~  b c''16 b' a' g' fis' e'
  fis'4 gis' e' r16 g' f' e'
  \change Staff="Organ_LH"  \voiceOne  d'16 e' d' cis' b e' d' e' a8 r r4
  \change Staff="Organ_RH"  \voiceTwo  R1*4/4
  R1*4/4
  %25
  R1*4/4
  r8 d' d' d' g' g' g' g'
  g' fis'16 e' fis'8 d' b' b' b' b'
  b' a'16 g' a'8 a' a' d' g'4~
  g' fis'~  fis'16 b cis' dis' e'4~
  %30
  e' dis' e'16 b e' g' b' e' g' b'
  c'' a c' e' a' d' fis' a' b' a' g' fis' e' d' c' b
  a b' a' g' fis' e' dis' cis' b4 b'~
  b'16 a' gis' b' a' g' fis' e' dis'2
  e'8 b16 e' g'8 e'16 g' c'' b' a' g' fis' c'' b' a'
  %35
  g'8 fis'[ g'8 a'] b'2~
  b'4 r8 d''!8 d''4 r8 g'
  d''4 r8 b' b'4 \change Staff="Organ_LH"  \voiceOne  r8 b'
  a'4 r e'16 fis' g' a' \change Staff="Organ_RH"  \voiceTwo  b'16 cis'' d'' b'
  cis''8 d'' e'' cis'' \change Staff="Organ_LH"  \voiceOne  d'16 e' fis' g' \change Staff="Organ_RH"  \voiceTwo  a'16 b' c'' a'
  %40
  b'8 c'' d'' b' \change Staff="Organ_LH"  \voiceOne  cis'16 d' e' fis' \change Staff="Organ_RH"  \voiceTwo  gis'16 ais' b' gis'
  ais'8 b' cis'' ais' b'16 fis' b' d'' gis'4
  r16 e' a' c'' fis'4 g'8 fis' e'4
  fis'8 e' dis'4 e' r
  r2 r4 r16 \change Staff="Organ_LH"  \voiceOne  e'16 c' a
  %45
  g e' cis' g e' bes a g fis g a fis d8 r
  r2 r8 g r16 g fis e
  a8 r r16 fis e d g8 r r16 e d cis
  r8 d16 e fis8 d r e16 fis g8 e
  r fis16 g a8 fis r g16 a b8 g
  %50
  r g16 fis e8 g r fis16 e d8 fis
  r e16 d cis8 e r d32 cis d16 r8 e32 d e16
  r8 fis32 e fis16 r8 g32 fis g16 a8 r r \change Staff="Organ_RH"  \voiceTwo  g'8~
  g'16 g' fis' e' fis' a' g' fis' e'8 r e''4~
  e''16 a' b' cis'' d'' e'' cis'' d'' g'4~  g'16 b' a' g'
  %55
  fis'4~  fis'16 g' a' b' cis'' d'' cis'' d'' e'8 a'
  fis'16 e' fis' a' d''8 d'' d'' c''16 b' c'' b' a' c''
  b' a' g' b' a' c'' b' d'' c'' a' b' c'' d'' c'' b' a'
  g'8 c'' c'' c'' c'' bes'16 a' bes' a' g' bes'
  a' gis' a' b'!16 a' c'' b' a' gis' b' e' gis' a' c'' gis' b'
  %60
  c'' e'' a'8~  a'16 e'' d'' f'' b'4 r
  r r16 c'' e'' c'' f''4 r16 d'' b' d''
  gis'4 r16 e'' c'' e'' a'8 d''~  d''16 c'' d'' b'
  c''4 r r2
  r8 a' d'' d'' d'' c''16 b' c''8 c''
  %65
  c'' b'16 a' b'8 e'' c'' a' d'' b'
  g'1
  R1*4/4
  r16 g' a' bes' c'' a' bes' g' fis'4 g'
  a'2 g'8 g' f'16 aes' g' f'
  %70
  \voiceOne  \change Staff="Organ_LH"  ees'2~  ees'16 d' c' ees' \change Staff="Organ_RH"  \voiceThree  r8 fis'
  g'4 r8 g' g'4 s4
  \voiceTwo  d'8 a'16 g' fis' e' d' c' r8 d' d' d'
  a' a' a' a' a' g'16 fis' g'8 e'
  c'' c'' c'' c'' c'' b'16 a' b'8 b'
  %75
  b' e' a'4~  a'8 g'16 fis' g'8 r
  r g' g' g' d'' d'' d'' d''
  d'' \change Staff="Organ_LH"  \voiceOne  b'16 a' b'8 g' \change Staff="Organ_RH"  \voiceTwo  e''8 e'' e'' e''
  e'' d''16 c'' d''8 d'' d'' g' c''4~
  c''8 d''16 c'' b' c'' a' b' c'' b' c'' d'' c'' d'' b' c''
  %80
  d'' c'' d'' e'' d'' e'' c'' d'' e'' d'' c'' b' c''4~
  c''8 b'16 a' b'8 c''16 d'' e'' d'' e'' f'' e'' g'' f'' e''
  d'' c'' b' c'' d'' f'' e'' d'' c''2~
  c''8 d''16 c'' b' c'' a' c'' b'2-\fermata
}


MvmntIIVoiceIII = {
  \voiceOne  R1*4/4
  R1*4/4
  R1*4/4
  r2 r8 g g g
  %5
  d' d' d' d' d' cis'16 b cis'8 a
  fis' fis' fis' fis' fis' e'16 d' e'8 e'
  e' a d'4~  d'8 e'16 d' cis' d' b cis'
  d' cis' d' e' d' e' d' c' b a b c' b d' c' b
  a4 \clef treble a'~  a'16 d' e' fis' g' a' fis' g'
  %10
  c'4~  c'16 e' d' c' b4~  b16 c' d' e'
  fis' g' fis' g' a8 d'~  d' b e'4~
  e'~  e'16 e' d' cis' d'2~
  d'16 b cis' d' e' fis' e' d' cis'4~  cis'16 a b cis'
  d'4 r8 \clef bass a~  a gis16 fis gis4
  %15
  a r r r8 d'
  g'16 a' g' fis' e' d' cis' b a4~  a16 g a fis
  g fis g a g b a g fis8 e fis gis
  a2 r8 fis g a
  b2 r8 b~  b a16 gis
  %20
  a8 a d' d' d' g c'4
  a b~  b8 a16 gis a8 c'
  \voiceTwo  b4 e~  e8 d r16 a b c'
  d' e' cis' d' e' d' cis' b a8 d' d' d'
  d' c'16 b c' b a c' b a g b a c' b d'
  %25
  c' a b c' d' c' b a g8 g a4~
  a8 a b16 c' b a g a g fis e g fis e
  d4 r r2
  R1*4/4
  R1*4/4
  %30
  R1*4/4
  R1*4/4
  R1*4/4
  R1*4/4
  R1*4/4
  %35
  r8 \clef treble b b b e' e' e' e'
  e' d'16 cis' d'8 b g' g' g' g'
  g' fis'16 e' fis'8 fis' fis' e'16 dis' e'4~
  e'8 fis'16 e' dis' e' cis' dis' e'4 r8 e'
  a'16 g' fis' e' d' cis' b a d'4 r8 d'
  %40
  g'16 fis' e' d' c' b a g cis'4 r8 \clef bass cis'
  fis'16 e' d' cis' b ais gis fis b8 d' e' e
  a c' d' d r16 g b d' c g e c
  r fis a c' b, fis dis b, e8 e, r e
  gis b gis e a a, r4
  %45
  r2 r4 r16 a fis d
  c a fis c a ees d c b,4 cis
  r8 fis b, r r e a, r
  fis,4 r g, r
  a, r b, r
  %50
  a, r a, r
  a, r a,8 r a, r
  a, r a, r r16 g fis g a4
  a2~  a16 d' e' fis' e' d' cis' b
  a4 r8 a b16 a b d' cis' d' cis' b
  %55
  a g fis e d e fis g a g a b a g fis e
  d8 r r16 \clef treble a d' fis' g' e' fis' g' a' g' fis' e'
  d'8 g' g' g' g' f'16 e' f' e' d' f'
  e' d' c' e' d' f' e' g' f' d' e' f' g' f' e' d'
  c' b c' d' c' e' d' c' b d' gis b c' e' d' b
  %60
  e' d' c' d' e' c' b a e'8 b e'4~
  e'16 e' gis' e' a'4~  a'16 a' f' a' d'4~
  d'16 f' b d' c'4~  c'8 f' e'4~
  e'8 e' a' a' a' g'16 fis' g'8 g'
  g' fis'16 e' fis'8 b' g' e' a' fis'
  %65
  d' g'16 fis' g'8 g' \clef bass e' c' b g~
  g g c'4~  c'8 b16 a b8 bes
  a16 g a bes a g fis e d fis g a bes g a bes
  c'2~  c'16 ees' d' c' b!16 d' c' b
  a4 d' d' r8 g
  %70
  g4 r8 c' a4 a16 c' bes a
  g f ees g d f ees d cis4-\fermata r4
  \voiceTwo  d8 r r4 b!16 a b c' b c' a b
  c' b c' d' c' d' b c' \clef treble d' c' d' e' d' e' c' d'
  e' d' e' fis' e' fis' d' e' fis' a' g' fis' e' d' c' b
  %75
  c' b c' d' c' e' d' c' b a b c' b c' a b
  cis' b cis' d' cis' d' b cis' d' cis' d' e' d' e' fis' d'
  g'2~  g'16 g' a' b' c''8 c''
  c'' b'16 a' g'8 b'~  b' c''16 b' a'4
  \voiceOne  g'4 r8 d' e'4 r8 e'
  %80
  f'4 r8 f' g'4~  g'16 a' g' fis'
  g'2~  g'8 b' c''4
  g'2 a'
  g'1-\fermata
}


MvmntIIVoiceIV = {
  s1*4/4          s1*4/4          s1*4/4          s1*4/4 %5
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %10
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %15
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %20
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %25
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %30
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %35
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %40
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %45
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %50
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %55
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %60
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %65
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          \voiceThree  s4 s4 s4 r8 b
  %70
  c'4 \change Staff="Organ_RH"  \voiceTwo  g'16 bes' aes' g' fis'!4 r8 d'
  d'4 r8 d' e'!4 r
  \change Staff="Organ_LH"  \voiceOne  a8 s8 s4 s4 s4
  s1*4/4          s1*4/4 %75
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          \change Staff="Organ_LH"  \voiceTwo  r8 g g g c' c' c' c'
  %80
  c' b16 a b8 g e' e' e' e'
  e' d'16 c' d'8 d' d' g c'4~
  c'8 d'16 c' b c' a b c'2
  g1
}


MvmntIIVoiceV = {
  s1*4/4          s1*4/4          s1*4/4          s1*4/4 %5
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %10
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %15
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %20
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %25
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %30
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %35
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %40
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %45
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %50
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %55
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %60
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %65
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %70
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %75
  s1*4/4          s1*4/4          s1*4/4          s1*4/4          s1*4/4 %80
  s1*4/4          s1*4/4          \voiceFour  g'4 \voiceThree  d'4 ees'2
  d'1
}


MvmntIIVoiceVI = {
  R1*4/4
  R1*4/4
  R1*4/4
  R1*4/4
  %5
  R1*4/4
  R1*4/4
  R1*4/4
  r8 d d d g g g g
  g fis16 e fis8 d b b b b
  %10
  b a16 g a8 a a d g4~
  g fis g r8 g
  a g a fis b a g fis
  e d cis b, a, g fis e
  d16 fis e fis d e cis d b, e d e cis d b, cis
  %15
  a, a g a fis g e fis d e cis d b, c a, b,
  g,8 g~  g16 fis g e fis4~  fis16 e fis d
  e4 a, d r
  a,8 b, c d e4 r
  b,8 c d e fis gis a a,
  %20
  d16 f e g f a g b c4 r8 c
  d16 e c d b, e d e a,4 a~
  a g~  g8 fis16 e fis8 a,
  b, b, cis cis d4 r8 d
  e e fis fis g4 r8 g,
  %25
  a, a, b, b, c4 r8 cis
  d4 r8 b, e4 a,
  d8 d, r16 d fis d g8 g, r16 e g e
  a8 g fis d g fis e d
  c a, d d, g,4 r8 g
  %30
  c' a b b, e4 r8 e
  a g fis d g4 r8 e
  fis e dis b, g, g16 fis g8 e
  a e c a, b, b16 a b8 b,
  e d c b, a, a b b,
  %35
  e16 fis dis fis e g fis a g a fis a g b a c'
  b8 b, r16 b, a, b, g, b, a, c b, d cis e
  d8 d, r16 d dis b, e8 e, r16 e g e
  a8 fis b b, e,4 r
  R1*4/4
  %40
  R1*4/4
  R1*4/4
  R1*4/4
  R1*4/4
  R1*4/4
  %45
  R1*4/4
  R1*4/4
  R1*4/4
  R1*4/4
  R1*4/4
  %50
  R1*4/4
  R1*4/4
  r2 r8 a, a, a,
  d d d d d cis16 b, cis8 a,
  fis fis fis fis fis e16 d e8 e
  %55
  e a, d2 cis4
  d8 e fis d e e fis fis
  g4 r8 g, a, a, b, b,
  c4 r8 c d d e e
  f e f d e d c b,
  %60
  a, g,!8 f,4 e,8 e r16 e gis e
  a8 a, r16 a, c a, d8 d, r16 b, d b,
  c8 c, r16 c e c f8 d e e,
  a,4 r16 a, c a, b,4 r16 cis e cis
  d4 r16 d fis d e4 r16 fis a fis
  %65
  g4 r16 g b g a4 r16 b d' b
  c'8 c c c g g g g
  g fis!16 e fis8 d bes bes bes bes
  bes a16 g a8 a a d g4~
  g fis g r8 g,
  %70
  c4 r8 c d4 r
  d r d,-\fermata r4
  d,8 d d d g g g g
  g fis16 e fis8 d b b b b
  b a16 g a8 a a d g4~
  %75
  g fis g r8 fis
  e2 d8 c b, a,
  g,16 g fis g e fis d e c4 r16 c' b c'
  fis g fis a b, d c d e,8 e a, d
  g,4 r8 f, e,4 r8 e,
  %80
  d,4 r8 d, c,4 r8 c,
  g,1~
  g,~
  g,-\fermata
}






\header {
  title = "Praeludium et Fuga XI"
  composer = "J. S. Bach"
}

#(set-global-staff-size 18)

\paper {
  page-count=10
  print-all-headers = ##t
  ragged-last-bottom = ##f
}

\score {
  %Praeludium
  <<
    \new PianoStaff <<
      \set PianoStaff.instrumentName = #"Manual"

      %Right hand
      \new Staff = "Organ_RH"  <<
        \new Voice = "MvmntIVoiceI"  {
          \clef treble
          \key g \major
          \time 3/4
          \MvmntIVoiceI
        }
        \new Voice = "MvmntIVoiceII"  {
          \MvmntIVoiceII
        }
        \new Voice = "MvmntIVoiceIII"  {
          \MvmntIVoiceIII
        }
        \new Voice = "MvmntIVoiceIV"  {
          \MvmntIVoiceIV
        }
      >>

      %Start of Staff: Left Hand
      \new Staff = "Organ_LH"  <<
        \new Voice = "MvmntIVoiceV"  {
          \clef bass
          \key g \major
          \time 3/4
          \MvmntIVoiceV
        }

      >>
    >>

    %Pedal
    \new Staff = "Organ_Ped"  <<
      \set Staff.instrumentName = "Pedal"
      \new Voice = "MvmntIVoiceVI"  {
        \clef bass
        \key g
        \major
        \time 3/4
        \MvmntIVoiceVI
      }
    >>
  >>

  \header {
    title = ##f
    composer = ##f
    piece = "Praeludium"
    opus = "BWV 541"
  }


}

\score {
  %Fuga
  <<
    \new PianoStaff <<
      \set PianoStaff.instrumentName = "Manual"
      %Right Hand
      \new Staff = "Organ_RH" <<
        \new Voice = "MvmntIIVoiceI"  {
          \clef treble
          \key g \major
          \time 4/4
          \MvmntIIVoiceI
        }
        \new Voice = "MvmntIIVoiceII"  {
          \MvmntIIVoiceII
        }
      >>

      %Left Hand
      \new Staff = "Organ_LH"  <<
        \new Voice = "MvmntIIVoiceIII"  {
          \clef bass
          \key g \major
          \time 4/4
          \MvmntIIVoiceIII
        }
        \new Voice = "MvmntIIVoiceIV"  {
          \MvmntIIVoiceIV
        }
        \new Voice = "MvmntIIVoiceV"  {
          \MvmntIIVoiceV
        }

      >>
    >>

    %Pedal
    \new Staff = "Organ_Ped"  <<
      \set Staff.instrumentName = "Pedal"
      \new Voice = "MvmntIIVoiceVI"  {
        \clef bass
        \key g \major
        \time 4/4
        \MvmntIIVoiceVI
      }
    >>
  >>

  \header {
    title = ##f
    composer = ##f
    piece = "Fuga"
  }
}




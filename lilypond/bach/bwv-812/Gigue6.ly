\version "2.20.0"

\include "italiano.ly"



\paper {
  #(set-paper-size "a4")
}


staffOne = \change Staff = one
staffTwo = \change Staff = two

stsu = { \staffTwo \stemUp }
sosn = { \staffOne \stemNeutral }

right =  {
        \clef treble
        \key fa \major
        \time 4/4
        % \partial 8
       \relative do'' {
       \stemDown \new voice
       
       r8 r16 \voiceOne \stemDown la re8.\mordent la16 sib8~( sib32) la sol fa mi8. sol16 |
       \stemUp r8 r16 re'16 la'8.\mordent mi16 fa8~_(\mordent fa32) mi re do! si8.\prall re16 |
       dod8.\prall fa32 sol la8.\mordent sol16 mi2( |
       mi8.) la,16 re8. la16 sib8~_(\mordent sib32) la sol fa mi8.\prall sol16 |
       fa8.\prall mi32 re sib'4~( sib8.) la32 sol la8.\mordent sib16 |
       sol8.\prall sol 16 do4~( do8.) sib32 la sib8. do16 |
       la8.\prall la16 re4~( re8.) do32 si! do8.\mordent re16 |
       mi2~( mi8.) la,16 re8. re16 |
                            re8~( re32) do si do do8.\prall si16 si2( |
                            sib8.) mi16 la8. mi16 fa8~_(\mordent fa32) mi re do si8.\prall re16 |
                            sold,8.\prall fad32 mi do'8.\mordent do16 do8\prall~( do32) re do si si8.\prall la16 |
                            la1 | \bar ":..:" 
       \break
        R1 |
        R |
        r8 r16 re sol,8. re'16 dod8\prall~( dod32) re mi fa sol8. mi16 | \break
        fa2 mi2( |
        mi8.) mi16 la,8. mi'16 fa4. r16 mi |
        re8. re16 sol,8. re'16 mi4. r16 re |
        do8~( do32) do re mi fa8~( fa32) mi fa re si'2( |
        si8.) la32 sold  la4~( la8.) sol32 fa sol4( |
        sol8.) la16 fa4\prall~( fa8)( fa32) fa mi fa sol fa mi16 fa32 mi re16 | \noBreak
        dod2\prall r8 r16 la re8. la16 |
        sib8\mordent~( sib32) la sol fa mi8.\mordent sol16 fa8. re'16 sol,8. re'16 | \break
        dod8\prall~( dod32) re mi fa sol8. mi16 fad8~( fad32) sol la sib do8. la16 |
        sib4~( sib8.) la16 sol4 fa( |
        fa16) mi re dod re mi fa sol32 la sib8~( sib32) la sol fa mi16 fa sol mi | \noBreak
        dod8.\prall si32 la fa'8.\mordent fa16 fa8~( fa32) sol fa mi mi8.\prall re16 | 
        re1 |
  


       }
       }

left =  {
        \clef bass
        \key fa \major
        \time 4/4
        % \partial 8
        \relative do{
       \new Voice = "melody" {     
         
         
          
          << \relative do'
            { \voiceTwo

              \staffOne
                            s1 |
                            fa8.\prall mi32 re dod4\trill re sol( |
                            sol8.) \stsu dod,16 re8. \sosn dod'!16 re4 dod8.\prall re32 mi |
                            \stemDown la,4 r8 r16 re, re4 dod |
                            re8. re16 sol8.\mordent re16 mi4 fa( |
                            fa8.) mi16 la8.\mordent mi16 fad4 sol( |
                            sol8.) fad16 si8. la16 sold4 la( |
                            la8.) la16 sold8.^\prall la32 si mi,8 r r4 |
                            r8 r16 mi la8. mi16  fa8 \once \tweak Y-offset #-4 \tweak X-offset 1.5 \mordent( fa32) mi re do si8. re16 |
                            do8. si16 do4~( do8.) si16 re8. fa16 |
                            mi4 la~( la) sold |
                            r8 r32 sol! fa mi fa8. re16~( re8)^([ re32) re dod si] dod4 |
                            r8 r16 mi la,8. re16 dod8\prall~( dod32) re mi fa sol8. mi16 |
                            fa4~( fa8)^( fa32) mi fa sol la4~( la8)( la32) fad sol la |
                            re,4 mi~( mi8)( mi32) fa mi re dod8.\prall si32 dod |
                            re8. la'16 re,8. la'16 sold8~^(\prall sold32) la si do re8. si16 |
                            do2~(\mordent do8.) re32 mi re8.\prall do16 |
                            si2~( si8.) do32 re do8.\prall si16 |
                            la4 r r8 r16 la' sold8.\prall la32 si |
                            mi,4~( mi8)( mi32) re mi fa si,4~( si8)( si32) si dod re |
                            mi4~( mi8)( mi32 re) dod re sol,2( |
                            sol8.) mi16 la8. mi16_\markup \italic "sinistra" fa8\mordent~( fa32) mi re do si8.\prall re16 |
                            dod2\prall re |
                            mi4 r r2 |
                            r8 r16 re' sol8. re16 mi8~( mi32) re dod si la8. do16 |
                            sib8. sol16 re8. fa16 mi8~( mi32) fa sol la sib8. sol16 |
                            la4 re re dod |
                            r8 r32 do sib la sib8. sol16~( sol8)^( sol32) sol fad mi fad4 |
              
                         
            }
            
            \new Voice  \relative do
            { \new voice
              R1 |
              R
              \voiceFour
              re8\rest re16\rest la' re8. la16 sib8~( sib32) la sol fa mi8. sol16 |
              fa4 re8\rest re16\rest fad16 sol8. mi16 la 8. la,16 |
              \stemUp re8. do16 sib8.\prall la32 sol do4\mordent  re4\rest |
              re8\rest re16\rest do32 sib la8. sib32 do re,4 re'4\rest |
              re8\rest re16\rest \stemDown re32 mi fa!8. mi32 re mi4 re\rest |
              re8\rest re16\rest si'16 mi8. si16 do8(^\mordent do32) si la sol! fad8. la16 |
              sold4^\prall la~( la) sold8. la32 si |
              mi,4~( mi8.) do16 re2( |
              \stemUp re16) re do si la sol fa mi re8. re'16 mi8. mi,16 |
              << { r8 r16 dod' re8. fa16 mi2 } \\ { la,1 } >> |
              \once  \tweak X-offset 12 re1\rest | re8\rest re16\rest \stemDown la' re,8. sol16 fad8^\prall~( fad32) sol la sib do8. la16 | sib4~( sib8)^( sib32) sib la sol la2 |
              re,8. re'32 do si8. do32 re re,8~( re32) fa mi re sold8.^\trill fad32 mi |
              la8. la,32 si \stemNeutral do8. si32 la re4 re\rest |
              re8\rest re16\rest sol,32 la si8. la32 sol do4~( do8)( do32) do re mi |
              fa8. la16 re8. la16 sold8~^(\prall sold32) la si do re8. si16 |
              do8. si16 do8. re16 mi8. fa16 mi8. re16 |
              dod8~( dod32) la si dod re8~( re32) re, mi fa sib,2^\trill |
              la4 re4\rest re2\rest |
              re8\rest re16\rest mi la8. mi16 fa8^\mordent~( fa32) mi re do sib8. re16 |
              sol,8~( sol32) fa' mi re dod8.\prall si32 dod re8~( re32) sib' la sol fad8.^\prall mi32 re |
              sol8~( sol32) la sol fa mi8~( mi32) fa mi re dod8. la16 re8. re,16 |
              sol8 re'\rest re4\rest sol8 re\rest re4\rest |
              re16\rest sol fa mi re do sib la sol8. sol'16 la8. la,16 |
              << { r8 r16 fad' sol8.\mordent sib16 la2\prall } \\ { re,1 } >> 
              \bar ":|."
              
     
            }
          >>

        }
           
            
           
                      


}}

\score {

         \context PianoStaff << #(set-accidental-style 'piano)
                \context Staff = "one" { \set Staff.extraNatural = ##t
                \right
                 }

                \context Staff = "two" { \set Staff.extraNatural = ##t
                \left
                 }
  >>  
  \layout {
  
         \context { \Staff
       \override BarLine #'hair-thickness = #0.30
  
  }
  }
  \midi {
    \context {
      \Score
      tempoWholesPerMinute = #(ly:make-moment 100 4)
    }
  }
    \header {

  piece = "Gigue"
  % Enlever le pied de page par défaut
  tagline = ##f
}
  
  
}

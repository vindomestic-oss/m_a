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
        \time 3/2
        \partial 8
        \relative do''{
\stemUp 

  \new Voice = "melody" {
 \set PianoStaff.connectArpeggios = ##t
  <<
      {
        \mergeDifferentlyDottedOn
        \voiceThree
        la8 |
        la4.\mordent sol8 fa mi fa re
        sib'4. sib8 |
        \once \override NoteColumn.force-hshift = #-0.5 la2. la4 re8\arpeggio dod re\mordent mi |
        dod4\prall si8 la \appoggiatura { la'}  sol fa sol la fa4.\prall mi8 |
        mi2. mi4\arpeggio la8 do,! re la |
        do sib la sol sib4.\mordent do8 la4. sib8 |
        do4.\mordent sib8 la sol la fa mib'4. fa8 |
        re2. re4\arpeggio mi!8 re mi fa |
        sib,4. do8 la4.\prall sol8 sol4. fa8 | 
        fa4.\prall mi8 fa sol fa sol sol4.\mordent la8 |
        la2~( la8) mi la2 
      }
            \new Voice {
        \voiceTwo
        s8 |
        s2 s2
        r8 << \new Voice { \voiceOne \stemUp \relative do'' sol4.( |
        \once \override NoteColumn.force-hshift = #1.5 sol8) mi fa2\mordent } \new Voice { \voiceFour sol8 mi dod | \once \override NoteColumn.force-hshift = #-0.5 re2. } >> \stemDown fa4 sol2\arpeggio |
        la2 mi' re4 sold, |
        la2. <la dod>4\arpeggio <la re>8 s8 s4 |
        s2 sol2~( sol4) fa4_( |
        fa2) s2 r8 do' la4 |
        r8 la sib2\mordent <fa sib>4\arpeggio <sol do>4. la8( |
        la4) sol4~( sol) fa~( fa) mi( |
        mi) re8 dod re1( |
        re8) re mi si dod4~( dod2)
             
            }
  >>
  
        }
        r8 \repeat volta 2 {  }
        la'8 |
        << { \voiceOne \relative do''
             la4.\arpeggio si8 dod8\mordent re dod mi sol,4.\prall la8 |
             sol fa mi re la'4.\mordent( sib16 do) fad,4.\prall fad8 |
             sol4.\mordent la8 sib do re mib fa4.\mordent sol8 |
             mib4\prall re8 do re4.\arpeggio sol,8 fad!4.\prall sol8 |
             r8 fad la do << {sib4. la8 la4.\downprall sol8 } \\ { \stemUp \once \override NoteColumn.force-hshift = #0.6 sol2 \once \override NoteColumn.force-hshift = #0.6 fad! } >>  |
             sol2. sol8( la16 sib) sib4. sib8 |
             sib2. la8 si16 do do4.\prall do8 |
             do4( si)\prall( si8) si dod re \stemDown mi fa mi sol |
             sib, sol la sol' fa dod re sib' la( sol fa mi) |
             re dod\prall si la la'4.\mordent do,8 do sib do la |
             do sib la sol sol'4.\mordent fa8 mi re dod re |
             re( dod\prall si la) \stemUp  sib4.\arpeggio do8 sib la sib sol |
             r dod mi sol << { fa4. mi8 mi4.\downprall re8 } \\ { \stemUp \once \override NoteColumn.force-hshift = #0.6 re2 \once \override NoteColumn.force-hshift = #0.6 dod! } >> |
               << { s2 s4 re2 } \\ { \stemUp re2~( re8) la8~( la2) } >>
             
           }
           \new Voice  \relative do'
           { \voiceTwo
             <dod mi>4.\arpeggio s8 s2 mi2 |
             re2 s2 re2( |
             re4) s4 s2 re'2 |
             do <fad, la>4\arpeggio s2. |
             re2. mib4 re do( |
             do8) mib re do sib la sib sol fa' mi fa sol |
             mi2. s4 la2 |
             la4( sol)( sol8) s8 s4 s2 |
             s1. |
             s1. |
             s1. |

             s2 <re fa>4.\arpeggio r8 mib4 r4 |
             la2. sib4 la sol( |
             sol8) sol la mi fad4~( fad2)
             
             
             
             
             
           }
        >>
        
}
\new Voice
{ r8 }


}

left =  {
        \clef bass
        \key fa \major
        \time 3/2
        \partial 8
        \relative do{
       \new Voice = "melody" {     
          r8 |
          
          <<
            { \voiceOne
              r4 fa4 la2~( la4) sol |
              la4. sol8 s4 re' re2\arpeggio |
              mi4 re~( re4.) dod8 re s8 s4 |
              s1 s2 |
              s1 s2 |
              r8 do, re mi fa1( |
              fa4.) mib8 re do re sib \stemDown sib'4. la8 |
              sol re mi do fa do re si \stemUp re dod si la |
              r8 mi' fa sol la2 sib | 
              mi,2.~( mi2)
                         
            }
            
            \new Voice  \relative do
            { \voiceTwo 
              re1.( |
              re2) fa8 mi fa re sib'4. sib8 |
              la2. la4 re8 dod! re mi |
              re dod si la sol fad sol la fad4.\prall sol8 |
              sol4.\mordent fa!8 mi re mi do fa re do sib |
              la2. sol4 la fa |
              sib2 s1 |
              s1 s2 |
              re2. do!4 sib2 |
              la2.~( la2)
     
            }
          >>

        }
            r8 %reprise
            r8 |
            
                      <<
            { \voiceOne
              r8 mi fa sol la2~( la)( |
              la) s2 r8 la re,4 |
              r8 re mi fad 
            }
            
                        \new Voice  \relative do
            { \voiceTwo 
              la2. si4 << {\once \tweak X-offset 1.5 fa'8\rest mi4. } \\
                          { dod4 la } >> |
              re4. mi8 fa sol fa la do,4. do8 |
              sib2 

            }
            
                      >>
                      
                      \new Voice {
                      sol8 mib fa re do si la sol |
              do2~( do8) la sib re mib do la' sib |
              fad4 re sol do, re\mordent re, |
              sol2
              r2 r8 sol la sib |     } 
                      
                                            <<
            { \voiceOne
        r8 sol' la sib do re do mib s2 |
        s1. |
        r4 mi, r fa r sol |
        la4. s8 s2 re2( |
        re4.) s8 s1 |
        s1. |
        s1. |
        r4 fad, la re,2
        
            }
            
                        \new Voice  \relative do
            { \voiceTwo 
              do2 r2 sol'8 fad mi! re |
              sol4. la8 sol fa sol mi sib'!4.^\mordent sib8 |
              dod,2 re sib |
              la4. sol'8 fad mi fad re r4 fad |
              sol4. fa!8 mi re dod re \stemUp sol,4 sib |
              la4. sib8 la sol la fa sol4 \stemDown  sol'4~( |
              sol8) mi dod la re4 sol la \stemUp la, |
              \stemDown  re2. re,2
   

            }
            
                      >>
} 
\new Voice {
r8 
}
\bar ":|."
}

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

  
  
}
    \header {

  piece = "Courante"
  % Enlever le pied de page par défaut
  tagline = ##f
}

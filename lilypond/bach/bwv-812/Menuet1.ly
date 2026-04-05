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
        \time 3/4
        % \partial 8
       \relative do'' {
       \stemUp re8 fa sib mi, fa\mordent la |
       sib, re sol dod, re fa |
       sol,4 sol4.\prall fa16 sol |
       \stemNeutral la2.( |
       la8) fa' mi re mi la |
       re, la' sold fad sold si |
       la mi re do si do |
       \set Score.repeatCommands = #'((volta "1") )
       la2 r4 |
       \set Score.repeatCommands = #'((volta #f) (volta "2") end-repeat)
       la2. |
       \set Score.repeatCommands = #'((volta #f) ) \break
       \bar ".|:-||"
       la4 sib!\trill do |
       sib la8\prall sol la4( |
       la8) sol fa mi fa sol |
       fa mi re mi do4 |
       fa2.( |
       fa)( |
       fa4) sol mi |
       fa8 mi fa\mordent sol la sib |
       do mib re do re sib |
       sol fa' mi! re mi do |
       la sol' fa mi fa re |
       mi re dod si dod la |
       \stemUp re2.^( |
       re)^( |
       re4) fa8 mi re dod |
       re2.\mordent
       
  


       }
       }

left =  {
        \clef bass
        \key fa \major
        \time 3/4
        % \partial 8
        \relative do{
       \new Voice = "melody" {     
         
          
          << \relative do'
            { \voiceOne
              \staffOne \stemDown fa4 sol_\trill la |
              sol fa8_\prall mi fa4( |
              fa8) mi re \stsu dod re mi |
              re dod si dod la4 |
              re4\mordent do!8\prall si do la |
              sold4 la\trill si |
              mi, la\mordent sold\mordent |
              la r4 r |
              la2. |
              \staffOne \stemDown fa'2._( |
              fa) |
              re |
              do2~( do8) \stsu sib |
              la do re sol, la do |
              fa, la sib mi, fa la |
              do4 sib8 la sol la |
              fa2\mordent r4 |
              r fa8 mi! fa4 |
              r sol8 fa sol4\mordent |
              r la re |
              dod8\prall re mi4 la, |
              \staffOne \stemDown la' sib_\trill do |
              do8 sib la sol la4 |
              fa sol mi |
              re2. |

                         
            }
            
            \new Voice  \relative do
            { \voiceTwo 
              re'2.( |
              re) |
              sib |
              la2~( la8) sol |
              fa2.( |
              fa4) mi re |
              do re mi |
              la, la'8 si dod la |
              la,2. |
              fa'8 la re sol, la do |
              re, fa sib mi, fa la |
              sib,4 si4.^\downprall la16 si |
              do4 re mi |
              mib fa8 mib re do |
              re4 do8 sib la sol |
              la4 sib do |
              fa fa, la |
              la sib4. la8 |
              do si do4. la8 |
              re dod re4 sib'( |
              sib) la8 sol fa mi |
              fad la re sol, la do |
              re, sol sib mi, fa la |
              \stemUp sib,4 sol la |
              << { re2. } \\ { re,2.} >> |

     
            }
          >>

        }
            %reprise
            
           
                      

\bar ":|."
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

  piece = "Menuet I"
  % Enlever le pied de page par défaut
  tagline = ##f
}
  
  
}

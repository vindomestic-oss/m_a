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
        \relative do''{
\stemUp 

  \new Voice = "melody" {
 \set PianoStaff.connectArpeggios = ##t
  << \relative do''
      {
        \mergeDifferentlyDottedOn
        \voiceOne
        la4\mordent sib8 la dod re |
        sol, la sib2\mordent( |
        sib8) la sol mi' la, sib16 sol |
        fad8\prall sol la2\mordent( |
        la8) re sib la sol fad |
        sol la16 sib la8 sol fa! mi\prall |
        re fa sib sol mib' dod |
        sold'\arpeggio la dod,2 |

      }
            \relative do' \new Voice {
        \voiceTwo
        fa4 sol fa |
        mi mi2( |
        mi4) mi mi |
        re re2( |
        re4) re re |
        dod dod dod |
        re r4 sol |
        <la re>\arpeggio la2 |

             
            }
  >>
  
        }
         \repeat volta 2 {  }
        
        
        << { \voiceOne \relative do''
             mi 4 mi <re fa>\arpeggio | 
             dod dod2 | do!4 do8 sib << { mib4( |
             mib8) re do fad\mordent sol\turn  la | }
                                        \\ { do,4 | s2. } >>
             sib'4 sib sib |
             sib8 la do sib la sol |
             fad sol sib la sol fa |
             sol4 sol2 |
             mi4 <re fa>8 <do mi> <mi sol> <fa la> |
             <mi sib> <do fa> fa2\arpeggio( |
             fa8) mi re si' mi, re |
             dod\prall re mi2\mordent( |
             mi8) la fa mi re do |
             sib! sol' dod, sib la sol |
             fa sib sold la fa' mi |
             dod re re2 |
             
              } 
             
           
           \new Voice  \relative do''
           { \voiceTwo
             <la dod>4 <sol dod> <fa la>\arpeggio |
             <mi la> <mi sol>8 <sol sib>     \new Voice << \relative { \stemDown la'8 \appoggiatura sib16 sol8 } \relative { \stemDown fa'8 mi8 } >> |
             <mib fad>4 <mib sol>8 <sol sib> \once \override NoteColumn.force-hshift = #0.6 fad![ sol] |
             <la do> 4 r r |
             <re fad> <re sol> <re sol> | <re sol>8 do mib re do sib |
             la sib re do sib la |
             sib4 <sib re>2 |
             <sol do>4 sol sol( |
             sol8) fa <la do>2\arpeggio |
             si4 si si |
             la la2 |
             la4 la la |
             sol sol mi |
             re8 dod8 re4 la'8 sol |
             sol4 fad2\mordent |
             
    
           }
           >>


}}

left =  {
        \clef bass
        \key fa \major
        \time 3/4
        % \partial 8
        \relative do{
       \new Voice = "melody" {     
         
          
          << \relative do'
            { \voiceOne
              re4 re re |
              sib8 la sol2( |
              sol8) mi la4 la( |
              la8) sol8 fad2( |
              fad4) sol sol |
              la mi la8 sol |
              fa4 sol~( sol8) mi! |
              fa re mi2 |
              la,4 sib8 la dod re |
              sol, la sib2( |
              sib8) la sol mib' la, sol |
              fad la <mib' fad >2 |
              s2. |
              s |
              r4 fad r |
              s2. |
   
                  \stemUp sib,4 \stemDown sib' sib |
              la~( la8) do sib la |
              \stemUp re8 si mi4 mi |
              mi8 re dod2 |
              fa4 re re  |
              re mi la, |
              la8 sol s4 dod8 mi |
              mi re re2 |
                         
            }
            
            \new Voice  \relative do
            { \voiceTwo 
              re4 re re |
              re4. fa8 mi re |
              dod4 dod dod |
              do!4. mib8 re do |
              sib4 sib sib |
              la la la |
              la sol sib |
              la la2 |
              s2. |
              s |
              s |
              s4 la2( |
              \stemUp la8) re sib la sol\prall fa! |
              mib4 r8 sib' do re |
              \stemDown mib4 re re, |
              sol8 re' mib re fad sol |
              s2. |
              s |
              sold4 sold sold |
              sol!4. sib8 la sol |
              fa4 fa fa |
              fa mi8 re dod4 |
              re8 mi fa re la'4 |
              <sib re,> <re, la'>2 |
          
    
            }
          >>

        }
        
            
           
                      

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

  piece = "Sarabande"
  % Enlever le pied de page par défaut
  tagline = ##f
}
  
  
}

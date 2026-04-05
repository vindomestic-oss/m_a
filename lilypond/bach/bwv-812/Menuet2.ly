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
       \stemUp 
       la4\mordent la4.\prall sol16 la |
      sib8 do re sib do la |
      sol4*2/3 s4*1/3 \once  \tweak Y-offset -0.5 \prallup do4. sib8 |
      la sol sib la sol fa |
      re'2.^( |
      re)^( |
      re8) re dod si la sol |
      fa mi sol fa mi re |
      la'4\mordent la4.\prall sol16 la |
      sib8 do re sib do la |
      sol4 sol4.\prall fa16 sol |
      la8 sib do la sib sol |
      fa4 fa4.\prall mi16 fa |
      sol8 la sib la sib sol |
      s4*1/3 \once  \tweak Y-offset -1 \prallup la4*2/3 sol8 fa mi fa |
      re2.\prall |
      \bar ":|."
      
      la'8 sol fa sol la sib |
      do sol la sib do sib |
      do mib re do sib la |
      sib la do sib la sol |
      dod4 dod4.\prall si16 dod |
      re4 re4.\prall dod16 re |
      mi8 fa sol mi fa re |
      mi4 re8 dod si la |
      
             la4\mordent la4.\prall sol16 la |
      sib8 do re sib do la |
      sol4*2/3 s4*1/3 \once  \tweak Y-offset -0.7 \prallup do4. sib8 |
      la sol sib la sol fa |
      re'2.^( |
      re)^( |
      re8) re dod si la sol |
      fa mi sol fa mi re |
      la'4\mordent la4.\prall sol16 la |
      sib8 do re sib do la |
      sol4 sol4.\prall fa16 sol |
      la8 sib do la sib sol |
      fa4 fa4.\prall mi16 fa |
      sol8 la sib la sib sol |
      s4*1/3 \once  \tweak Y-offset -1 \prallup la4*2/3 sol8 fa mi fa |
      re2.\prall | 
      
  


       }
       \bar "|."
       }

left =  {
        \clef bass
        \key fa \major
        \time 3/4
        % \partial 8
        \relative do{
       \new Voice = "melody" {     
         
          
          << \relative do'
            { \voiceTwo
              \staffOne \stemDown 
              fa4 fa2 |
              sol2~( sol8) fa |
              mi4 mi2 |
              fa2 r4 |
              fa4 fa4.\prall mi16 fa |
              sol8 la sib sol la fa |
              mi2. |
              re2 r4 |
              fa fa2( |
              fa2.)( |
              fa4) mi2( |
              mi2.)( |
              mi4) re2( |
              re4) dod2 |
              re2 dod4 |
              re2. |
              
              
    
                         
            }
            
            \new Voice  \relative do
            { \voiceThree 
              re4 re' do |
              sib4 la8 sol la sib |
              do4 do,8 sib la sol |
              \stemUp fa4 sol la |
              \stemNeutral sib8 fa' sib la sol fa |
              mi dod re mi fa sol |
              la4 la, la' |
              re, fa, la |
              re,8 la' re do sib la |
              sol la sib sol la sib |
              do sol' do sib la sol |
              fa sol la fa sol la |
              sib do sib la sol fa |
              mi fa sol fa sol mi |
              fa4 sol la |
              re, la re, |
              
 

     
            }
          >>

        }
              << \relative do'
            { \voiceTwo
             \stemDown     
        
              re,4\mordent re4.\prall do!16 re |
              mi2. |
              fad4 fad4.\prall mi!16 fad |
              sol4 re sol, |
              sol'8 fa sol sib la sol |
              fa la sol fa mi re |
              dod4 la re |
              la si dod |
                            re4 re' do |
              sib4 la8 sol la sib |
              do4 do,8 sib la sol |
              \stemUp fa4 sol la |
              \stemNeutral sib8 fa' sib la sol fa |
              mi dod re mi fa sol |
              la4 la, la' |
              re, fa, la |
              re,8 la' re do sib la |
              sol la sib sol la sib |
              do sol' do sib la sol |
              fa sol la fa sol la |
              sib do sib la sol fa |
              mi fa sol fa sol mi |
              fa4 sol la_\markup {\italic "Menuet I da capo"} |
              re, la re, |
         
              
            }
        
        
                    \new Voice  \relative do
            { \voiceThree 
        
                  \staffTwo r2 r4 |
              \stemUp sol'4 sol4.\prall fad16 sol |
              la2. |
              sol2. |
              \staffOne \stemDown mi'4 mi2 |
              la4 la2_( |
              la4) dod re |
              dod \voiceTwo r r |
              
               fa,4 fa2 |
              sol2~( sol8) fa |
              mi4 mi2 |
              fa2 r4 |
              fa4 fa4.\prall mi16 fa |
              sol8 la sib sol la fa |
              mi2. |
              re2 r4 |
              fa fa2( |
              fa2.)( |
              fa4) mi2( |
              mi2.)( |
              mi4) re2( |
              re4) dod2 |
              re2 dod4 |
              re2. |
              
              
              
              
            }
              >>
            
            
           
                      


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

  piece = "Menuet II"
  % Enlever le pied de page par défaut
  tagline = ##f
}
  
  
}

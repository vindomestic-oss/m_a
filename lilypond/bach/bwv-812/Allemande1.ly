 #(set-global-staff-size 19)
\version "2.20.0"

\include "italiano.ly"




\paper {
  #(set-paper-size "a4")
  

    ragged-last-bottom = ##f     %%pour répartir les systèmes dans la page
    % Enlever le pied de page par défaut
  tagline = ##f
  
}

staffOne = \change Staff = one
staffTwo = \change Staff = two

stsd = { \staffTwo \stemUp }
sosn = { \staffOne \stemNeutral }

global = {
  \key fa \major
  \time 4/4
  \partial 16
}

right = \relative do'' {
  \global
%01
re16 |
re la sib sol la fa mi\prall re r 
\set Staff.connectArpeggios = ##t
<<
  \relative {
\mergeDifferentlyDottedOn sib' mi sol~( sol) sol fa mi |
sol fa mi re fa4 mi8.\arpeggio mi16 la mi fa dod |
re4~( re16) fa mi sol re dod si la do4( | do16) sib!8.~( sib4)~( sib16) mi,! la8~( la8.) sib32 la |

%05
sol4~( sol16) fa mi fa }
  \\
  \relative { 
    sib'8. la4( | la) r16 la sib fa <sol sib>8.\arpeggio r16 mi8 la( |
    la16) la sib fad sol2 r16 sol la fad! |
    sol8 re16 fa! mib sol dod, re dod4 r16 la re8 |
   %05
   r16 re mi si dod4
    
  }
>>
  
  sol16 fa mi re sib'!8.\mordent sib16 |

  << \relative do''
      {
        \mergeDifferentlyDottedOn
        \voiceOne
        sib16 sol la do mib4~( mib8.) re16 r sib re sol | \break
        do,4~(   
        do16) sib la sib do la sib 

      }
            \relative do'' \new Voice {
        \voiceTwo
        s4 r16 << {  \autoBeamOff  do8. \autoBeamOn \once \tweak X-offset -1 si16\rest la[ sib8]   } \\ { do16 << { la8 s4 } \\ { la16 fa~( fa4) } >>   } >> sol |
        r16 sol la mi fad4 
        
            
            }
  >>
   
sol16 mi'8.\mordent mi16|
mi la fa dod re8.\mordent re16 << { sol4~( sol16) sol fa\prall mi } \\ { r16 re mi si dod!4 } >>  |
\stemDown fa16 dod re fa sib8. sib16 sib la32 sol fa sol mi16
\set Staff.connectArpeggios = ##t
<< 
  \relative {

la''4~( |

%10
la16) sol sib la sol fa mi re( dod8.\prall) re16 mi fa sol8( | \break
sol16) fa mi fa fa8.\upprall mi16 mi4 r | r16 la, re fa~( fa) fa mi re <dod mi la>4..\arpeggio \repeat volta 2 {  } \pageBreak
    
  }
  
  \\
  \relative {

    r16 sol'' fa mi |
    re4. r8 r4 r8 sol16 sib, | 
    la4. re8~( re16) si dod la sib sol fa\prall mi |
    fa4 sold la4..\arpeggio





} >> mi16 |
mi la sol mi fa re dod si 
<< \relative do'' {
dod2\=1( | dod16\=1)  mi16 re sib
   }
   \\
   \relative do' {
     r16 la' << {sib8~( sib4) } \\   {sib16 sol~( sol4)} >>
} >>
 sol16 sib la sol << \relative do' { fa dod re fa sib8. sib16 |

%15
sib sol la do mib4~( mib16) do re fad sol8.\mordent sol16 |
sol re mib si do4~( do4) s4 |}
  \\ \relative do' {
    r8 re~( re4) |
    mib r16 do' la fa r8 r16 do re4 |
    r r16 la' sib sol fad4 r16 fad! la mib'! }
 >>
                     
                     
re'16 do32 sib la sib sol16~( \stemUp sol) fad la do sib la sol la \stemNeutral  sib8.\mordent sib16 |
sib sol' mi do sib8.\upprall la32 sib la8. si16 dod re mi fa |
sol la32 sib la sib sol16 fa sol32 fa mi fa re16 dod8\prall si16 la mi'8.\mordent mi16 |

%20
mi dod re fa 
<< \relative do''' {
sol4~( sol8.) sol16 fa4( | \break
fa16) sib, mib8~( mib16) do re mib re8. re16~( re) sol, do8( |
do4)( do16) mib re do sib4 r16 sol la sib |
r mi,! la8~( la16) si dod re }
   \\
   \relative do'' {
    r16 la sib! sol r la dod!8 r16 re sib la | 
    sol8. sol16 la4~( la16) la sib8 mi,!4( |
    mi16) sib' la sol fad4 r16 fad sol re mib4 |
    dod4     
   }
>>

mi16 fa32 sol fa sol mi16 mi8.\prall re16 |
<< \relative do'' {
re4~( re8.) dod16 re8. la16\=1( <la\=1) re>8. }
   \\
   \relative do'' {
     r16 sib do la sib fad sol8~( sol16) mi16 fad8\=2( <re fad\=2)>8.
     
   }
>>   
   \repeat volta 2 {  }











   \pageBreak
  
}



left = \relative do' {
  \global
  %01
  r16 |
  <<
    
      \relative {
      s2 dod' | re8 r }
      \\
      \relative {
  re1( |
  re8) la' re4(^\mordent re16) re do!^\prall sib do8 la } 
    >> |
    sib la sib sol la sol fad\prall re |
    sol\mordent sol, sol'8.\mordent sol16 sol8. fa32 mi fa4( |
    
    %05
    fa8.) sol32 fa mi8 la re,4 r16 re' do!\prall sib! |
    do8[ sib] la fa sib\mordent sib, sib'8.\mordent sib16 |
    sib8. do32 sib la16 re do re sol,4 r16 dod re mi |
    <<
      \relative {
        
        
        fa8[ fa'~]( \stemDown fa16) fa mi\prall re
      
      }
      \\
      \relative {
    fa4 s }
    >>
    mi8\mordent[ sol,] la la, |
    re4~( re16) mi fa sol do,!4~( do16) re mi fa |
    
    %10
    sib,4 sib'~( sib16) la sib la sol fa mi re |
    <<
      \relative {
        r8 la4\mordent sold8 la2( | la2)( la4..) }
      \\
      \relative {
        dod4 re la2( | la)( la4..)
      }
    >>
    
    r16 |
    << \relative do' {
      r8 dod << {re[ fa] } \\ { re4 }>>  mi4 mi |
      r8 la, sib16 sol dod8 r8 fa,8~( fa16) sol la sib |
       }
       \\
       \relative do' {
        la2~( la4)( la16) sib la sol |
        fa4~( fa8) mi re2 |
       }
    >>  
   do'8. sib16 la8 fa sib4~( sib16) sol la sib |
   << \relative do' {
     r8 sol la4 r16 do re la sib4( |
     sib8) do re4~( re16) do sib la }
      \\
      \relative do {
       mib4~( mib16) do re mib re2( |
       re4.) re8 sol4 }
   >>
   sol16 fa! mi re |
<< \relative do' {
  r4 do~( do16) do sib la }
   \\
   \relative do {
     do8 re mi do fa4 }
>>
sol16 fa mi re |
dod8[ la] re sol, la la'8~( la16) sol fa mi |
    << \relative do' {
      r8 la si dod re2~( \stemDown re8) do!16 sib  }
       \\
       \relative do {
         fa4. mi8 re2 }
    >>
    do'8 fa, sib4~( sib8.) sib16 | 
    la sol fad mi re do sib la sol4 sol'8.\mordent sol16 |
    sol fa! mi re dod si la sol 
    << \relative do {
      r16 la re8~( re) dod! | re2. re8. }
       \\
       \relative do, {
         fa8. sol16 la4 | re,2. re8. }
    >>
  
  
}

\score {
  \new PianoStaff <<
    \new Staff = "one" \with {
      midiInstrument = "acoustic grand"
      \consists "Span_arpeggio_engraver"
    } \right
    \new Staff = "two" \with {
      midiInstrument = "acoustic grand"
    } { \clef bass \left  }
  >>
  \layout {
  
       \context { \Staff
       \override BarLine #'hair-thickness = #0.30
       }
  
  }
  \midi {
    \context {
      \Score
      tempoWholesPerMinute = #(ly:make-moment 70 4)
    }
  }
  
  \header {
  piece = "Allemande"
  % Enlever le pied de page par défaut
  tagline = ##f
}
  
}

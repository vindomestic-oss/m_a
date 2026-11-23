"""Split the multi-movement files added 2026-11-23 to musicxml/musedata/ (reuses _split_organ_sonatas.run):
BWV 1027-1029 (gamba sonatas), BWV 1063 (concerto), BWV 992 (Capriccio), Kleine Praeludien BWV 924-931.
Boundaries = 0-based <measure> indices of part P1 (end exclusive), read from key/time/tempo changes and final barlines.
BWV 1061 is removed (moved to _unsplit/), the four single-file duplicates of Kleine Praeludien too."""
import os, shutil
import _split_organ_sonatas as so

JOBS = [
 ('bwv-1027-sonata-for-viola-da-gamba-and-harpsichord.mxl', None,
  [(0, 29, '01-adagio', 'I. Adagio'), (29, 143, '02-allegro-ma-non-tanto', 'II. Allegro ma non tanto'),
   (143, 161, '03-andante', 'III. Andante'), (161, 304, '04-allegro-moderato', 'IV. Allegro moderato')],
  'bwv-1027-gamba-sonata'),
 ('bwv-1028-sonata-per-a-viola-de-gamba-i-claveci-num-2-en-re-majo.mxl', None,
  [(0, 23, '01-adagio', 'I. Adagio'), (23, 105, '02-allegro', 'II. Allegro'), (105, 135, '03-andante', 'III. Andante'),
   (135, 260, '04-allegro', 'IV. Allegro')], 'bwv-1028-gamba-sonata'),
 ('bwv-1029-sonata-per-a-viola-de-gamba-i-claveci-num-3-en-sol-menor.mxl', None,
  [(0, 111, '01-vivace', 'I. Vivace'), (111, 143, '02-adagio', 'II. Adagio'), (143, 254, '03-allegro', 'III. Allegro')],
  'bwv-1029-gamba-sonata'),
 ('bwv-1063-concerto-for-three-harpsichords-in-d-minor-a-415-hz.mxl', None,
  [(0, 290, '01-allegro', 'I. Allegro'), (290, 359, '02-alla-siciliana', 'II. Alla Siciliana'),
   (359, 583, '03-allegro', 'III. Allegro')], 'bwv-1063-concerto'),
 ('bach-js-capriccio-bwv-992.mxl', None,
  [(0, 17, '01-arioso', 'I. Arioso'), (17, 36, '02-andante', 'II. Andante'), (36, 85, '03-adagissimo', 'III. Adagissimo'),
   (85, 96, '04-allhier-kommen-die-freunde', 'IV. Allhier kommen die Freunde'),
   (96, 108, '05-aria-di-postiglione', 'V. Aria di postiglione'), (108, 167, '06-fuga', 'VI. Fuga')], 'bwv-992-capriccio'),
 ('kleine-praludien-bwv-924-926-927-930-928-925-931-johann-sebastian-bach.mxl', None,
  [(0, 18, 'bwv-924-kleines-praeludium-c-major', 'BWV 924'), (18, 66, 'bwv-926-kleines-praeludium-d-minor', 'BWV 926'),
   (66, 81, 'bwv-927-kleines-praeludium-f-major', 'BWV 927'), (81, 123, 'bwv-930-kleines-praeludium-g-minor', 'BWV 930'),
   (123, 147, 'bwv-928-kleines-praeludium-f-major', 'BWV 928'), (147, 165, 'bwv-925-kleines-praeludium-d-major', 'BWV 925'),
   (165, 173, 'bwv-931-kleines-praeludium-a-minor', 'BWV 931')], ''),
]
REMOVE = ['bwv-1061-concerto-for-two-harpsichords-in-c-major.mxl', 'bwv-930-prelude-in-g-minor.mxl',
          'little-prelude-f-major-bwv-927-js-bach.mxl', 'prelude-in-d-major-bwv-925-johann-sebastian-bach.mxl',
          'preludio-bwv-926-bach.mxl']

if __name__ == '__main__':
    done = [so.run(*j) for j in JOBS if os.path.exists(os.path.join(so.D, j[0]))]
    os.makedirs(os.path.join(so.D, '_unsplit'), exist_ok=True)
    for p in done + [os.path.join(so.D, f) for f in REMOVE if os.path.exists(os.path.join(so.D, f))]:
        shutil.move(p, os.path.join(so.D, '_unsplit', os.path.basename(p)))
        print('moved to _unsplit:', os.path.basename(p))

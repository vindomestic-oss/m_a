"""Split BWV 989 (Aria variata) and BWV 831 (French Overture) into one .mxl per movement/variation.
Reuses the splitter of _split_organ_sonatas.py (state carry-over, renumbering from 1, move original to _unsplit/).
Boundaries = indices of <measure> elements in the single part (0-based, end exclusive)."""
import os, shutil
import _split_organ_sonatas as so

B989 = 'bwv-989-aria-variata'
V989 = [(0, 13, '01-aria', 'Aria'), (13, 25, '02-var-1', 'Var. 1'), (25, 37, '03-var-2', 'Var. 2'),
        (37, 52, '04-var-3', 'Var. 3'), (52, 64, '05-var-4', 'Var. 4'), (64, 78, '06-var-5', 'Var. 5'),
        (78, 90, '07-var-6', 'Var. 6'), (90, 102, '08-var-7', 'Var. 7'), (102, 117, '09-var-8', 'Var. 8'),
        (117, 131, '10-var-9', 'Var. 9'), (131, 143, '11-var-10', 'Var. 10')]
B831 = 'bwv-831-french-overture'
# section labels sit in the LAST bar of the previous section in this edition; starts verified by the opening notes
# (dance repeats incl. Da Capo stay inside their dance)
V831 = [(0, 184, '01-ouverture', 'Ouverture'), (184, 233, '02-courante', 'Courante'),
        (233, 378, '03-gavotte', 'Gavotte I-II-I'), (378, 554, '04-passepied', 'Passepied I-II-I'),
        (554, 610, '05-sarabande', 'Sarabande'), (610, 762, '06-bourree', 'Bourrée I-II-I'),
        (762, 931, '07-gigue', 'Gigue')]
JOBS = [('bwv-989-aria-variata-alla-maniera-italiana.mxl', None, V989, B989),
        ('bwv-831-french-overture-in-b-minor.mxl', None, V831, B831)]

if __name__ == '__main__':
    done = [so.run(*j) for j in JOBS if os.path.exists(os.path.join(so.D, j[0]))]
    os.makedirs(os.path.join(so.D, '_unsplit'), exist_ok=True)
    for p in done:
        shutil.move(p, os.path.join(so.D, '_unsplit', os.path.basename(p)))
        print('moved to _unsplit:', os.path.basename(p))

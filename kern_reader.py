import sys, os, multiprocessing

multiprocessing.freeze_support()

_here = os.path.dirname(os.path.abspath(__file__))
_reader_dir = os.path.join(_here, 'reader')
if _reader_dir not in sys.path:
    sys.path.insert(0, _reader_dir)

import importlib.util
_spec = importlib.util.spec_from_file_location(
    '_core', os.path.join(_reader_dir, 'app.py'))
_core = importlib.util.module_from_spec(_spec)
sys.modules['_core'] = _core
_spec.loader.exec_module(_core)

from reader.app import (
    find_kern_files, find_xml_files, find_generated_files,
    find_lilypond_files, find_music21_files, find_tobis_files,
    find_imslp_files, KERN_DIR, check_file, prepare_grand_staff,
    add_beam_markers, analyze_motifs, _vtk, _composer_from_rel,
)

if __name__ == '__main__':
    _core._run_main()

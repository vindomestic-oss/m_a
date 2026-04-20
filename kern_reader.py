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

if __name__ == '__main__':
    _core._run_main()

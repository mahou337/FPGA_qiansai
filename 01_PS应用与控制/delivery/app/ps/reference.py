"""Load the unchanged algorithm from the source tree or deployment bundle."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parent / 'reference'
if not REFERENCE.is_dir():
    REFERENCE = HERE.parents[1] / 'gesture_classic'
if not (REFERENCE / 'skin_detection.py').is_file():
    raise RuntimeError('Missing gesture_classic reference modules')
sys.path.insert(0, str(REFERENCE))

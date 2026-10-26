r"""Run kicad-review from a clone or a downloaded zip without installing it, with any Python 3.9+ (KiCad's own
python works too, e.g. "C:\Program Files\KiCad\10.0\bin\python.exe" kicad-review.py ...)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
from kicad_review.kireview import main  # noqa: E402

main()

"""Make `moose_scout` importable in tests without installing the package.

`pytest tests/` failed with ModuleNotFoundError because src/ is not on the path in a
bare checkout. Adding it here means the suite runs from a plain clone — which is the
whole point of having a suite: it has to run before anything is set up.
"""
import os
import sys

ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("MOOSE_SCOUT_CONFIG", os.path.join(ROOT, "config"))

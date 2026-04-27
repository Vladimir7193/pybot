"""pytest bootstrap — injects pybot/ into sys.path."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYBOT_DIR = os.path.abspath(os.path.join(HERE, os.pardir))

if PYBOT_DIR not in sys.path:
    sys.path.insert(0, PYBOT_DIR)

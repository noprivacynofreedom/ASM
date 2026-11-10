"""Where the tests find the code they test.

The shipped Atlas backend lives in atlas-rust-desktop/src-tauri/resources/atlas/ (that is the folder the
installer bundles). Import this module BEFORE importing any Atlas module so the tests exercise the
shipped code, not a stale copy.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "atlas-rust-desktop" / "src-tauri" / "resources" / "atlas"

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

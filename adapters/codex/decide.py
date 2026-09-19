#!/usr/bin/env python3
"""Run the shared decision CLI while preserving the user's project as its config root."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "runtime"))
from decision.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

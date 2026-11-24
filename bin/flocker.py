#!/usr/bin/env python3
"""Flocker's command-line entry point: ``python bin/flocker.py <command> --help``.

Project: Flocker
File: bin/flocker.py
Purpose: run flocker.cli from any checkout without installing the package (src/ is put on sys.path)
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)

Run it with the Flocker environment's interpreter, e.g. ``conda run -n Flocker python bin/flocker.py eval ...``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flocker.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

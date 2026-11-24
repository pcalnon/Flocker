"""Shared pytest fixtures for Flocker's tests.

Project: Flocker
File: tests/conftest.py
Purpose: the real TeamTrack tree for integration tests, skipped when the data is absent
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE)
"""

from pathlib import Path

import pytest

from flocker.paths import teamtrack_root


@pytest.fixture
def real_teamtrack() -> Path:
    root = teamtrack_root()
    if not (root / "teamtrack-mot" / "soccer_top").is_dir():
        pytest.skip(f"TeamTrack data not found under {root}")
    return root

"""Smoke tests for the bmops CLI entrypoint."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_cli_help_runs():
    cli = Path(__file__).resolve().parents[1] / "scripts" / "bmops.py"
    result = subprocess.run(
        [sys.executable, str(cli), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "check-regression" in result.stdout
    assert "pack" in result.stdout

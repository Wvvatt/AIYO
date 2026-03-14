"""Entry point for CLI."""

from __future__ import annotations

import sys

from aiyo.cli import cli

if __name__ == "__main__":
    sys.exit(cli())

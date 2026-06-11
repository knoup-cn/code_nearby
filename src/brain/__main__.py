from __future__ import annotations

import sys

from .cli import app
from .tui import run as run_tui

if __name__ == "__main__":
    # No arguments → TUI mode
    # `brain .` → analyze current directory
    # Other arguments → CLI mode
    if len(sys.argv) == 1:
        run_tui()
    elif len(sys.argv) == 2 and sys.argv[1] == ".":
        sys.argv = ["brain", "analyze", "."]
        app()
    else:
        app()

from __future__ import annotations

import sys

from .cli import app
from .tui import run as run_tui

if __name__ == "__main__":
    # 无参数 → TUI 模式
    # `brain .` → 分析当前目录
    # 其他参数 → CLI 模式
    if len(sys.argv) == 1:
        run_tui()
    elif len(sys.argv) == 2 and sys.argv[1] == ".":
        sys.argv = ["brain", "analyze", "."]
        app()
    else:
        app()

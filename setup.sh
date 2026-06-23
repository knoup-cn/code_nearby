#!/usr/bin/env bash
#
# Code Nearby — 一键安装脚本
#
# 用法:
#   git clone https://github.com/knoup-cn/code_nearby.git && cd code_nearby && bash setup.sh
#
# 零前置依赖：脚本自动安装 uv（含 Python 3.12），无需手动装任何东西。
#
set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

log()  { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*"; }
err()  { echo -e "${RED}✗${RESET} $*"; }
info() { echo -e "${CYAN}→${RESET} $*"; }

# ── 0. 定位项目根目录 ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f "pyproject.toml" ]; then
    err "未找到 pyproject.toml，请在项目根目录运行此脚本"
    exit 1
fi

echo ""
echo -e "${BOLD}Code Nearby — 一键安装${RESET}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. 确保 uv 可用（uv 自带 Python 管理，无需系统 Python）─────────
if command -v uv &>/dev/null; then
    log "uv $(uv --version 2>/dev/null || echo 'found')"
else
    info "安装 uv（含 Python 3.12）..."
    curl -LsSf https://astral.sh/uv/install.sh | bash
    export PATH="$HOME/.local/bin:$PATH"
    log "uv 安装完成"
fi

# ── 2. 通过 uv 确保 Python 3.12 ─────────────────────────────────────
info "确保 Python 3.12 ..."
uv python install 3.12 2>/dev/null || true
PYTHON="$(uv python find 3.12 2>/dev/null || true)"
if [ -n "$PYTHON" ]; then
    log "Python 3.12: $PYTHON"
else
    err "无法获取 Python 3.12"
    exit 1
fi

# ── 3. 同步依赖 ─────────────────────────────────────────────────────
info "同步依赖 (mcp + dev) ..."
uv sync --extra mcp --extra dev

log "依赖安装完成"

# ── 4. 验证导入 ─────────────────────────────────────────────────────
info "验证安装 ..."
uv run python -c "import code_nearby; print('code-nearby (dev)')" 2>/dev/null || true

# ── 5. 打印 MCP 配置 ───────────────────────────────────────────────
PROJECT_DIR="$SCRIPT_DIR"
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  MCP 客户端配置${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo "将以下内容添加到你的 MCP 客户端配置中："
echo ""
echo -e "  ${YELLOW}Claude Code${RESET}  →  ~/.claude/settings.json 或 <project>/.claude/settings.json"
echo -e "  ${YELLOW}VS Code${RESET}       →  .vscode/mcp.json"
echo ""
echo -e "${CYAN}──────────────────────────────────────────${RESET}"
cat <<MCPCONFIG
{
  "mcpServers": {
    "nearby": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "$PROJECT_DIR",
        "nearby-mcp"
      ]
    }
  }
}
MCPCONFIG
echo -e "${CYAN}──────────────────────────────────────────${RESET}"
echo ""
echo -e "${GREEN}✓ 安装完成！${RESET} 配置好 MCP 客户端后重启即可使用。"
echo ""
echo "可选操作:"
echo "  uv run pytest          # 运行测试"
echo "  uv run nearby-mcp      # 手动启动 MCP server"
echo ""

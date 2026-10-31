#!/bin/zsh
# Local developer bundle launcher: does not install a bridge or launch/modify a game.
set -eu
cd -- "${0:A:h:h}"
if ! command -v uv >/dev/null 2>&1; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    export PATH="$HOME/.local/bin:$PATH"
  else
    print -u2 '需要先安装 uv；此启动器不会自动下载安装工具。'
    exit 1
  fi
fi
print '正在启动本机后端与桌宠。游戏桥接须已在此 Mac 上单独准备并启动；此入口不启动或修改游戏。'
exec uv run --frozen --extra save --extra agent python scripts/run_mvp.py "$@"

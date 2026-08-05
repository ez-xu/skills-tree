#!/bin/bash
# Skills Tree Sync — 调用 _sync.py 完成所有操作
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# 自动检测 Python: Git Bash 优先 python，Linux 优先 python3
if [ -n "$MSYSTEM" ] || [ "$OS" = "Windows_NT" ]; then
    PYTHON=$(command -v python 2>/dev/null || command -v python3 2>/dev/null)
else
    PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
fi

exec "$PYTHON" "$DIR/_sync.py"

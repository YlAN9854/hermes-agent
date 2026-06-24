#!/usr/bin/env bash
# ContextVis 后端纯函数测试套件
# 用法: cd <repo> && bash context-vis/tests/run_all.sh
set -e

PYTHON="/home/frey_ubuntu/.hermes/hermes-agent/venv/bin/python"
REPO="$(git rev-parse --show-toplevel)"

echo "=== ContextVis tests ==="
PYTHONPATH="$REPO" "$PYTHON" "$REPO/context-vis/tests/test_reference_graph.py"
PYTHONPATH="$REPO" "$PYTHON" "$REPO/context-vis/tests/test_residual_drop.py"
echo "=== All suites passed ==="

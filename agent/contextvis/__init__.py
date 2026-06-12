"""ContextVis 服务端：上下文分块真值快照（只读、best-effort）。

见 agent/contextvis/chunking.py 与根目录 CLAUDE.md。
"""

from agent.contextvis.chunking import (
    build_snapshot_chunks,
    drop_indices_for_chunks,
)

__all__ = ["build_snapshot_chunks", "drop_indices_for_chunks"]

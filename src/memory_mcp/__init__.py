"""memory-mcp：供 xiaozhi-server / Agent 在会话中调用的记忆工具服务（docs/05）。

约束：
- 工具调用可能在会话中，须轻量、有超时（800ms~1.5s），失败则对话降级无记忆；
- 不做浏览器、不跑重摘要；
- 鉴权：仅内网或带服务间 token；
- 工具白名单仅 memory.*，无 shell/SQL/DBA 工具（docs/08 §5）。
"""

from memory_mcp.server import main, mcp

__all__ = ["main", "mcp"]

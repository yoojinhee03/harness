"""harness MCP 서버 패키지.

FastAPI 백엔드 없이 in-process 로 resolver·catalog·runtime 을 감싸, 에디터(Claude Code·
Cursor·Claude Desktop) 안에서 recommend → resolve → eject 를 MCP 툴로 호출하게 한다.
"""

from .server import main

__all__ = ["main"]

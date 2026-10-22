"""MCP 서버 실행 진입점: uv run python -m eval_agent.mcp_server

stdio 방식: Claude Desktop/Claude Code가 이 프로세스를 직접 실행하고, 표준 입출력으로 JSON 메시지를 주고받는다.
- 네트워크 포트를 열지 않으므로 내 PC 밖에서 접속할 수 없다. (별도 인증이 필요 없는 이유)
- 주의: stdout은 프로토콜 전용이다. 이 경로에서 print()를 하면 메시지가 깨져 연결이 끊긴다.
  로그는 stderr로만 남긴다.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from eval_agent.config import get_settings
from eval_agent.mcp_server.server import create_server


def main() -> None:
    session_factory = sessionmaker(create_engine(get_settings().database_url))
    create_server(session_factory).run(transport="stdio")


if __name__ == "__main__":
    main()

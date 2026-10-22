"""MCP 서버: 3단계 도구 4개를 Claude Desktop / Claude Code가 직접 쓸 수 있게 노출한다.

에이전트(4~5단계)와의 차이
- 에이전트: 우리가 LLM을 호출하고, LLM이 고른 도구를 우리가 실행한다. (API 비용은 우리 쪽에서 발생)
- MCP 서버: LLM은 Claude Desktop/Code 쪽에 있고, 우리는 '도구 목록과 실행'만 제공한다.
  LLM 호출이 없으므로 이 서버에는 Claude API 키도, 반복 한도도, 답변 규칙 프롬프트도 필요 없다.
  (같은 도구를 쓰지만 '두뇌'가 어디에 있는지가 다르다. 도구 설명은 descriptions.py로 공유한다.)

Spring 비교: 같은 서비스 로직을 REST 컨트롤러(5단계)와 다른 프로토콜의 어댑터(이 파일)로 각각 노출하는 것과 같다.
도구 로직(3단계)은 건드리지 않고, 얇은 어댑터만 더한다.

SDK 메모: mcp 2.x에서는 FastMCP가 MCPServer로 이름이 바뀌었다. (mcp 1.x 코드의 FastMCP와 사용법은 거의 같다)
"""

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session

from eval_agent.tools import (
    compare_years,
    get_grade_distribution,
    get_org_summary,
    search_policy_docs,
)
from eval_agent.tools.descriptions import TOOL_DESCRIPTIONS

SessionFactory = Callable[[], Session]

INSTRUCTIONS = (
    "평가 결과 분석 도구 모음입니다. 모든 데이터는 가상의 더미 데이터이며, 도구는 읽기 전용이고 개인 이름 없이 "
    "집계만 돌려줍니다. 숫자는 도구 결과에 있는 값만 사용하고, 결과의 unit 필드('인원' 또는 '평가 건수')를 "
    "구분해서 말하세요. 데이터가 없으면 error 응답의 안내(조회 가능한 연도·조직)를 그대로 전달하세요."
)


def create_server(session_factory: SessionFactory) -> MCPServer:
    """session_factory를 밖에서 받는다. 테스트에서는 메모리 DB를, 실행할 때는 PostgreSQL을 꽂는다."""
    server = MCPServer("eval-agent", instructions=INSTRUCTIONS)

    # 결과는 dict 그대로 돌려준다. MCP가 JSON(structured content)으로 직렬화해서 클라이언트에 전달한다.
    # 데이터 없음 같은 '정상적인 부재'는 에이전트와 똑같이 {"error": ...} 결과로 알려서 LLM이 스스로 복구하게 한다.
    @server.tool(name="get_grade_distribution", description=TOOL_DESCRIPTIONS["get_grade_distribution"])
    def _get_grade_distribution(
        year: int, org_name: str | None = None, eval_type: str | None = None
    ) -> dict[str, Any]:
        with session_factory() as session:
            return get_grade_distribution(session, year, org_name, eval_type)

    @server.tool(name="compare_years", description=TOOL_DESCRIPTIONS["compare_years"])
    def _compare_years(org_name: str, year_from: int, year_to: int) -> dict[str, Any]:
        with session_factory() as session:
            return compare_years(session, org_name, year_from, year_to)

    @server.tool(name="get_org_summary", description=TOOL_DESCRIPTIONS["get_org_summary"])
    def _get_org_summary(year: int, org_name: str) -> dict[str, Any]:
        with session_factory() as session:
            return get_org_summary(session, year, org_name)

    @server.tool(name="search_policy_docs", description=TOOL_DESCRIPTIONS["search_policy_docs"])
    def _search_policy_docs(query: str) -> dict[str, Any]:
        return search_policy_docs(query)

    return server

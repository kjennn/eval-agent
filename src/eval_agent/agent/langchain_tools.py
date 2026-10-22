"""3단계에서 만든 순수 함수 도구를 LangChain 도구로 감싼다.

왜 감싸는가
- LLM은 파이썬 함수를 직접 부르지 못한다. LLM에게는 "도구 이름 + 설명 + 파라미터 스키마"만 보이고,
  LLM이 도구 호출을 요청하면 우리 코드가 대신 실행해서 결과를 돌려준다.
- 이 파일이 그 '이름 + 설명 + 스키마'를 만든다. 스키마는 함수 시그니처(타입힌트)에서 자동으로 만들어지고,
  설명은 tools/descriptions.py의 문구를 쓴다(MCP 서버와 공유). (Java로 치면 OpenAPI 스펙을 코드에서 뽑는 것과 비슷)
- 3단계 도구는 DB 세션을 인자로 받으므로, 여기서 호출할 때마다 세션을 열고 닫아 준다.

새 문법 메모
- `@tool("이름")`: 데코레이터. 함수를 LangChain 도구 객체로 바꿔 준다. (Java의 애노테이션과 비슷하지만
  애노테이션은 표시만 하고, 데코레이터는 함수를 받아서 '다른 객체로 바꿔 돌려준다'는 점이 다르다)
- `Callable[[], Session]`: "인자 없이 호출하면 Session을 돌려주는 것"이라는 타입힌트. sessionmaker가 이에 해당한다.
"""

import json
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, tool
from sqlalchemy.orm import Session

from eval_agent.tools import (
    compare_years,
    get_grade_distribution,
    get_org_summary,
    search_policy_docs,
)
from eval_agent.tools.descriptions import TOOL_DESCRIPTIONS

SessionFactory = Callable[[], Session]


def _dump(result: dict[str, Any]) -> str:
    # LLM에게는 텍스트로 전달된다. ensure_ascii=False: 한글을 \uXXXX로 깨뜨리지 않는다.
    return json.dumps(result, ensure_ascii=False)


def build_tools(session_factory: SessionFactory) -> list[BaseTool]:
    @tool("get_grade_distribution", description=TOOL_DESCRIPTIONS["get_grade_distribution"])
    def _get_grade_distribution(
        year: int, org_name: str | None = None, eval_type: str | None = None
    ) -> str:
        with session_factory() as session:
            return _dump(get_grade_distribution(session, year, org_name, eval_type))

    @tool("compare_years", description=TOOL_DESCRIPTIONS["compare_years"])
    def _compare_years(org_name: str, year_from: int, year_to: int) -> str:
        with session_factory() as session:
            return _dump(compare_years(session, org_name, year_from, year_to))

    @tool("get_org_summary", description=TOOL_DESCRIPTIONS["get_org_summary"])
    def _get_org_summary(year: int, org_name: str) -> str:
        with session_factory() as session:
            return _dump(get_org_summary(session, year, org_name))

    @tool("search_policy_docs", description=TOOL_DESCRIPTIONS["search_policy_docs"])
    def _search_policy_docs(query: str) -> str:
        return _dump(search_policy_docs(query))

    return [_get_grade_distribution, _compare_years, _get_org_summary, _search_policy_docs]

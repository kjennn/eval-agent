"""3단계에서 만든 순수 함수 도구를 LangChain 도구로 감싼다.

왜 감싸는가
- LLM은 파이썬 함수를 직접 부르지 못한다. LLM에게는 "도구 이름 + 설명 + 파라미터 스키마"만 보이고,
  LLM이 도구 호출을 요청하면 우리 코드가 대신 실행해서 결과를 돌려준다.
- 이 파일이 그 '이름 + 설명 + 스키마'를 만든다. 스키마는 함수 시그니처(타입힌트)에서 자동으로 만들어지고,
  **독스트링이 곧 LLM에게 보이는 도구 설명**이다. (Java로 치면 OpenAPI 스펙을 코드에서 뽑는 것과 비슷)
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

SessionFactory = Callable[[], Session]


def _dump(result: dict[str, Any]) -> str:
    # LLM에게는 텍스트로 전달된다. ensure_ascii=False: 한글을 \uXXXX로 깨뜨리지 않는다.
    return json.dumps(result, ensure_ascii=False)


def build_tools(session_factory: SessionFactory) -> list[BaseTool]:
    @tool("get_grade_distribution")
    def _get_grade_distribution(
        year: int, org_name: str | None = None, eval_type: str | None = None
    ) -> str:
        """등급(S/A/B/C/D)별 인원(건수)과 비율을 조회한다.

        - year: 평가 연도 (예: 2025)
        - org_name: 본부명 또는 팀명. 생략하면 회사 전체. 생략하거나 본부를 지정하면 하위 조직(본부별/팀별)
          분포가 breakdown에 함께 나오므로, 여러 본부를 비교할 때는 org_name을 생략하고 한 번만 호출한다.
        - eval_type: '역량', '성과', '다면' 중 하나. 생략하면 세 유형을 합산하며, 이때 결과의 unit은
          '인원'이 아니라 '평가 건수'다.
        """
        with session_factory() as session:
            return _dump(get_grade_distribution(session, year, org_name, eval_type))

    @tool("compare_years")
    def _compare_years(org_name: str, year_from: int, year_to: int) -> str:
        """한 조직(본부 또는 팀)의 두 연도 등급 분포를 비교한다.

        등급별로 두 연도의 비율과 변화량(diff_pct_point, 단위 %p)을 돌려준다.
        - org_name: 본부명 또는 팀명 (필수)
        - year_from: 비교 기준 연도, year_to: 비교 대상 연도
        """
        with session_factory() as session:
            return _dump(compare_years(session, org_name, year_from, year_to))

    @tool("get_org_summary")
    def _get_org_summary(year: int, org_name: str) -> str:
        """조직(본부 또는 팀)의 평가 대상 인원수, 전체 평균 점수, 평가유형(역량/성과/다면)별 평균 점수를 조회한다.

        - year: 평가 연도, org_name: 본부명 또는 팀명 (둘 다 필수)
        """
        with session_factory() as session:
            return _dump(get_org_summary(session, year, org_name))

    @tool("search_policy_docs")
    def _search_policy_docs(query: str) -> str:
        """평가 기준 문서(등급 배분 가이드, 본부별 예외 규정, 평가 유형과 반영 비율, 보정·이의신청)에서
        질문과 관련된 문단을 키워드로 검색한다.

        - query: 핵심 키워드를 공백으로 구분해 넣는다. 조사를 빼고 명사 위주로 쓴다. (예: '영업본부 B등급 허용 상한')
        기준 수치(허용 비율, 예외 규정 등)를 말하기 전에 반드시 이 도구로 확인한다.
        """
        return _dump(search_policy_docs(query))

    return [_get_grade_distribution, _compare_years, _get_org_summary, _search_policy_docs]

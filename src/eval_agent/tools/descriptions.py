"""도구 설명 (LLM에게 보이는 문구). 에이전트(LangChain)와 MCP 서버가 같은 문구를 공유한다.

왜 한 곳에 모으는가
- 도구 설명은 LLM이 '어떤 도구를 언제, 어떤 값으로 부를지' 판단하는 유일한 단서다.
  에이전트와 MCP 서버에 설명을 따로 적어 두면 한쪽만 고쳐서 두 곳의 동작이 어긋날 수 있다.
- Spring으로 치면 같은 안내 문구를 컨트롤러 두 곳에 복사하지 않고 상수로 빼 두는 것과 같다.
"""

from eval_agent.tools.sql_query import MAX_ROWS, schema_text

TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_grade_distribution": """등급(S/A/B/C/D)별 인원(건수)과 비율을 조회한다.

- year: 평가 연도 (예: 2025)
- org_name: 본부명 또는 팀명. 생략하면 회사 전체. 생략하거나 본부를 지정하면 하위 조직(본부별/팀별)
  분포가 breakdown에 함께 나오므로, 여러 본부를 비교할 때는 org_name을 생략하고 한 번만 호출한다.
- eval_type: '역량', '성과', '다면' 중 하나. 생략하면 세 유형을 합산하며, 이때 결과의 unit은
  '인원'이 아니라 '평가 건수'다.""",
    "compare_years": """한 조직(본부 또는 팀)의 두 연도 등급 분포를 비교한다.

등급별로 두 연도의 비율과 변화량(diff_pct_point, 단위 %p)을 돌려준다.
- org_name: 본부명 또는 팀명 (필수)
- year_from: 비교 기준 연도, year_to: 비교 대상 연도""",
    "get_org_summary": """조직(본부 또는 팀)의 평가 대상 인원수, 전체 평균 점수, 평가유형(역량/성과/다면)별 평균 점수를 조회한다.

- year: 평가 연도, org_name: 본부명 또는 팀명 (둘 다 필수)""",
    "search_policy_docs": """평가 기준 문서(등급 배분 가이드, 본부별 예외 규정, 평가 유형과 반영 비율, 보정·이의신청)에서
질문과 의미가 가까운 문단을 검색한다. (임베딩 검색, 쓸 수 없으면 키워드 검색으로 대체. 결과의 method 참고)

- query: 찾고 싶은 내용을 짧은 문장이나 핵심 명사로 넣는다. (예: '영업본부 B등급 허용 상한')
기준 수치(허용 비율, 예외 규정 등)를 말하기 전에 반드시 이 도구로 확인한다.""",
    "run_sql": f"""평가 DB에 읽기 전용 SELECT 문을 직접 실행한다 (Text-to-SQL).

다른 도구로 답할 수 없는 질문(예: 직급별 평균 점수, 팀별 D등급 인원 순위)에만 쓴다.
등급 분포·연도 비교·조직 요약은 전용 도구를 먼저 쓴다.

- sql: SELECT 문 하나. 아래 테이블과 컬럼만 쓸 수 있다. 결과는 최대 {MAX_ROWS}행이다.
- 직원 이름은 조회할 수 없다. 개인별 행 대신 GROUP BY로 집계해서 조회한다.
- 오류가 나면 message를 읽고 SQL을 고쳐 한 번 더 시도할 수 있다.

[스키마]
{schema_text()}
- 본부별 집계: employee.org_unit_id(팀) → org_unit.parent_id(본부) 순서로 조인한다.
- 연도 조건: evaluation_result.cycle_id = evaluation_cycle.id 로 조인해 evaluation_cycle.year로 거른다.""",
}

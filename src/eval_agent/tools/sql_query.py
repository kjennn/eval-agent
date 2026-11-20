"""도구 5: Text-to-SQL. LLM이 직접 쓴 SELECT 문을 검사한 뒤 읽기 전용으로 실행한다.

왜 따로 두는가
- 도구 1~3은 정해진 파라미터만 받는다(evaluation.py의 설계 원칙). 안전하지만 질문 모양이 조금만 달라도
  ("직급별 평균 점수", "팀별 D등급 인원 상위 3개") 답할 도구가 없다.
- 이 도구는 그 빈틈을 메우는 '보조' 도구다. LLM에게 스키마를 알려 주고 SQL을 직접 쓰게 한다.
  대신 자유 SQL은 위험하므로, 실행 전에 SQL을 파싱해서 검사하고 실행도 읽기 전용으로 제한한다.

안전장치 (겹겹이 둔다. 하나가 뚫려도 다음 단계에서 막히도록)
1. 파싱 검사(sqlglot): 문장은 하나만, SELECT(UNION 포함)만 허용. INSERT/UPDATE/DELETE/DDL은 거절.
2. 테이블 화이트리스트: 평가 관련 테이블 4개만. 그 밖의 테이블(시스템 카탈로그 등)은 거절.
3. 개인정보 차단: employee.name 컬럼과, employee가 들어간 쿼리의 SELECT *를 거절.
   (기존 도구와 같은 원칙: 개인 이름은 절대 내보내지 않는다)
4. 위험 함수 차단: pg_sleep, pg_read_file 같은 pg_* 함수와 dblink 등.
5. 실행 제한: 결과 행 수 상한(MAX_ROWS), PostgreSQL에서는 READ ONLY 트랜잭션 + statement_timeout.
6. 실행 후 항상 rollback. 어떤 경우에도 커밋하지 않는다.

Java 비교: JdbcTemplate에 사용자 SQL을 그대로 넘기는 대신, 파서로 AST를 만들어 검사한 뒤
읽기 전용 커넥션(@Transactional(readOnly = true))으로 실행하는 것과 같다.

한계
- 개인별 행(employee_id, score)은 막지 않는다. 이름은 안 나가지만 '집계만'이라는 원칙보다는 느슨하다.
  집계만 강제하려면 GROUP BY/집계함수 여부를 검사해야 하는데, 오탐이 많아 여기서는 프롬프트 규칙으로 둔다.
- 검사는 SQL 문법 수준이다. 실제 운영이라면 DB 계정 자체를 읽기 전용 + 뷰만 보이게 만드는 것이 근본 대책이다.
"""

from typing import Any

import sqlglot
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlglot import exp

ToolResult = dict[str, Any]

MAX_ROWS = 50
STATEMENT_TIMEOUT_MS = 3000

# LLM이 볼 수 있는 테이블과 컬럼. 이 목록이 곧 도구 설명의 스키마 안내가 된다.
ALLOWED_TABLES: dict[str, dict[str, str]] = {
    "org_unit": {
        "id": "PK",
        "name": "조직명 (예: 영업본부, 국내영업팀)",
        "parent_id": "상위 조직 id. NULL이면 본부, 값이 있으면 그 본부 소속 팀",
    },
    "employee": {
        "id": "PK",
        "org_unit_id": "소속 팀 id (본부가 아니라 팀)",
        "job_level": "직급",
        # name 컬럼은 존재하지만 개인정보라 조회 불가. 일부러 안내하지 않는다.
    },
    "evaluation_cycle": {
        "id": "PK",
        "year": "평가 연도 (예: 2025)",
        "name": "평가 주기 이름",
    },
    "evaluation_result": {
        "id": "PK",
        "cycle_id": "evaluation_cycle.id",
        "employee_id": "employee.id",
        "eval_type": "'역량', '성과', '다면' 중 하나",
        "score": "점수 (소수 2자리)",
        "grade": "'S', 'A', 'B', 'C', 'D' 중 하나",
    },
}

BLOCKED_COLUMNS = {("employee", "name")}
BLOCKED_FUNCTION_PREFIXES = ("pg_", "dblink", "lo_", "current_setting", "set_config")


def schema_text() -> str:
    """도구 설명에 넣을 스키마 안내 문자열."""
    lines = []
    for table, cols in ALLOWED_TABLES.items():
        col_text = ", ".join(f"{c}({d})" for c, d in cols.items())
        lines.append(f"- {table}: {col_text}")
    return "\n".join(lines)


def _error(code: str, message: str) -> ToolResult:
    return {"error": code, "message": message}


def _validate(sql: str) -> ToolResult | None:
    """문제가 있으면 에러 dict, 통과하면 None."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        return _error("sql_parse_error", f"SQL을 해석할 수 없습니다: {str(e)[:200]}")

    if len(statements) != 1:
        return _error("rejected", "SQL은 SELECT 문 하나만 보낼 수 있습니다.")
    tree = statements[0]

    # exp.Query: SELECT, UNION/INTERSECT/EXCEPT를 아우르는 부모 타입
    if not isinstance(tree, exp.Query):
        return _error("rejected", "SELECT 문만 실행할 수 있습니다.")
    # SELECT 안에 숨긴 쓰기 구문(예: CTE 안의 DELETE ... RETURNING)도 거절한다
    if any(tree.find_all(exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter, exp.Command)):
        return _error("rejected", "데이터를 바꾸는 구문은 실행할 수 없습니다.")
    if tree.find(exp.Into):  # SELECT ... INTO 새테이블
        return _error("rejected", "SELECT INTO는 실행할 수 없습니다.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    alias_to_table: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        if table.db or name not in ALLOWED_TABLES:  # 스키마 지정(pg_catalog.x 등)도 거절
            return _error(
                "table_not_allowed",
                f"'{table.sql()}' 테이블은 조회할 수 없습니다. 허용 테이블: {list(ALLOWED_TABLES)}",
            )
        alias_to_table[(table.alias or name).lower()] = name

    uses_employee = "employee" in alias_to_table.values()
    for col in tree.find_all(exp.Column):
        owner = alias_to_table.get(col.table.lower()) if col.table else None
        if col.name.lower() == "name" and (owner == "employee" or (not col.table and uses_employee)):
            # 한정자 없는 name은 어느 테이블 것인지 모호하므로, employee가 있으면 막는다
            return _error("column_not_allowed", "직원 이름(employee.name)은 조회할 수 없습니다. org_unit.name처럼 테이블을 명시하세요.")
        if isinstance(col.this, exp.Star) and owner == "employee":
            return _error("column_not_allowed", "employee.* 는 쓸 수 없습니다. 필요한 컬럼만 고르세요.")
    if uses_employee and any(isinstance(s, exp.Star) for s in tree.find_all(exp.Star) if not isinstance(s.parent, exp.Count)):
        return _error("column_not_allowed", "employee를 조회할 때는 SELECT * 를 쓸 수 없습니다. 필요한 컬럼만 고르세요.")

    for func in tree.find_all(exp.Func):
        fname = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if fname.startswith(BLOCKED_FUNCTION_PREFIXES):
            return _error("function_not_allowed", f"'{fname}' 함수는 쓸 수 없습니다.")
    return None


def run_sql(session: Session, sql: str) -> ToolResult:
    """검사를 통과한 SELECT 문을 읽기 전용으로 실행하고, 최대 MAX_ROWS행을 돌려준다."""
    sql = sql.strip().rstrip(";")
    if err := _validate(sql):
        return err

    # 원래 쿼리를 서브쿼리로 감싸 행 수를 제한한다. 한 행 더 가져와서 잘렸는지 판단한다.
    limited = f"SELECT * FROM ({sql}) AS q LIMIT {MAX_ROWS + 1}"
    try:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        result = session.execute(text(limited))
        columns = list(result.keys())
        rows = [list(r) for r in result.fetchall()]
    except SQLAlchemyError as e:
        # DB 오류 메시지를 돌려주면 LLM이 읽고 SQL을 고쳐서 다시 시도할 수 있다
        detail = str(getattr(e, "orig", e)).splitlines()[0][:300]
        return _error("sql_error", f"SQL 실행 오류: {detail}")
    finally:
        session.rollback()

    truncated = len(rows) > MAX_ROWS
    return {
        "sql": sql,
        "columns": columns,
        "rows": [[_jsonable(v) for v in r] for r in rows[:MAX_ROWS]],
        "row_count": min(len(rows), MAX_ROWS),
        "truncated": truncated,
    }


def _jsonable(value: Any) -> Any:
    # PostgreSQL의 AVG 등은 Decimal을 돌려준다. JSON으로 바꿀 수 있게 float로 바꾼다.
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)

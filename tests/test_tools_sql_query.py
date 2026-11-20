import json

import pytest

from eval_agent.seed_data import build_dataset
from eval_agent.tools import get_grade_distribution, get_org_summary, run_sql
from eval_agent.tools.sql_query import MAX_ROWS

# ---------- 정상 실행: 전용 도구와 같은 숫자가 나와야 한다 ----------


def test_전용_도구와_같은_등급_인원이_나온다(db):
    sql = """
        SELECT r.grade, COUNT(*) AS cnt
        FROM evaluation_result r
        JOIN evaluation_cycle c ON c.id = r.cycle_id
        JOIN employee e ON e.id = r.employee_id
        JOIN org_unit t ON t.id = e.org_unit_id
        JOIN org_unit h ON h.id = t.parent_id
        WHERE c.year = 2025 AND r.eval_type = '성과' AND h.name = '영업본부'
        GROUP BY r.grade
    """
    r = run_sql(db, sql)
    assert "error" not in r
    assert r["columns"] == ["grade", "cnt"]
    by_grade = dict(r["rows"])
    expected = get_grade_distribution(db, 2025, "영업본부", "성과")
    assert by_grade["B"] == next(d["count"] for d in expected["distribution"] if d["grade"] == "B")


def test_직급별_평균처럼_전용_도구에_없는_질문도_답한다(db):
    r = run_sql(db, """
        SELECT e.job_level, ROUND(AVG(r.score), 2) AS avg_score
        FROM evaluation_result r JOIN employee e ON e.id = r.employee_id
        GROUP BY e.job_level ORDER BY e.job_level
    """)
    assert r["row_count"] == 5  # 사원~부장
    assert all(isinstance(v, float) for _, v in r["rows"])


def test_CTE와_끝의_세미콜론도_허용한다(db):
    r = run_sql(db, "WITH y AS (SELECT year FROM evaluation_cycle) SELECT COUNT(*) FROM y;")
    assert r["rows"] == [[2]]


def test_결과는_MAX_ROWS행에서_잘린다(db):
    r = run_sql(db, "SELECT id, score FROM evaluation_result")
    assert r["row_count"] == MAX_ROWS and r["truncated"] is True


def test_결과는_JSON으로_바꿀_수_있다(db):
    r = run_sql(db, "SELECT year, name FROM evaluation_cycle ORDER BY year")
    assert json.loads(json.dumps(r, ensure_ascii=False))["rows"][0][0] == 2024


# ---------- 거절: 실행 전에 막혀야 한다 ----------


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM evaluation_result",
        "UPDATE evaluation_result SET grade = 'S'",
        "DROP TABLE employee",
        "INSERT INTO org_unit (name) VALUES ('x')",
        "SELECT 1; DELETE FROM evaluation_result",
        "WITH d AS (DELETE FROM evaluation_result RETURNING id) SELECT * FROM d",
        "SELECT * INTO backup FROM evaluation_result",
    ],
)
def test_쓰기와_여러_문장은_거절한다(db, sql):
    assert run_sql(db, sql)["error"] == "rejected"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM pg_catalog.pg_user",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM sqlite_master",
    ],
)
def test_허용되지_않은_테이블은_거절한다(db, sql):
    assert run_sql(db, sql)["error"] == "table_not_allowed"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM employee",
        "SELECT e.name FROM employee e",
        "SELECT * FROM employee",
        "SELECT e.* FROM employee e",
        "SELECT r.score, name FROM evaluation_result r JOIN employee e ON e.id = r.employee_id",
    ],
)
def test_직원_이름은_어떤_형태로도_조회할_수_없다(db, sql):
    assert run_sql(db, sql)["error"] == "column_not_allowed"


def test_조직명은_테이블을_명시하면_조회된다(db):
    r = run_sql(db, """
        SELECT t.name, COUNT(*) FROM employee e JOIN org_unit t ON t.id = e.org_unit_id
        GROUP BY t.name
    """)
    assert "error" not in r
    names = {e.name for e in build_dataset().employees}
    assert not any(row[0] in names for row in r["rows"])


def test_COUNT_별표는_employee에서도_허용한다(db):
    assert run_sql(db, "SELECT COUNT(*) FROM employee")["rows"] == [[250]]


def test_위험_함수는_거절한다(db):
    assert run_sql(db, "SELECT pg_sleep(10)")["error"] == "function_not_allowed"


def test_DB_오류는_예외가_아니라_안내로_돌아온다(db):
    r = run_sql(db, "SELECT no_such_column FROM evaluation_result")
    assert r["error"] == "sql_error"
    # 실패 뒤에도 세션을 계속 쓸 수 있어야 한다 (rollback 확인)
    assert get_org_summary(db, 2025, "개발본부")["org_name"] == "개발본부"


def test_파싱할_수_없는_SQL은_안내로_돌아온다(db):
    assert run_sql(db, "SELEC FROM")["error"] in {"sql_parse_error", "rejected"}

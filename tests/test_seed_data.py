from collections import Counter

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from eval_agent.models import Base, Employee, EvaluationResult, OrgUnit
from eval_agent.seed_data import (
    GRADE_BANDS,
    ORG_STRUCTURE,
    allocate_grades,
    build_dataset,
    insert_dataset,
)


def _b_ratio(data, hq: str, year: int) -> float:
    grades = [
        r.grade
        for r in data.results
        if r.year == year and data.employees[r.employee_index].hq == hq
    ]
    return grades.count("B") / len(grades)


def test_allocate_grades는_인원수와_목표비율에_맞게_나눈다():
    grades = allocate_grades(60, {"S": 5, "A": 18, "B": 52, "C": 20, "D": 5})
    assert len(grades) == 60
    assert Counter(grades) == {"S": 3, "A": 11, "B": 31, "C": 12, "D": 3}


def test_같은_seed는_같은_데이터를_만든다():
    a, b = build_dataset(seed=1), build_dataset(seed=1)
    assert a.employees == b.employees
    assert a.results == b.results


def test_데이터_규모():
    data = build_dataset()
    total = sum(info["headcount"] for info in ORG_STRUCTURE.values())
    assert len(data.employees) == total
    # 직원 x 2개 연도 x 3개 평가유형
    assert len(data.results) == total * 2 * 3


def test_점수는_등급_구간_안에_있다():
    for r in build_dataset().results:
        low, high = GRADE_BANDS[r.grade]
        assert low <= r.score <= high, (r.grade, r.score)


def test_영업본부_2025_B등급이_다른_본부보다_뚜렷하게_높다():
    data = build_dataset()
    sales = _b_ratio(data, "영업본부", 2025)
    others = [_b_ratio(data, hq, 2025) for hq in ORG_STRUCTURE if hq != "영업본부"]
    assert sales > 0.65  # 기준 문서의 영업본부 허용 상한(65%)을 넘는다
    assert all(sales - o >= 0.10 for o in others)


def test_시드가_DB에_들어간다_sqlite_메모리():
    # 실제 PostgreSQL 대신 메모리 SQLite로 'ORM 매핑과 삽입 순서'만 빠르게 검증한다.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        counts = insert_dataset(session, build_dataset())
        session.commit()

        assert counts["org_unit"] == 4 + 12
        assert session.scalar(select(func.count()).select_from(Employee)) == counts["employee"]
        assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 1500
        # 본부는 parent_id가 없고, 팀은 모두 본부를 부모로 가진다
        assert session.scalar(
            select(func.count()).select_from(OrgUnit).where(OrgUnit.parent_id.is_(None))
        ) == 4

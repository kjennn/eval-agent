"""평가 결과 조회 도구 3개 (읽기 전용).

설계 원칙
- 자유 SQL을 받지 않는다. 정해진 파라미터(연도, 조직명, 평가유형)만 받는다.
- DB 세션을 첫 인자로 받는다. 전역 상태가 없어서 테스트에서 가짜 DB를 쉽게 꽂을 수 있다.
  (Spring에서 Repository를 생성자로 주입받아 테스트하는 것과 같은 발상)
- 결과는 JSON으로 바꿀 수 있는 dict만 돌려준다. 개인 이름은 절대 포함하지 않고 집계만 낸다.
- 조회가 안 될 때는 예외를 던지지 않고 {"error": ...} dict를 돌려준다.
  나중에 LLM이 이 결과를 읽고 "데이터가 없습니다"라고 스스로 답할 수 있게 하기 위해서다.

새 문법 메모
- `dict[str, Any]`: "키는 문자열, 값은 아무 타입"이라는 타입힌트 (Java의 Map<String, Object>)
- `str | None`: 문자열 또는 None. 기본값이 `= None`이면 생략 가능한 파라미터가 된다.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eval_agent.models import (
    EVAL_TYPES,
    GRADES,
    Employee,
    EvaluationCycle,
    EvaluationResult,
    OrgUnit,
)

ToolResult = dict[str, Any]


# ---------- 공통 조각 (도구 3개가 함께 쓴다) ----------


def _available_years(session: Session) -> list[int]:
    return list(session.scalars(select(EvaluationCycle.year).order_by(EvaluationCycle.year)))


def _error(code: str, message: str, **extra: Any) -> ToolResult:
    # **extra: 이름 붙은 인자를 모두 dict로 받는다 (가변 키워드 인자). 호출: _error("x", "msg", available_years=[1])
    return {"error": code, "message": message, **extra}


def _check_year(session: Session, year: int) -> ToolResult | None:
    years = _available_years(session)
    if year not in years:
        return _error(
            "no_data",
            f"{year}년 평가 데이터가 없습니다. 조회 가능한 연도: {years}",
            available_years=years,
        )
    return None


def _check_eval_type(eval_type: str | None) -> ToolResult | None:
    if eval_type is not None and eval_type not in EVAL_TYPES:
        return _error(
            "invalid_eval_type",
            f"평가유형은 {list(EVAL_TYPES)} 중 하나여야 합니다.",
            allowed=list(EVAL_TYPES),
        )
    return None


def _headquarters(session: Session) -> list[OrgUnit]:
    stmt = select(OrgUnit).where(OrgUnit.parent_id.is_(None)).order_by(OrgUnit.id)
    return list(session.scalars(stmt))


def _children(session: Session, unit: OrgUnit) -> list[OrgUnit]:
    stmt = select(OrgUnit).where(OrgUnit.parent_id == unit.id).order_by(OrgUnit.id)
    return list(session.scalars(stmt))


def _find_org(session: Session, org_name: str) -> OrgUnit | ToolResult:
    unit = session.scalar(select(OrgUnit).where(OrgUnit.name == org_name))
    if unit is None:
        names = [hq.name for hq in _headquarters(session)]
        return _error(
            "org_not_found",
            f"'{org_name}' 조직을 찾을 수 없습니다. 본부 목록: {names}",
            available_headquarters=names,
        )
    return unit


def _team_ids(session: Session, unit: OrgUnit) -> list[int]:
    """조직이 본부면 소속 팀들의 id, 팀이면 자기 id. (직원은 팀에 소속되어 있다)"""
    if unit.parent_id is None:
        return [t.id for t in _children(session, unit)]
    return [unit.id]


def _distribution(
    session: Session, year: int, team_ids: list[int] | None, eval_type: str | None
) -> ToolResult:
    """등급별 건수·비율. team_ids가 None이면 회사 전체."""
    stmt = (
        select(EvaluationResult.grade, func.count())
        .join(EvaluationCycle, EvaluationCycle.id == EvaluationResult.cycle_id)
        .where(EvaluationCycle.year == year)
        .group_by(EvaluationResult.grade)
    )
    if eval_type is not None:
        stmt = stmt.where(EvaluationResult.eval_type == eval_type)
    if team_ids is not None:
        stmt = stmt.join(Employee, Employee.id == EvaluationResult.employee_id).where(
            Employee.org_unit_id.in_(team_ids)
        )
    counts = dict(session.execute(stmt).all())  # {"B": 41, "A": 6, ...}
    total = sum(counts.values())
    return {
        "total": total,
        "distribution": [
            {
                "grade": g,
                "count": counts.get(g, 0),
                "ratio_pct": round(counts.get(g, 0) / total * 100, 1) if total else 0.0,
            }
            for g in GRADES  # 인원이 0인 등급도 빠뜨리지 않고 S~D 전부 내보낸다
        ],
    }


def _unit_label(eval_type: str | None) -> str:
    # 평가유형을 지정하지 않으면 한 직원이 유형별로 여러 건을 가지므로 '인원'이 아니라 '건수'다
    return "인원" if eval_type else "평가 건수(직원 x 평가유형)"


# ---------- 도구 1 ----------


def get_grade_distribution(
    session: Session,
    year: int,
    org_name: str | None = None,
    eval_type: str | None = None,
) -> ToolResult:
    """등급(S/A/B/C/D)별 인원과 비율을 돌려준다.

    org_name을 생략하면 회사 전체, 본부명이면 그 본부, 팀명이면 그 팀이다.
    조직 하위 단위가 있으면(회사→본부, 본부→팀) breakdown에 단위별 분포도 함께 준다.
    eval_type(역량/성과/다면)을 생략하면 세 유형을 합산한다.
    """
    if err := _check_year(session, year):  # := 는 '대입하고 바로 검사'하는 문법 (walrus 연산자)
        return err
    if err := _check_eval_type(eval_type):
        return err

    if org_name is None:
        scope_name, team_ids = "전체", None
        children = _headquarters(session)
    else:
        unit = _find_org(session, org_name)
        if isinstance(unit, dict):  # 조회 실패 시 _find_org가 에러 dict를 돌려줬다
            return unit
        scope_name, team_ids = unit.name, _team_ids(session, unit)
        children = _children(session, unit) if unit.parent_id is None else []

    result: ToolResult = {
        "year": year,
        "org_name": scope_name,
        "eval_type": eval_type or "전체",
        "unit": _unit_label(eval_type),
        **_distribution(session, year, team_ids, eval_type),
    }
    if children:
        result["breakdown"] = [
            {"org_name": c.name, **_distribution(session, year, _team_ids(session, c), eval_type)}
            for c in children
        ]
    return result


# ---------- 도구 2 ----------


def _diff_pct_point(count_from: int, total_from: int, count_to: int, total_to: int) -> float:
    ratio_from = count_from / total_from * 100 if total_from else 0.0
    ratio_to = count_to / total_to * 100 if total_to else 0.0
    return round(ratio_to - ratio_from, 1)


def compare_years(session: Session, org_name: str, year_from: int, year_to: int) -> ToolResult:
    """한 조직의 두 연도 등급 분포를 나란히 놓고, 등급별 비율 변화(%p)를 계산한다."""
    for year in (year_from, year_to):
        if err := _check_year(session, year):
            return err
    unit = _find_org(session, org_name)
    if isinstance(unit, dict):
        return unit

    team_ids = _team_ids(session, unit)
    before = _distribution(session, year_from, team_ids, None)
    after = _distribution(session, year_to, team_ids, None)
    changes = [
        {
            "grade": b["grade"],
            "from_ratio_pct": b["ratio_pct"],
            "to_ratio_pct": a["ratio_pct"],
            # 비율끼리의 차이는 %가 아니라 %p(퍼센트포인트)다.
            # 반올림된 비율끼리 빼면 오차가 생기므로(51.7, 68.3 → 16.6), 건수에서 다시 계산한다(16.67 → 16.7).
            "diff_pct_point": _diff_pct_point(b["count"], before["total"], a["count"], after["total"]),
        }
        for b, a in zip(before["distribution"], after["distribution"])
    ]
    return {
        "org_name": unit.name,
        "year_from": year_from,
        "year_to": year_to,
        "unit": _unit_label(None),
        "from": before,
        "to": after,
        "changes": changes,
    }


# ---------- 도구 3 ----------


def get_org_summary(session: Session, year: int, org_name: str) -> ToolResult:
    """조직의 평가 대상 인원수, 전체 평균 점수, 평가유형별 평균 점수."""
    if err := _check_year(session, year):
        return err
    unit = _find_org(session, org_name)
    if isinstance(unit, dict):
        return unit

    stmt = (
        select(
            EvaluationResult.eval_type,
            func.avg(EvaluationResult.score),
            func.count(),
            func.count(func.distinct(EvaluationResult.employee_id)),
        )
        .join(EvaluationCycle, EvaluationCycle.id == EvaluationResult.cycle_id)
        .join(Employee, Employee.id == EvaluationResult.employee_id)
        .where(EvaluationCycle.year == year, Employee.org_unit_id.in_(_team_ids(session, unit)))
        .group_by(EvaluationResult.eval_type)
    )
    rows = session.execute(stmt).all()
    if not rows:
        return _error("no_data", f"{year}년 {unit.name}의 평가 결과가 없습니다.")

    by_type = {eval_type: float(avg) for eval_type, avg, _, _ in rows}
    total_results = sum(n for _, _, n, _ in rows)
    overall = sum(float(avg) * n for _, avg, n, _ in rows) / total_results  # 건수 가중 평균
    return {
        "org_name": unit.name,
        "year": year,
        "headcount": max(h for _, _, _, h in rows),  # 직원은 유형마다 중복되므로 합이 아니라 유형별 인원 중 최댓값
        "avg_score": round(overall, 2),
        "avg_score_by_eval_type": {t: round(by_type[t], 2) for t in EVAL_TYPES if t in by_type},
    }

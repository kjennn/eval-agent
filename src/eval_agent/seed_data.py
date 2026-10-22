"""더미 데이터 생성 (전부 가짜, 실제 고객사 데이터 아님).

설계 원칙
- 순수 함수: build_dataset()은 DB를 모른다. 파이썬 객체만 만들어 돌려준다.
  그래서 DB 없이도 테스트할 수 있다. DB에 넣는 일은 insert_dataset()이 따로 한다.
- 결정적: 같은 seed면 항상 같은 데이터가 나온다. (테스트와 포트폴리오 재현성)
- 등급은 '목표 비율'대로 정확히 배정한다(랜덤 샘플링이 아님).
  그래서 "영업본부 B등급 비율이 높다"는 분석 신호가 항상 같은 값으로 나온다.
"""

import random
from dataclasses import dataclass

from sqlalchemy.orm import Session

from eval_agent.models import (
    EVAL_TYPES,
    GRADES,
    Employee,
    EvaluationCycle,
    EvaluationResult,
    OrgUnit,
)

# 본부 > 팀, 본부별 인원
ORG_STRUCTURE: dict[str, dict] = {
    "영업본부": {"teams": ["국내영업팀", "해외영업팀", "영업기획팀"], "headcount": 60},
    "개발본부": {"teams": ["플랫폼개발팀", "서비스개발팀", "QA팀"], "headcount": 80},
    "경영지원본부": {"teams": ["인사팀", "재무팀", "총무팀"], "headcount": 40},
    "생산본부": {"teams": ["생산1팀", "생산2팀", "품질관리팀"], "headcount": 70},
}

CYCLES = [(2024, "2024년 정기평가"), (2025, "2025년 정기평가")]

# 본부·연도별 목표 등급 비율(%). 각 행의 합은 100.
# 영업본부는 2025년에 B가 68%로 쏠리게 일부러 만들었다. (기준 문서의 허용 범위와 비교하는 분석용)
GRADE_TARGETS: dict[str, dict[int, dict[str, int]]] = {
    "영업본부": {
        2024: {"S": 5, "A": 18, "B": 52, "C": 20, "D": 5},
        2025: {"S": 2, "A": 10, "B": 68, "C": 17, "D": 3},
    },
    "개발본부": {
        2024: {"S": 5, "A": 24, "B": 47, "C": 19, "D": 5},
        2025: {"S": 5, "A": 22, "B": 49, "C": 19, "D": 5},
    },
    "경영지원본부": {
        2024: {"S": 4, "A": 20, "B": 50, "C": 21, "D": 5},
        2025: {"S": 5, "A": 21, "B": 49, "C": 20, "D": 5},
    },
    "생산본부": {
        2024: {"S": 5, "A": 20, "B": 51, "C": 19, "D": 5},
        2025: {"S": 5, "A": 19, "B": 52, "C": 19, "D": 5},
    },
}

# 등급별 점수 구간 [low, high)
GRADE_BANDS = {"S": (90, 100), "A": (80, 90), "B": (70, 80), "C": (60, 70), "D": (40, 60)}

JOB_LEVELS = ["사원", "대리", "과장", "차장", "부장"]
JOB_LEVEL_WEIGHTS = [30, 30, 22, 12, 6]

_SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권"]
_GIVEN_1 = ["민", "서", "지", "현", "준", "도", "하", "예", "수", "태", "유", "소"]
_GIVEN_2 = ["준", "윤", "우", "진", "아", "영", "호", "은", "린", "빈", "원", "희"]


@dataclass
class EmployeeSeed:
    name: str
    team: str
    hq: str
    job_level: str


@dataclass
class ResultSeed:
    year: int
    employee_index: int  # Dataset.employees 안에서의 위치
    eval_type: str
    score: float
    grade: str


@dataclass
class Dataset:
    employees: list[EmployeeSeed]
    results: list[ResultSeed]


def allocate_grades(total: int, percents: dict[str, int]) -> list[str]:
    """total명에게 percents(%) 비율로 등급을 나눠 준다. 소수점은 '최대 잔여법'으로 정리한다.

    예: 60명, B 52% → 31.2명 → 우선 31명, 남는 자리는 소수 부분이 큰 등급부터 1명씩 더 준다.
    """
    raw = {g: total * percents[g] / 100 for g in GRADES}
    counts = {g: int(v) for g, v in raw.items()}
    leftover = total - sum(counts.values())
    for g in sorted(GRADES, key=lambda g: raw[g] - counts[g], reverse=True)[:leftover]:
        counts[g] += 1
    return [g for g in GRADES for _ in range(counts[g])]


def _score_for(grade: str, eval_type: str, rng: random.Random) -> float:
    low, high = GRADE_BANDS[grade]
    u = rng.random()
    if eval_type == "다면":
        u = 0.3 + 0.7 * u  # 다면평가는 구간 안에서 조금 후하게 나오도록
    return round(low + (high - low) * u, 2)


def build_dataset(seed: int = 42) -> Dataset:
    # random.Random(seed): 전역 상태를 건드리지 않는 독립 난수 생성기 (Java의 new Random(seed))
    rng = random.Random(seed)

    employees: list[EmployeeSeed] = []
    hq_members: dict[str, list[int]] = {}
    for hq, info in ORG_STRUCTURE.items():
        teams = info["teams"]
        hq_members[hq] = []
        for i in range(info["headcount"]):
            employees.append(
                EmployeeSeed(
                    name=rng.choice(_SURNAMES) + rng.choice(_GIVEN_1) + rng.choice(_GIVEN_2),
                    team=teams[i % len(teams)],  # 팀에 골고루 배치
                    hq=hq,
                    job_level=rng.choices(JOB_LEVELS, weights=JOB_LEVEL_WEIGHTS)[0],
                )
            )
            hq_members[hq].append(len(employees) - 1)

    results: list[ResultSeed] = []
    for year, _ in CYCLES:
        for hq, members in hq_members.items():
            for eval_type in EVAL_TYPES:
                grades = allocate_grades(len(members), GRADE_TARGETS[hq][year])
                rng.shuffle(grades)  # 어떤 직원이 어떤 등급을 받을지 섞는다
                for emp_idx, grade in zip(members, grades):
                    results.append(
                        ResultSeed(year, emp_idx, eval_type, _score_for(grade, eval_type, rng), grade)
                    )
    return Dataset(employees=employees, results=results)


def insert_dataset(session: Session, data: Dataset) -> dict[str, int]:
    """Dataset을 DB에 넣는다. 커밋은 호출한 쪽이 한다. (Spring의 @Transactional 경계와 같은 발상)"""
    # 본부 → flush로 id 확보 → 팀(parent_id = 본부 id)
    hq_rows = {name: OrgUnit(name=name) for name in ORG_STRUCTURE}
    session.add_all(hq_rows.values())
    session.flush()  # INSERT를 DB로 보내서 id를 채운다 (커밋은 아님)

    team_rows: dict[str, OrgUnit] = {}
    for hq, info in ORG_STRUCTURE.items():
        for team in info["teams"]:
            team_rows[team] = OrgUnit(name=team, parent_id=hq_rows[hq].id)
    session.add_all(team_rows.values())
    session.flush()

    emp_rows = [
        Employee(name=e.name, org_unit_id=team_rows[e.team].id, job_level=e.job_level)
        for e in data.employees
    ]
    session.add_all(emp_rows)
    cycle_rows = {year: EvaluationCycle(year=year, name=name) for year, name in CYCLES}
    session.add_all(cycle_rows.values())
    session.flush()

    session.add_all(
        EvaluationResult(
            cycle_id=cycle_rows[r.year].id,
            employee_id=emp_rows[r.employee_index].id,
            eval_type=r.eval_type,
            score=r.score,
            grade=r.grade,
        )
        for r in data.results
    )
    session.flush()
    return {
        "org_unit": len(hq_rows) + len(team_rows),
        "employee": len(emp_rows),
        "evaluation_cycle": len(cycle_rows),
        "evaluation_result": len(data.results),
    }

import json

import pytest
from sqlalchemy import func, select

from eval_agent.models import EvaluationResult
from eval_agent.tools import compare_years, get_grade_distribution, get_org_summary


def _ratio(result: dict, grade: str) -> float:
    return next(d["ratio_pct"] for d in result["distribution"] if d["grade"] == grade)


def _count(result: dict, grade: str) -> int:
    return next(d["count"] for d in result["distribution"] if d["grade"] == grade)


# ---------- get_grade_distribution ----------


def test_영업본부_2025_성과평가_등급분포(db):
    r = get_grade_distribution(db, 2025, "영업본부", "성과")
    assert r["total"] == 60 and r["unit"] == "인원"
    # 손으로 계산: 60명 x 68% = 40.8 → 최대 잔여법으로 B 41명
    assert _count(r, "B") == 41
    assert _ratio(r, "B") == 68.3
    assert [d["grade"] for d in r["distribution"]] == ["S", "A", "B", "C", "D"]


def test_조직을_생략하면_회사전체이고_본부별_breakdown이_붙는다(db):
    r = get_grade_distribution(db, 2025, eval_type="성과")
    assert r["org_name"] == "전체"
    assert r["total"] == 250
    by_hq = {b["org_name"]: b for b in r["breakdown"]}
    assert set(by_hq) == {"영업본부", "개발본부", "경영지원본부", "생산본부"}
    assert _ratio(by_hq["영업본부"], "B") > _ratio(by_hq["개발본부"], "B") + 10


def test_평가유형을_생략하면_세유형을_합산하고_단위가_건수다(db):
    r = get_grade_distribution(db, 2025, "영업본부")
    assert r["total"] == 180  # 60명 x 3유형
    assert "건수" in r["unit"]


def test_팀_이름으로도_조회된다(db):
    r = get_grade_distribution(db, 2025, "국내영업팀", "성과")
    assert r["total"] == 20 and "breakdown" not in r


def test_본부_조회는_팀별_breakdown을_준다(db):
    r = get_grade_distribution(db, 2025, "영업본부", "성과")
    assert len(r["breakdown"]) == 3
    assert sum(b["total"] for b in r["breakdown"]) == r["total"]


def test_데이터가_없는_연도는_에러를_돌려준다(db):
    r = get_grade_distribution(db, 2023)
    assert r["error"] == "no_data"
    assert r["available_years"] == [2024, 2025]
    assert "2023" in r["message"]


def test_없는_조직은_에러와_본부목록을_돌려준다(db):
    r = get_grade_distribution(db, 2025, "없는본부")
    assert r["error"] == "org_not_found"
    assert "영업본부" in r["available_headquarters"]


def test_잘못된_평가유형은_에러를_돌려준다(db):
    r = get_grade_distribution(db, 2025, "영업본부", "인성")
    assert r["error"] == "invalid_eval_type"


# ---------- compare_years ----------


def test_영업본부_2024에서_2025_B등급이_크게_늘었다(db):
    r = compare_years(db, "영업본부", 2024, 2025)
    b = next(c for c in r["changes"] if c["grade"] == "B")
    # 2024: 31/60 = 51.67%, 2025: 41/60 = 68.33% → +16.67%p → 16.7
    # (표시용 비율 51.7, 68.3을 빼면 16.6이 되는 반올림 오차를 피해 건수에서 다시 계산한다)
    assert b["from_ratio_pct"] == 51.7
    assert b["to_ratio_pct"] == 68.3
    assert b["diff_pct_point"] == 16.7
    assert r["from"]["total"] == r["to"]["total"] == 180


def test_compare_years는_없는_연도를_에러로_돌려준다(db):
    assert compare_years(db, "영업본부", 2023, 2025)["error"] == "no_data"
    assert compare_years(db, "영업본부", 2024, 2026)["error"] == "no_data"


def test_compare_years는_없는_조직을_에러로_돌려준다(db):
    assert compare_years(db, "없는본부", 2024, 2025)["error"] == "org_not_found"


# ---------- get_org_summary ----------


def test_개발본부_2025_요약이_독립_계산과_일치한다(db, dataset):
    r = get_org_summary(db, 2025, "개발본부")

    # SQL이 아니라 파이썬 객체에서 직접 평균을 구해서 비교한다 (같은 실수를 두 번 하지 않으려고)
    mine = [x for x in dataset.results if x.year == 2025 and dataset.employees[x.employee_index].hq == "개발본부"]
    expected_overall = sum(x.score for x in mine) / len(mine)
    expected_multi = [x.score for x in mine if x.eval_type == "다면"]

    assert r["headcount"] == 80
    assert r["avg_score"] == pytest.approx(expected_overall, abs=0.01)
    assert r["avg_score_by_eval_type"]["다면"] == pytest.approx(sum(expected_multi) / 80, abs=0.01)
    assert set(r["avg_score_by_eval_type"]) == {"역량", "성과", "다면"}


def test_org_summary는_없는_연도와_조직을_에러로_돌려준다(db):
    assert get_org_summary(db, 2023, "개발본부")["error"] == "no_data"
    assert get_org_summary(db, 2025, "없는본부")["error"] == "org_not_found"


# ---------- 공통 성질 ----------


def test_모든_결과는_JSON으로_직렬화되고_개인_이름을_담지_않는다(db, dataset):
    results = [
        get_grade_distribution(db, 2025),
        get_grade_distribution(db, 2025, "영업본부", "다면"),
        compare_years(db, "영업본부", 2024, 2025),
        get_org_summary(db, 2025, "개발본부"),
        get_grade_distribution(db, 2023),
    ]
    dumped = "".join(json.dumps(r, ensure_ascii=False) for r in results)  # 직렬화 안 되면 여기서 실패
    # 직원 이름이 한 건도 새어 나오지 않았는지 (3글자 이름이 결과 문자열에 들어 있는지 검사)
    assert not any(e.name in dumped for e in dataset.employees)


def test_도구는_읽기_전용이다_행_수가_변하지_않는다(db):
    before = db.scalar(select(func.count()).select_from(EvaluationResult))
    get_grade_distribution(db, 2025)
    compare_years(db, "영업본부", 2024, 2025)
    get_org_summary(db, 2025, "개발본부")
    assert db.scalar(select(func.count()).select_from(EvaluationResult)) == before
    assert not db.new and not db.dirty and not db.deleted

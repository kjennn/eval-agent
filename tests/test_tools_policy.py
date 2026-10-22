import json

from eval_agent.tools import search_policy_docs


def test_영업본부_B등급_허용_질의는_영업본부_예외규정이_1순위다():
    r = search_policy_docs("영업본부 B등급 허용 상한")
    assert r["found"] is True
    top = r["results"][0]
    assert top["source"] == "02-org-exceptions.md"
    assert top["section"] == "1. 영업본부"
    assert "65%" in top["text"]


def test_B등급_허용범위_질의는_배분_가이드의_해당_절을_찾는다():
    r = search_policy_docs("B등급 허용 범위 정상")
    top = r["results"][0]
    assert top["source"] == "01-grade-distribution-guide.md"
    assert "40% 이상 60% 이하" in top["text"]


def test_top_k만큼만_돌려준다():
    assert len(search_policy_docs("평가", top_k=2)["results"]) == 2


def test_관련_문서가_없으면_found가_False다():
    r = search_policy_docs("우주선 연료 보급")
    assert r["found"] is False and r["results"] == []


def test_키워드가_없는_질의도_안전하게_처리한다():
    r = search_policy_docs("? !")
    assert r["found"] is False and r["results"] == []


def test_결과는_JSON으로_직렬화된다():
    json.dumps(search_policy_docs("이의신청"), ensure_ascii=False)

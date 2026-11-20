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


# ---------- 임베딩 검색과 대체(fallback) ----------

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from eval_agent.rag.store import VectorBase  # noqa: E402
from tests.fake_embedder import FakeEmbedder  # noqa: E402


def test_임베더가_없으면_키워드_검색이고_method가_적힌다():
    r = search_policy_docs("영업본부 B등급 허용 상한")
    assert r["method"] == "keyword" and "fallback_reason" not in r


def test_색인이_없으면_키워드로_대체하고_이유를_알려준다():
    # 테이블은 있지만 비어 있다 (index_policy.py를 아직 안 돌린 상태)
    engine = create_engine("sqlite://")
    VectorBase.metadata.create_all(engine)
    r = search_policy_docs(
        "영업본부 B등급 허용 상한", session_factory=sessionmaker(engine), embedder=FakeEmbedder()
    )
    assert r["method"] == "keyword"
    assert "index_policy.py" in r["fallback_reason"]
    assert r["results"][0]["section"] == "1. 영업본부"  # 대체돼도 검색 결과는 정상


def test_DB나_API_오류가_나도_검색은_키워드로_계속된다(session_factory):
    # 메모리 SQLite에는 policy_chunk 테이블도 pgvector도 없어서 임베딩 검색이 실패한다
    r = search_policy_docs("이의신청 기간", session_factory=session_factory, embedder=FakeEmbedder())
    assert r["method"] == "keyword" and r["found"] is True
    assert "fallback_reason" in r

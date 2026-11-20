"""실제 PostgreSQL + pgvector로 색인·검색을 확인한다. (선택 실행)

    RUN_PG_TESTS=1 uv run pytest tests/test_vector_store_pg.py

기본 pytest에서는 건너뛴다. DB 없이도 전체 테스트가 돌아가야 하기 때문이다.
모든 작업을 트랜잭션 하나 안에서 하고 마지막에 rollback하므로, 실제 색인 데이터는 바뀌지 않는다.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from eval_agent.config import get_settings
from eval_agent.rag.store import (
    NotIndexedError,
    VectorBase,
    index_chunks,
    search_by_vector,
    vector_search,
)
from eval_agent.tools.policy import load_chunks
from tests.fake_embedder import FakeEmbedder

pytestmark = pytest.mark.skipif(os.environ.get("RUN_PG_TESTS") != "1", reason="RUN_PG_TESTS=1 일 때만 실행")


@pytest.fixture
def pg_session():
    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        trans = conn.begin()
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        VectorBase.metadata.create_all(conn)
        with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
            yield session
        trans.rollback()


def test_색인한_문단_수는_문서의_문단_수와_같다(pg_session):
    n = index_chunks(pg_session, FakeEmbedder(), load_chunks())
    assert n == len(list(load_chunks())) == 20  # "## 절" 18개 + 첫 절 앞의 개요 2개(01, 02 문서)


def test_코사인_거리가_가까운_문단이_먼저_나온다(pg_session):
    index_chunks(pg_session, FakeEmbedder(), load_chunks())
    # 유사도 하한은 voyage-4 기준이라, 점수가 낮게 나오는 가짜 임베더에서는 끄고 정렬만 확인한다
    emb = FakeEmbedder()
    qvec = emb.embed_query("영업본부 B등급 상한 예외")
    results = search_by_vector(pg_session, emb.model, qvec, top_k=3, min_similarity=0.0)
    assert results[0]["source"] == "02-org-exceptions.md"
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True) and all(0 < s <= 1 for s in scores)


def test_다른_모델로_만든_색인은_쓰지_않는다(pg_session):
    index_chunks(pg_session, FakeEmbedder(), load_chunks())
    other = FakeEmbedder()
    other.model = "another-model"
    with pytest.raises(NotIndexedError):
        vector_search(pg_session, other, "영업본부")


def test_유사도_하한보다_낮은_문단은_돌려주지_않는다(pg_session):
    emb = FakeEmbedder()
    index_chunks(pg_session, emb, load_chunks())
    qvec = emb.embed_query("영업본부 B등급 상한 예외")
    assert search_by_vector(pg_session, emb.model, qvec, top_k=3, min_similarity=0.0)
    assert search_by_vector(pg_session, emb.model, qvec, top_k=3, min_similarity=0.99) == []

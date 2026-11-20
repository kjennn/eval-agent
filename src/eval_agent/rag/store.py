"""pgvector에 기준 문서 문단을 저장하고, 질문과 의미가 가까운 문단을 찾는다.

테이블을 평가 데이터(models.py의 Base)와 다른 메타데이터(VectorBase)에 둔 이유
- seed.py --reset, 테스트용 메모리 SQLite는 Base만 만들고 지운다. 벡터 테이블은 pgvector 확장이
  있어야 하므로 PostgreSQL에서 index_policy.py가 따로 만든다. (서로 생명주기가 다르다)

검색 원리
- 문단마다 임베딩 벡터를 미리 저장해 두고(색인), 질문을 같은 모델로 벡터로 바꾼 뒤
  코사인 거리(<=> 연산자)가 가장 작은 문단부터 가져온다. 유사도 = 1 - 코사인 거리.
- 18개 문단이라 인덱스(HNSW 등) 없이 전체를 비교한다. 수만 건 이상이면 인덱스를 만든다.
"""

from collections.abc import Iterable
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Engine, String, Text, delete, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from eval_agent.rag.embedder import EMBEDDING_DIM, Embedder

# 이 값보다 유사도가 낮으면 '관련 문단 없음'으로 본다. 벡터 검색은 무조건 가장 가까운 것을 돌려주므로,
# 엉뚱한 질문("우주선 연료")에도 결과가 나오지 않게 하는 하한이다.
# voyage-4로 잰 값(docs/embedding-search.md 7단계): 무관한 질문의 1위는 최고 0.322, 관련 질문의 1위는 최저 0.479.
# 그 사이인 0.4로 둔다. 모델을 바꾸면 다시 재야 한다.
MIN_SIMILARITY = 0.4


class VectorBase(DeclarativeBase):
    """벡터 테이블 전용 메타데이터."""


class PolicyChunk(VectorBase):
    __tablename__ = "policy_chunk"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100))  # 파일명
    document: Mapped[str] = mapped_column(String(200))  # 문서 제목
    section: Mapped[str] = mapped_column(String(200))  # 소제목
    text: Mapped[str] = mapped_column(Text)
    # 어느 모델로 만든 벡터인지 같이 저장한다. 모델이 다르면 벡터끼리 비교할 수 없기 때문이다.
    embedding_model: Mapped[str] = mapped_column(String(50))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class NotIndexedError(RuntimeError):
    """현재 모델로 만든 색인이 없다. (index_policy.py를 아직 안 돌렸거나 모델을 바꿨다)"""


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    VectorBase.metadata.create_all(engine)


def index_chunks(
    session: Session, embedder: Embedder, chunks: Iterable[tuple[str, str, str, str]]
) -> int:
    """(source, document, section, text) 목록을 임베딩해서 저장한다. 기존 색인은 지우고 새로 만든다."""
    rows = list(chunks)
    # 제목까지 함께 임베딩해야 "영업본부 예외" 같은 질문이 그 절의 본문과 잘 맞는다.
    vectors = embedder.embed_documents([f"{doc}\n{sec}\n{body}" for _, doc, sec, body in rows])
    session.execute(delete(PolicyChunk))
    session.add_all(
        PolicyChunk(
            source=src, document=doc, section=sec, text=body,
            embedding_model=embedder.model, embedding=vec,
        )
        for (src, doc, sec, body), vec in zip(rows, vectors, strict=True)
    )
    return len(rows)


def vector_search(
    session: Session, embedder: Embedder, query: str, top_k: int = 3
) -> list[dict[str, Any]]:
    indexed = session.scalar(
        select(func.count()).select_from(PolicyChunk).where(PolicyChunk.embedding_model == embedder.model)
    )
    if not indexed:
        raise NotIndexedError(f"'{embedder.model}' 모델로 만든 색인이 없습니다. scripts/index_policy.py를 실행하세요.")

    return search_by_vector(session, embedder.model, embedder.embed_query(query), top_k)


def search_by_vector(
    session: Session,
    model: str,
    qvec: list[float],
    top_k: int = 3,
    min_similarity: float = MIN_SIMILARITY,
) -> list[dict[str, Any]]:
    """이미 임베딩한 질문 벡터로 가까운 문단을 찾는다. (질문 임베딩과 DB 검색을 나눠 쓸 때)

    min_similarity는 모델마다 알맞은 값이 다르다. 기본값은 voyage-4로 잰 값이다.
    """
    distance = PolicyChunk.embedding.cosine_distance(qvec).label("distance")
    stmt = (
        select(PolicyChunk, distance)
        .where(PolicyChunk.embedding_model == model)
        .order_by(distance)
        .limit(top_k)
    )
    results = []
    for chunk, dist in session.execute(stmt).all():
        similarity = 1 - float(dist)
        if similarity < min_similarity:
            continue
        results.append(
            {
                "source": chunk.source,
                "document": chunk.document,
                "section": chunk.section,
                "score": round(similarity, 3),
                "text": chunk.text,
            }
        )
    return results


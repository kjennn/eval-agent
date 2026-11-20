"""기준 문서(docs/policy/*.md)를 임베딩해서 pgvector에 저장한다 (색인).

    uv run python scripts/index_policy.py

- 문서를 고쳤거나 EMBEDDING_MODEL을 바꿨을 때 다시 실행한다. 실행할 때마다 기존 색인을 지우고 새로 만든다.
- .env에 VOYAGE_API_KEY와 EMBEDDING_MODEL이 있어야 한다. 문단 20개라 무료 토큰 안에서 끝난다.
- seed.py와 같은 역할: seed.py는 평가 데이터를, 이 스크립트는 검색용 벡터를 DB에 넣는다.
"""

import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from eval_agent.config import get_settings
from eval_agent.rag.embedder import create_embedder
from eval_agent.rag.store import ensure_schema, index_chunks
from eval_agent.tools.policy import load_chunks


def main() -> int:
    settings = get_settings()
    embedder = create_embedder(settings)
    if embedder is None:
        print(".env에 VOYAGE_API_KEY가 없습니다. docs/embedding-search.md 0단계를 참고하세요.")
        return 1

    engine = create_engine(settings.database_url)
    ensure_schema(engine)  # CREATE EXTENSION vector + policy_chunk 테이블
    with Session(engine) as session:
        n = index_chunks(session, embedder, load_chunks())
        session.commit()
    print(f"policy_chunk: {n}개 문단을 '{embedder.model}' 모델로 색인했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

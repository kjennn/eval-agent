"""기준 문서 검색 한 번을 따라가며, 임베딩 모델과 pgvector를 실제로 썼는지 보여 준다.

    uv run python scripts/trace_search.py
    uv run python scripts/trace_search.py "평가 결과에 이의를 제기하려면?"

출력
1. DB(policy_chunk)에 저장된 문단 벡터 일부
2. 검색 과정을 일어난 순서대로: [SQL]은 DB로 보낸 쿼리, [Voyage]는 임베딩 API 호출
   (벡터 검색 SQL에서 pgvector 코사인 거리 연산자 <=> 가 보인다)
3. 도구 결과 (method, 점수, 문단)

Voyage API를 한 번 부른다(무료 토큰 안). Claude API는 부르지 않는다.
"""

import logging
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from eval_agent.config import get_settings
from eval_agent.rag.embedder import EMBEDDING_DIM, create_embedder
from eval_agent.tools import search_policy_docs

DEFAULT_QUESTION = "평가 결과가 억울하면 어떻게 해?"


class _SqlLogFilter(logging.Filter):
    """SQL 로그를 읽기 쉽게 다듬는다.

    - 파라미터 줄의 질문 벡터(숫자 1024개)는 앞 3개만 남긴다.
      (SQLAlchemy가 긴 파라미터를 로그에서 미리 잘라 두므로, 개수는 세지 않고 차원 상수로 표시한다)
    - 여러 줄로 나뉜 SQL은 한 줄로 편다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if msg.startswith("[generated") and "embedding_1" in msg:
            head, _, rest = msg.partition("'[")
            numbers, _, tail = rest.partition("]'")
            first = ",".join(numbers.split(",")[:3])
            msg = f"{head}'[{first}, ... (총 {EMBEDDING_DIM}개 중 앞 3개)]'{tail}"
        record.msg, record.args = "[SQL] " + " ".join(msg.split()), ()
        return True


def main() -> int:
    question = " ".join(sys.argv[1:]) or DEFAULT_QUESTION
    settings = get_settings()
    embedder = create_embedder(settings)
    if embedder is None:
        print(".env에 VOYAGE_API_KEY가 없습니다. 이 상태에서는 키워드 검색만 동작합니다.")
        return 1
    engine = create_engine(settings.database_url)

    print("=== 1. DB에 저장된 문단 벡터 (policy_chunk, 앞 3개)")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT section, embedding_model, vector_dims(embedding), left(embedding::text, 50) "
                "FROM policy_chunk ORDER BY id LIMIT 3"
            )
        ).all()
    for section, model, dims, preview in rows:
        print(f"  {section} | {model} | {dims}차원 | {preview}...")

    # 임베딩 호출을 감싸서, 무엇을 보내고 무엇을 받았는지 출력한다
    original = embedder.embed_queries

    def traced(texts: list[str]) -> list[list[float]]:
        vectors = original(texts)
        head = [round(x, 4) for x in vectors[0][:3]]
        print(f"  [Voyage] model={embedder.model}, 입력={texts}")
        print(f"  [Voyage] 받은 벡터: {len(vectors[0])}차원, 앞 3개 값={head}")
        return vectors

    embedder.embed_queries = traced  # type: ignore[method-assign]

    print("\n=== 2. 검색 과정 (일어난 순서대로)")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  %(message)s"))
    handler.addFilter(_SqlLogFilter())
    sql_logger = logging.getLogger("sqlalchemy.engine")
    sql_logger.addHandler(handler)
    sql_logger.setLevel(logging.INFO)
    try:
        result = search_policy_docs(question, session_factory=sessionmaker(engine), embedder=embedder)
    finally:
        sql_logger.setLevel(logging.WARNING)

    print("\n=== 3. 도구 결과")
    print(f"  method = {result['method']}")
    if "fallback_reason" in result:
        print(f"  fallback_reason = {result['fallback_reason']}")
    for r in result["results"]:
        print(f"  {r['score']}  {r['source']} / {r['section']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

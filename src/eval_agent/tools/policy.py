"""기준 문서 검색 도구.

두 가지 방식이 있다.
- 임베딩(벡터) 검색: 질문과 '의미'가 가까운 문단을 pgvector에서 찾는다. (rag/store.py)
  조사("영업본부가")나 다른 표현("이의 제기" ↔ "이의신청")에도 맞는 문단을 찾을 수 있다.
- 키워드 검색: 질문 키워드가 많이 들어 있는 문단을 찾는다. API 키나 DB 없이 동작한다.

search_policy_docs()는 임베딩 검색을 먼저 시도하고, 쓸 수 없으면(키 없음, 색인 없음, API 오류)
키워드 검색으로 돌아간다. 결과의 method 필드에 실제로 쓴 방식이 적힌다.
도구 이름·파라미터·결과 모양은 그대로라서 에이전트와 MCP 서버는 바뀌지 않는다.

문서는 '## 제목' 단위의 문단(chunk)으로 쪼갠다. 두 방식이 같은 문단 단위를 쓴다.
"""

import logging
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 타입힌트에만 쓴다. 실행 시에는 불러오지 않아서 pgvector 없이도 키워드 검색이 동작한다.
    from sqlalchemy.orm import Session

    from eval_agent.rag.embedder import Embedder

logger = logging.getLogger(__name__)

# 이 파일 위치(src/eval_agent/tools/)에서 프로젝트 루트의 docs/policy를 찾는다.
DEFAULT_POLICY_DIR = Path(__file__).resolve().parents[3] / "docs" / "policy"


def _split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """마크다운을 (문서 제목, [(소제목, 본문), ...])으로 나눈다."""
    title = ""
    sections: list[tuple[str, str]] = []
    heading = "개요"
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append((heading, body))

    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            heading, buf = line[3:].strip(), []
        else:
            buf.append(line)
    flush()
    return title, sections


def load_chunks(docs_dir: Path | None = None) -> Iterator[tuple[str, str, str, str]]:
    """기준 문서의 문단을 (파일명, 문서 제목, 소제목, 본문)으로 하나씩 돌려준다."""
    for path in sorted((docs_dir or DEFAULT_POLICY_DIR).glob("*.md")):
        title, sections = _split_sections(path.read_text(encoding="utf-8"))
        for heading, body in sections:
            yield path.name, title, heading, body


def search_policy_docs(
    query: str,
    top_k: int = 3,
    docs_dir: Path | None = None,
    *,  # 이 뒤의 인자는 이름을 붙여야만 넘길 수 있다 (키워드 전용 인자)
    session_factory: "Callable[[], Session] | None" = None,
    embedder: "Embedder | None" = None,
) -> dict[str, Any]:
    """임베딩 검색을 먼저 시도하고, 안 되면 키워드 검색으로 찾는다."""
    if embedder is not None and session_factory is not None:
        from eval_agent.rag.store import NotIndexedError, vector_search

        try:
            with session_factory() as session:
                results = vector_search(session, embedder, query, top_k)
            return {"query": query, "method": "vector", "found": bool(results), "results": results}
        except NotIndexedError as e:
            reason = str(e)
        except Exception:  # API 장애, DB에 pgvector 없음 등. 검색 자체는 계속되게 키워드로 돌아간다.
            logger.exception("임베딩 검색 실패, 키워드 검색으로 대체")
            reason = "임베딩 검색 중 오류가 나서 키워드 검색으로 대체했습니다."
        result = keyword_search(query, top_k, docs_dir)
        result["fallback_reason"] = reason
        return result
    return keyword_search(query, top_k, docs_dir)


def keyword_search(query: str, top_k: int = 3, docs_dir: Path | None = None) -> dict[str, Any]:
    """질문 키워드가 들어 있는 문단을 찾는다.

    점수 = (질문 키워드 중 문단에 들어 있는 키워드 수) x 100 + 등장 횟수(최대 10).
    여러 키워드를 골고루 포함한 문단이 한 키워드만 많이 반복되는 문단보다 앞선다.
    """
    # 한글/영문/숫자 덩어리로 키워드를 뽑는다. 한 글자짜리는 노이즈라 버린다.
    keywords = {k.lower() for k in re.findall(r"[0-9A-Za-z가-힣]+", query) if len(k) >= 2}
    if not keywords:
        return {
            "query": query, "method": "keyword", "found": False, "results": [],
            "message": "검색할 키워드가 없습니다.",
        }

    scored: list[dict[str, Any]] = []
    for source, title, heading, body in load_chunks(docs_dir):
        haystack = f"{title}\n{heading}\n{body}".lower()
        hits = {k: haystack.count(k) for k in keywords}
        matched = sum(1 for n in hits.values() if n > 0)
        if matched == 0:
            continue
        scored.append(
            {
                "source": source,
                "document": title,
                "section": heading,
                "score": matched * 100 + min(sum(hits.values()), 10),
                "text": body,
            }
        )

    scored.sort(key=lambda r: r["score"], reverse=True)
    results = scored[:top_k]
    return {"query": query, "method": "keyword", "found": bool(results), "results": results}

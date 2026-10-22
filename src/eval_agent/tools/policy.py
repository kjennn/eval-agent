"""기준 문서 검색 도구 (키워드 검색).

docs/policy/*.md 파일을 '## 제목' 단위의 문단(chunk)으로 쪼개고,
질문에서 뽑은 키워드가 많이 들어 있는 문단을 점수순으로 돌려준다.

한계 (README에 적을 예정)
- 단순 문자열 포함 검사라서 조사가 붙으면("영업본부가") 못 찾을 수 있고, 동의어도 모른다.
  이후 임베딩 기반 검색으로 바꿔 볼 수 있다. 지금은 '도구 구조'를 익히는 게 목적이다.
"""

import re
from pathlib import Path
from typing import Any

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


def search_policy_docs(
    query: str, top_k: int = 3, docs_dir: Path | None = None
) -> dict[str, Any]:
    """기준 문서에서 query와 관련 있는 문단을 찾는다.

    점수 = (질문 키워드 중 문단에 들어 있는 키워드 수) x 100 + 등장 횟수(최대 10).
    여러 키워드를 골고루 포함한 문단이 한 키워드만 많이 반복되는 문단보다 앞선다.
    """
    # 한글/영문/숫자 덩어리로 키워드를 뽑는다. 한 글자짜리는 노이즈라 버린다.
    keywords = {k.lower() for k in re.findall(r"[0-9A-Za-z가-힣]+", query) if len(k) >= 2}
    if not keywords:
        return {"query": query, "found": False, "results": [], "message": "검색할 키워드가 없습니다."}

    directory = docs_dir or DEFAULT_POLICY_DIR
    scored: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        title, sections = _split_sections(path.read_text(encoding="utf-8"))
        for heading, body in sections:
            haystack = f"{title}\n{heading}\n{body}".lower()
            hits = {k: haystack.count(k) for k in keywords}
            matched = sum(1 for n in hits.values() if n > 0)
            if matched == 0:
                continue
            scored.append(
                {
                    "source": path.name,
                    "document": title,
                    "section": heading,
                    "score": matched * 100 + min(sum(hits.values()), 10),
                    "text": body,
                }
            )

    scored.sort(key=lambda r: r["score"], reverse=True)
    results = scored[:top_k]
    return {"query": query, "found": bool(results), "results": results}

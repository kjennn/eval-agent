"""키워드 검색과 임베딩 검색의 결과를 같은 질문으로 나란히 비교한다.

    uv run python scripts/compare_search.py
    uv run python scripts/compare_search.py "질문 하나만 따로 비교"

index_policy.py로 색인을 먼저 만들어야 한다. 질문마다 Voyage API를 한 번 호출한다(무료 토큰 안).
결제 수단을 등록하지 않은 Voyage 계정은 분당 3회로 제한되므로, 모든 질문을 요청 한 번으로 묶어 임베딩한다.
"""

import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from eval_agent.config import get_settings
from eval_agent.rag.embedder import create_embedder
from eval_agent.rag.store import search_by_vector
from eval_agent.tools.policy import keyword_search

# (질문, 기대하는 1순위 '파일명 / 소제목' 일부, 무엇을 보려는 질문인가)
CASES = [
    ("영업본부 B등급 허용 상한", "02-org-exceptions.md / 1. 영업본부", "키워드가 그대로 들어 있는 기본 질문"),
    ("영업본부가 B를 많이 줘도 돼?", "02-org-exceptions.md / 1. 영업본부", "조사가 붙고 'B등급'을 'B'로 줄인 구어체"),
    ("평가 결과가 억울하면 어떻게 해?", "04-calibration-and-appeal.md / 3. 이의신청", "'이의신청'이라는 단어 없이 의미로만 묻기"),
    ("팀원이 다섯 명뿐인 팀도 비율을 지켜야 해?", "01-grade-distribution-guide.md / 5. 소규모 조직", "'10명 미만'을 숫자 없이 표현"),
    ("성과평가랑 역량평가 반영 비중", "03-evaluation-types-and-weights.md", "평가 유형 문서"),
    ("우주선 연료 보급 일정", "(없음)", "무관한 질문: 결과가 없어야 한다"),
]


def _fmt(results: list[dict]) -> list[str]:
    if not results:
        return ["(결과 없음)"]
    return [f"{r['score']:>7}  {r['source']} / {r['section']}" for r in results]


def main() -> int:
    settings = get_settings()
    embedder = create_embedder(settings)
    if embedder is None:
        print(".env에 VOYAGE_API_KEY가 없습니다.")
        return 1
    session_factory = sessionmaker(create_engine(settings.database_url))

    cases = [(q, "?", "직접 입력") for q in sys.argv[1:]] or CASES
    qvecs = embedder.embed_queries([q for q, _, _ in cases])  # API 호출은 여기서 한 번뿐
    for (question, expected, why), qvec in zip(cases, qvecs, strict=True):
        print(f"\n=== {question}\n    기대: {expected}  ({why})")
        kw = keyword_search(question, top_k=3)["results"]
        with session_factory() as session:
            vec = search_by_vector(session, embedder.model, qvec, top_k=3)
        print("  [키워드]  점수=키워드수x100+등장횟수")
        for line in _fmt(kw):
            print("   ", line)
        print("  [임베딩]  점수=코사인 유사도")
        for line in _fmt(vec):
            print("   ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

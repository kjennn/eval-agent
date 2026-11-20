"""임베딩 모델 인터페이스와 Voyage AI 구현체.

왜 인터페이스(Protocol)로 두는가
- 검색 코드는 "문장 → 숫자 벡터"만 알면 되고, 어느 회사 모델인지는 몰라도 된다.
- 테스트에서는 API를 부르지 않는 가짜 구현체를 꽂는다. 나중에 로컬 모델(bge-m3 등)을 비교하고 싶으면
  구현체 하나만 더 만들면 된다.
- Spring으로 치면 `interface Embedder`와 `@Component class VoyageEmbedder implements Embedder`다.
  다른 점: Python의 Protocol은 implements를 쓰지 않는다. 같은 이름·모양의 메서드만 있으면 그 타입으로 인정된다
  (구조적 타이핑, '덕 타이핑'에 타입 검사를 붙인 것).

문서용과 질문용을 나누는 이유
- Voyage는 input_type="document" / "query"를 받는다. 짧은 질문과 긴 문단을 같은 공간에서 비교하기 좋게
  모델 쪽에서 각각 다른 안내 문구를 앞에 붙여 임베딩한다. 그래서 메서드를 둘로 나눴다.
"""

from typing import Protocol

from eval_agent.config import Settings

# 벡터 차원. DB 컬럼(vector(1024))과 반드시 같아야 한다. voyage-4 계열의 기본값이 1024다.
EMBEDDING_DIM = 1024


class Embedder(Protocol):
    model: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class VoyageEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        import voyageai  # 실제로 쓸 때만 불러온다 (키 없이 테스트할 때 import 비용을 피함)

        self.model = model
        self._client = voyageai.Client(api_key=api_key, max_retries=2, timeout=20)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        result = self._client.embed(
            texts, model=self.model, input_type="document", output_dimension=EMBEDDING_DIM
        )
        return result.embeddings

    def embed_query(self, text: str) -> list[float]:
        result = self._client.embed(
            [text], model=self.model, input_type="query", output_dimension=EMBEDDING_DIM
        )
        return result.embeddings[0]


def create_embedder(settings: Settings) -> Embedder | None:
    """키가 없으면 None (= 키워드 검색만 사용). 키는 있는데 모델명이 없으면 설정 실수이므로 바로 알린다."""
    if not settings.voyage_api_key:
        return None
    if not settings.embedding_model:
        raise ValueError(".env에 EMBEDDING_MODEL(예: voyage-4)을 설정하세요.")
    return VoyageEmbedder(settings.voyage_api_key, settings.embedding_model)

"""테스트용 가짜 임베더. API를 부르지 않고, 글자 2개 묶음(bigram)을 해시해서 벡터를 만든다.

의미를 이해하지는 못하지만 '겹치는 글자가 많으면 벡터가 가깝다'는 성질이 있어서,
검색 순서가 올바르게 나오는지 확인하는 데 충분하다. 같은 입력이면 항상 같은 벡터가 나온다.
"""

import hashlib
import math

from eval_agent.rag.embedder import EMBEDDING_DIM


class FakeEmbedder:
    model = "fake-bigram"

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * EMBEDDING_DIM
        t = "".join(text.split()).lower()
        for i in range(len(t) - 1):
            h = int(hashlib.md5(t[i : i + 2].encode()).hexdigest(), 16)
            v[h % EMBEDDING_DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

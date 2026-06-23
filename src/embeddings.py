"""임베딩 제공자 추상화.

- VOYAGE_API_KEY 가 있으면 Voyage AI(voyage-3) 사용 — Anthropic 권장 임베딩.
- 없으면 결정론적 로컬 해시 임베딩으로 폴백 → 키 없이도 파이프라인이 끝까지 동작.
  (로컬 폴백은 의미 품질이 제한적이며, 배선/검증용. 실전은 Voyage 사용 권장.)
"""
from __future__ import annotations

import hashlib
import math
import os
import re

_DIM = 256
_TOKEN = re.compile(r"[0-9a-zA-Z]+|[가-힣]+")


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN.findall(text.lower()):
        if re.match(r"[가-힣]+", m) and len(m) >= 2:
            out += [m[i:i + 2] for i in range(len(m) - 1)]  # 한글 bigram
        else:
            out.append(m)
    return out


def _local_embed(text: str) -> list[float]:
    vec = [0.0] * _DIM
    for tok in _tokens(text):
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        vec[h % _DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class Embeddings:
    def __init__(self) -> None:
        self.provider = "local-hash"
        self._client = None
        if os.getenv("VOYAGE_API_KEY"):
            try:
                import voyageai  # type: ignore
                self._client = voyageai.Client()
                self.provider = "voyage-3"
            except Exception:
                self._client = None

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        if self._client is not None:
            r = self._client.embed(texts, model="voyage-3", input_type=input_type)
            return r.embeddings
        return [_local_embed(t) for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)

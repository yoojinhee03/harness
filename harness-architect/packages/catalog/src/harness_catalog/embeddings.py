"""임베딩 — 스왑 가능한 인터페이스. 개발: 기술 스택 §2.

기본은 키 없이 도는 **로컬 폴백**(해싱 벡터라이저). 품질이 필요하면 `VOYAGE_API_KEY` 로
Voyage(`voyage-3.5`) 로 스왑. 인터페이스가 같으므로 저비용 반복은 로컬, 품질은 Voyage.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol

_DIM = 512
_TOKEN_RE = re.compile(r"[0-9a-zA-Z가-힣]+")


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _tokenize(text: str) -> list[str]:
    """단어 토큰 + 문자 트라이그램(한국어·오타 견고성)."""
    words = _TOKEN_RE.findall(text.lower())
    grams: list[str] = []
    for w in words:
        if len(w) <= 3:
            grams.append(w)
        else:
            grams.extend(w[i : i + 3] for i in range(len(w) - 2))
    return words + grams


def _hash(token: str) -> tuple[int, float]:
    digest = hashlib.md5(token.encode("utf-8")).digest()  # noqa: S324 - 해싱 벡터라이저(비암호)
    index = int.from_bytes(digest[:4], "big") % _DIM
    sign = 1.0 if digest[4] & 1 else -1.0
    return index, sign


class LocalEmbedder:
    """결정적 해싱 벡터라이저 — 의존성·키 불필요. 소규모 카탈로그에 충분."""

    name = "local-hashing-512"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * _DIM
        for token in _tokenize(text):
            idx, sign = _hash(token)
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]


class OpenAIEmbedder:
    """OpenAI 임베딩 — 품질 모드. OPENAI_API_KEY 필요, openai 설치 필요."""

    def __init__(self, model: str = "text-embedding-3-small", api_key: str | None = None) -> None:
        self.name = f"openai:{model}"
        self._model = model
        try:
            import openai
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("OpenAIEmbedder 는 openai 가 필요합니다: uv sync --extra openai") from exc
        self._client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - 네트워크
        result = self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in result.data]


def get_embedder(settings: object | None = None) -> Embedder:
    """설정에 따라 임베더를 고른다: openai | local(폴백). (Voyage 는 제거됨.)

    앱 레벨 키 경로는 main 에서 OpenAIEmbedder/LocalEmbedder 를 직접 구성해 주입한다.
    settings 는 `harness_catalog.settings.Settings` (순환 import 회피 위해 느슨히 받음).
    """
    from .settings import load_settings

    cfg = settings if settings is not None else load_settings()
    if getattr(cfg, "embedder_choice", "local") == "openai":
        try:
            return OpenAIEmbedder(model=getattr(cfg, "openai_embed_model", "text-embedding-3-small"))
        except RuntimeError:  # pragma: no cover
            pass
    return LocalEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))

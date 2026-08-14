"""Phase 1 — RAG 실연동 경로 테스트 (fake 주입, 네트워크 없음).

품질 모드(Voyage 임베더 · Claude Reasoner)가 실제로 주입 경로를 타는지, 그리고 키 없는
로컬 폴백이 동일하게 관통하는지 회귀 고정한다.
"""

from __future__ import annotations

import pytest
from harness_catalog import Recommender, build_registry
from harness_catalog.embeddings import LocalEmbedder
from harness_catalog.settings import Settings


@pytest.fixture(scope="module")
def registry():
    return build_registry()


# ── fake 임베더/Reasoner ──


class RecordingEmbedder:
    """호출을 기록하는 fake 임베더 — 주입 경로 검증용."""

    name = "fake-embedder"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._inner = LocalEmbedder()

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return self._inner.embed(texts)


class FakeReasoner:
    """품질 모드 스텁 — 고정 능력·근거 반환(네트워크 대체)."""

    name = "claude"

    def extract_requirements(self, description: str) -> list[str] | None:
        return ["review.code", "vcs.code-review"]

    def rank_reasons(self, description, items):
        return {i[0]: f"[claude] {i[1]}" for i in items}


def test_injected_embedder_is_used(registry):
    emb = RecordingEmbedder()
    rec = Recommender(registry, embedder=emb)
    assert emb.calls  # 인덱싱 시 카탈로그 문서 임베딩 호출됨
    rec.recommend("코드 리뷰 봇", top_k=3)
    assert len(emb.calls) >= 2  # 인덱싱 + 쿼리 임베딩


def test_injected_reasoner_drives_quality_mode(registry):
    rec = Recommender(registry, reasoner=FakeReasoner())
    result = rec.recommend("아무 설명", top_k=3)
    assert result.extraction_mode == "claude"
    assert result.ranking_mode == "claude"
    assert result.requirements == ["review.code", "vcs.code-review"]
    assert all(r.reason.startswith("[claude]") for r in result.recommendations)


def test_local_fallback_regression(registry):
    """키 없는 기본 경로 — heuristic 모드로 PR 봇 컴포넌트를 여전히 추천."""
    rec = Recommender(registry)  # 기본: LocalEmbedder + NullReasoner
    result = rec.recommend("PR 자동 리뷰 봇, 코드 리뷰, 보안 스캔", top_k=4)
    assert result.extraction_mode == "heuristic"
    assert result.ranking_mode == "heuristic"
    ids = {r.id for r in result.recommendations}
    assert {"github-mcp", "pr-review-skill", "secret-scan-hook"} <= ids


def test_settings_mode_flags():
    s = Settings(
        anthropic_key=None, voyage_key=None, embedder_mode="auto", ranker_mode="auto",
        embed_model="x", claude_model="claude-sonnet-5",
    )
    assert s.embedder_choice == "local" and s.use_claude is False
    forced = Settings(
        anthropic_key=None, voyage_key=None, embedder_mode="openai", ranker_mode="claude",
        embed_model="x", claude_model="claude-sonnet-5", openai_key="o",
    )
    assert forced.embedder_choice == "openai" and forced.use_claude is True

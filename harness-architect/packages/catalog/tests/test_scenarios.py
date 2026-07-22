"""Phase 4 — 둘째 시나리오 관통 (실제 확장 카탈로그).

이슈 분류 · 문서 초안 시나리오가 추천에 등장하고, cross-type 의존(skill→mcp)이 리졸버에서
충족되는지 확인한다. PR 봇 경로 회귀도 함께 고정한다.
"""

from __future__ import annotations

import pytest
from harness_catalog import Recommender, build_registry
from harness_resolver import (
    ComponentSelection,
    HarnessConfig,
    HarnessMetadata,
    resolve,
)


@pytest.fixture(scope="module")
def registry():
    return build_registry()


def test_catalog_size(registry):
    # 시드 10 + 프롬프트 조각 3(role·format·safety) = 13.
    assert len(registry.all()) == 13


# ── 이슈 분류 시나리오 ──


def test_issue_triage_recommended(registry):
    rec = Recommender(registry)
    result = rec.recommend("이슈 분류 에이전트: 새 이슈를 읽고 라벨을 달고 담당자를 제안", top_k=8)
    ids = {r.id for r in result.recommendations}
    assert "issue-triage-skill" in ids
    assert "github-mcp" in ids  # vcs.issue-tracking 제공


def test_issue_triage_resolves_with_github(registry):
    config = HarnessConfig(
        metadata=HarnessMetadata(id="issue-bot"),
        components=[
            ComponentSelection(ref="github-mcp@1.4.0"),
            ComponentSelection(ref="issue-triage-skill@1.0.0"),
        ],
    )
    result = resolve(config, registry)
    assert result.ok is True
    assert result.diagnostics.gaps == []  # issue-triage.requires(vcs.issue-tracking) 충족


def test_issue_triage_gap_without_github(registry):
    config = HarnessConfig(
        metadata=HarnessMetadata(id="issue-bot"),
        components=[ComponentSelection(ref="issue-triage-skill@1.0.0")],
    )
    result = resolve(config, registry)
    gaps = {g.capability for g in result.diagnostics.gaps}
    assert "vcs.issue-tracking" in gaps


# ── 문서 초안 시나리오 ──


def test_doc_draft_recommended_and_resolves(registry):
    rec = Recommender(registry)
    result = rec.recommend("회의록을 요약해서 문서 초안을 만들고 위키에 저장", top_k=8)
    ids = {r.id for r in result.recommendations}
    assert "doc-draft-skill" in ids
    assert "notion-mcp" in ids  # knowledge.wiki 제공

    config = HarnessConfig(
        metadata=HarnessMetadata(id="doc-bot"),
        components=[
            ComponentSelection(ref="notion-mcp@1.0.0"),
            ComponentSelection(ref="doc-draft-skill@1.0.0"),
        ],
    )
    resolved = resolve(config, registry)
    assert resolved.ok is True
    assert resolved.diagnostics.gaps == []  # doc-draft.requires(knowledge.wiki) 충족


# ── PR 봇 경로 회귀 ──


def test_pr_bot_regression(registry):
    rec = Recommender(registry)
    result = rec.recommend("PR 자동 리뷰 봇, 코드 리뷰, 보안 스캔", top_k=6)
    ids = {r.id for r in result.recommendations}
    assert {"github-mcp", "pr-review-skill", "secret-scan-hook"} <= ids

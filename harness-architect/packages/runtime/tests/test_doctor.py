"""드리프트 진단 테스트 (Phase 9-2) — 저장된 하네스와 움직인 카탈로그의 간극.

하네스는 굳고 카탈로그는 움직인다. 그 간극을 실행 전에 알려주는 게 doctor 의 일이고,
**말없이 고치지 않는 것**이 그만큼 중요하다(조직 자산을 도구가 임의로 바꾸면 안 된다).
"""

from __future__ import annotations

from harness_resolver import (
    Component,
    ComponentSelection,
    HarnessConfig,
    HarnessMetadata,
    InMemoryRegistry,
)
from harness_runtime import apply_suggestions, doctor


def registry() -> InMemoryRegistry:
    return InMemoryRegistry(
        [
            # 같은 id 의 세 버전 — 1.0.0 은 deprecated, 2.0.0 이 최신 stable.
            Component(id="gh", type="mcp", name="GitHub", version="1.0.0", status="deprecated",
                      provides=["vcs.code-hosting"]),
            Component(id="gh", type="mcp", name="GitHub", version="1.5.0", provides=["vcs.code-hosting"]),
            Component(id="gh", type="mcp", name="GitHub", version="2.0.0", provides=["vcs.code-hosting"]),
            # deprecated 이고 상위 버전이 없다 → 타 컴포넌트 대체를 제안해야 한다.
            Component(id="old-notify", type="mcp", name="구 알림", version="1.0.0", status="deprecated",
                      provides=["comms.messaging"]),
            Component(id="slack", type="mcp", name="Slack", version="3.0.0", provides=["comms.messaging"]),
            Component(id="ctx", type="context", name="컨벤션", version="1.0.0",
                      provides=["convention.coding"], body="x"),
        ]
    )


def config(refs: list[str]) -> HarnessConfig:
    return HarnessConfig(
        metadata=HarnessMetadata(id="bot"),
        components=[ComponentSelection(ref=r) for r in refs],
    )


def by_id(report) -> dict:
    return {f.component_id: f for f in report.findings}


# ── 진단 ──


def test_pinned_latest_is_ok():
    f = by_id(doctor(config(["gh@2.0.0"]), registry()))["gh"]
    assert f.issue == "ok" and f.suggested_ref is None


def test_upgrade_available():
    f = by_id(doctor(config(["gh@1.5.0"]), registry()))["gh"]
    assert f.issue == "upgrade_available"
    assert f.current_version == "1.5.0" and f.latest_version == "2.0.0"
    assert f.suggested_ref == "gh@2.0.0"


def test_deprecated_pin_suggests_newer_same_id():
    """같은 id 의 상위 stable 이 있으면 그게 1순위 — 가장 안전한 교체다."""
    f = by_id(doctor(config(["gh@1.0.0"]), registry()))["gh"]
    assert f.issue == "deprecated" and f.suggested_ref == "gh@2.0.0"


def test_deprecated_without_newer_suggests_capability_peer():
    """상위 버전이 없으면 같은 능력을 주는 다른 컴포넌트를 제안한다(제안일 뿐)."""
    f = by_id(doctor(config(["old-notify@1.0.0"]), registry()))["old-notify"]
    assert f.issue == "deprecated" and f.suggested_ref == "slack@3.0.0"


def test_missing_pinned_version():
    f = by_id(doctor(config(["gh@9.9.9"]), registry()))["gh"]
    assert f.issue == "missing"
    assert f.pinned_version == "9.9.9" and f.suggested_ref == "gh@2.0.0"


def test_missing_component_entirely():
    f = by_id(doctor(config(["ghost@1.0.0"]), registry()))["ghost"]
    assert f.issue == "missing" and f.suggested_ref is None


def test_unpinned_is_flagged_as_drift():
    """버전을 안 박으면 카탈로그가 움직일 때마다 조용히 다른 걸 쓴다 — 그게 드리프트다."""
    f = by_id(doctor(config(["gh"]), registry()))["gh"]
    assert f.issue == "unpinned"
    assert f.pinned_version is None
    assert f.current_version == "2.0.0"  # 최신 stable 로 잡힌다(1.0.0 은 deprecated)
    assert f.suggested_ref == "gh@2.0.0"


# ── 리포트 집계 ──


def test_ok_and_blocking_separate_severity():
    """업그레이드 권고로 CI 를 깨지 않는다 — blocking 은 사라짐·deprecated 뿐이다."""
    upgrade_only = doctor(config(["gh@1.5.0"]), registry())
    assert upgrade_only.ok is False  # 손볼 게 있긴 하다
    assert upgrade_only.blocking == []  # 그러나 차단은 아니다

    broken = doctor(config(["gh@1.0.0"]), registry())
    assert [f.issue for f in broken.blocking] == ["deprecated"]


def test_all_ok_report():
    r = doctor(config(["gh@2.0.0", "ctx@1.0.0"]), registry())
    assert r.ok is True and r.blocking == []
    assert r.summary() == {"ok": 2}


def test_empty_config_notes():
    r = doctor(config([]), registry())
    assert r.ok is True and r.notes


# ── --fix 의 안전 경계 ──


def test_apply_suggestions_upgrades_same_id():
    cfg = config(["gh@1.5.0"])
    fixed = apply_suggestions(cfg, doctor(cfg, registry()))
    assert [s.ref for s in fixed.components] == ["gh@2.0.0"]
    assert [s.ref for s in cfg.components] == ["gh@1.5.0"]  # 원본 불변


def test_apply_suggestions_refuses_cross_component_replacement():
    """능력이 겹쳐도 config 계약이 다르다 — 말없이 바꾸면 조용히 깨진다. 제안만 남긴다."""
    cfg = config(["old-notify@1.0.0"])
    report = doctor(cfg, registry())
    assert report.findings[0].suggested_ref == "slack@3.0.0"  # 제안은 한다
    assert apply_suggestions(cfg, report).components[0].ref == "old-notify@1.0.0"  # 적용은 안 한다


def test_apply_suggestions_preserves_component_config():
    """버전만 바꾸고 config 오버라이드는 보존해야 한다."""
    cfg = HarnessConfig(
        metadata=HarnessMetadata(id="bot"),
        components=[ComponentSelection(ref="gh@1.5.0", config={"repo_filter": "org/*"})],
    )
    fixed = apply_suggestions(cfg, doctor(cfg, registry()))
    assert fixed.components[0].ref == "gh@2.0.0"
    assert fixed.components[0].config == {"repo_filter": "org/*"}

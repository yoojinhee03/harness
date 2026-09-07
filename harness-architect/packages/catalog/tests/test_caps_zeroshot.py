"""제로샷 caps 분류기 — 결정성·임계값·억지태깅 금지 (하드닝 TASK 3 인프라).

주의: 이 분류기는 기본 sync 파이프라인에 **연결하지 않는다** — LocalEmbedder 정밀도가 부족해
거짓 충족 위험이 있다(eval_zeroshot 로 스냅샷에서 측정). 활성화는 semantic 임베더(OpenAI) + 보정 후.
"""

from __future__ import annotations

from harness_catalog.caps_zeroshot import zeroshot_classifier


def test_deterministic() -> None:
    clf = zeroshot_classifier(threshold=0.1, top_n=2)
    items = [("x", "github repository pull request code review commit 저장소 커밋")]
    assert clf(items) == clf(items)  # 같은 입력 → 같은 출력(고정 임베더)


def test_high_threshold_no_forced_tagging() -> None:
    clf = zeroshot_classifier(threshold=0.99, top_n=2)
    assert clf([("x", "some vague description")]) == {}  # 임계값 높으면 억지 태깅 안 함


def test_empty_items() -> None:
    assert zeroshot_classifier()([]) == {}


def test_top_n_caps_limit() -> None:
    clf = zeroshot_classifier(threshold=0.0, top_n=2)  # 임계값 0 → 항상 배정, 개수만 제한
    caps = clf([("x", "github git repository")]).get("x", [])
    assert 0 < len(caps) <= 2  # top_n 상한 준수

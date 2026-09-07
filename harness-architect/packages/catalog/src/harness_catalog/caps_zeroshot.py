"""제로샷 능력 태깅 — LLM 없이 통제어휘 임베딩 코사인으로 caps 분류(하드닝 TASK 3).

휴리스틱(키워드 정확매칭)이 놓친 빈 caps 컴포넌트를 통제어휘와의 임베딩 유사도로 채운다.
`CapabilityClassifier` 규약을 만족하므로 기존 `CapabilityEnricher` 에 그대로 꽂힌다(LLM 분류기 대체/선행).

**결정성 제약(중요)**: caps 분류 임베더는 **서빙 임베더와 분리·고정**한다. 서빙 임베더는 런타임 등록
키(OpenAI/Local)로 바뀌는데, caps 가 그에 의존하면 "키 등록"만으로 전체 재태깅+gap 판정 이동이 난다.
따라서 여기선 항상 `LocalEmbedder`(키 무관·결정적)를 기본으로 쓴다(명시 embedder 로 핀 교체 가능).

**정밀도 주의**: LocalEmbedder 는 표면 문자(트라이그램) 기반이라 의미 동의어가 약하고 헛매칭이 있다
(예: OpenSearch 의 'search'). 그래서 임계값을 **보수적으로** 잡고, 휴리스틱 caps 는 덮지 않고
**빈 것만 보완**한다("거짓 gap 을 줄이려다 거짓 충족을 만들면 더 나쁘다"). 임계값 보정 근거는
`scripts/eval_zeroshot.py` 로 스냅샷에서 측정한다.
"""

from __future__ import annotations

from .embeddings import Embedder, LocalEmbedder, cosine
from .enrichment import CapabilityClassifier
from .vocabulary import CAPABILITY_VOCAB

# 보수적 기본 임계값 — LocalEmbedder 헛매칭을 억제(스냅샷 측정으로 보정, eval_zeroshot.py).
DEFAULT_THRESHOLD = 0.35
DEFAULT_TOP_N = 2


def _vocab_doc(cap: str) -> str:
    """통제어휘 항목 → 임베딩 텍스트(cap 명 + 키워드). measure_caps 와 동일 규약."""
    _facet, keywords = CAPABILITY_VOCAB[cap]
    return cap.replace(".", " ").replace("-", " ") + " " + " ".join(keywords)


def zeroshot_classifier(
    threshold: float = DEFAULT_THRESHOLD,
    top_n: int = DEFAULT_TOP_N,
    embedder: Embedder | None = None,
) -> CapabilityClassifier:
    """(id, text) 목록 → {id: [cap]} 분류기. 고정 임베더로 통제어휘와 코사인, 임계값 위 top_n.

    embedder 미지정 시 LocalEmbedder(결정적·키 무관). 임계값 미만이면 그 컴포넌트는 비운다(억지 태깅 금지).
    """
    emb = embedder or LocalEmbedder()
    caps = list(CAPABILITY_VOCAB)
    cap_vecs = emb.embed([_vocab_doc(c) for c in caps])

    def classify(items: list[tuple[str, str]]) -> dict[str, list[str]] | None:
        if not items:
            return {}
        out: dict[str, list[str]] = {}
        text_vecs = emb.embed([t for _cid, t in items])
        for (cid, _text), tv in zip(items, text_vecs, strict=True):
            scored = sorted(
                ((cosine(tv, cv), cap) for cap, cv in zip(caps, cap_vecs, strict=True)),
                key=lambda x: -x[0],
            )
            picked = [cap for score, cap in scored[:top_n] if score >= threshold]
            if picked:
                out[cid] = picked
        return out

    return classify

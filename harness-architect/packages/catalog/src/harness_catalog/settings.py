"""RAG 설정 일원화 — 환경변수에서 모드·모델명을 읽는다. 개발: 기술 스택 §2·§4.

키가 없으면 자동으로 로컬 폴백. 명시 모드로 강제도 가능(테스트·재현).
  HARNESS_EMBEDDER = auto | local | openai   (auto = OPENAI_API_KEY 있으면 openai)
  HARNESS_RANKER   = auto | heuristic | claude (auto = ANTHROPIC_API_KEY 있으면 claude)
  HARNESS_OPENAI_EMBED_MODEL = 임베딩 모델(기본 text-embedding-3-small)
  HARNESS_CLAUDE_MODEL       = 추출·랭킹 근거 모델(기본 claude-sonnet-5)
  HARNESS_RELEVANCE_FLOOR    = 추천 카드 관련성 하한(기본 0.20 — 임베더 교체 시 재보정)

라이브 카탈로그(공식 MCP 레지스트리 실시간 연동) — 기본 off, 옵트인.
  HARNESS_LIVE_REGISTRY   = off | on   (on 이면 공식 레지스트리를 런타임에 물림)
  HARNESS_REGISTRY_URL    = 레지스트리 베이스 URL(기본: registry.modelcontextprotocol.io)
  HARNESS_REGISTRY_TTL    = 캐시 신선도 초(기본 300 — REST 폴링이라 이 주기로 실시간 갱신)
  HARNESS_REGISTRY_MAX_PAGES = 페이지네이션 상한(기본 50 — 절단 시 경고 로그)
  HARNESS_REGISTRY_ENRICH_MAX = caps 빈 컴포넌트 LLM 보강 상한(기본 150, 0=끔; ANTHROPIC_API_KEY 있을 때만)
  HARNESS_MARKETPLACE     = off | on   (on 이면 Claude Code 플러그인 마켓플레이스를 non-mcp 타입 소스로 물림)
  HARNESS_MARKETPLACE_URL = 마켓플레이스 marketplace.json URL(기본: anthropics/claude-plugins-official)
  HARNESS_SKILLSMP       = off | on   (on 이면 SkillsMP 를 skill 타입 소스로 물림)
  HARNESS_SKILLSMP_KEY   = SkillsMP API 키(선택 — 익명 50 req/day → 인증 500 req/day)
  HARNESS_SKILLSMP_MAX_QUERIES = 통제어휘 질의 수 상한(기본 8 — 익명 쿼터 안)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .llm import DEFAULT_CLAUDE_MODEL

# 추천 카드 관련성 하한의 기본값. LocalEmbedder 실측(시드 카탈로그): 연관 컴포넌트 ≥0.27,
# 무관 도메인 잡음 ≤0.15 → 0.20 이 경계. recommender 가 이 값을 기본으로 쓴다.
DEFAULT_RELEVANCE_FLOOR = 0.20


@dataclass(frozen=True)
class Settings:
    anthropic_key: str | None
    embedder_mode: str  # auto | local | openai
    ranker_mode: str  # auto | heuristic | claude
    claude_model: str
    # OpenAI(임베딩/LLM) — 기본값과 함께 끝에 추가(기존 kwargs 생성 무파손).
    openai_key: str | None = None
    openai_embed_model: str = "text-embedding-3-small"
    # 라이브 카탈로그(공식 MCP 레지스트리) — 기본값과 함께 끝에 추가(기존 kwargs 생성 무파손).
    live_registry_mode: str = "off"  # off | on
    registry_url: str = "https://registry.modelcontextprotocol.io"
    registry_ttl: float = 300.0
    registry_max_pages: int = 50
    registry_enrich_max: int = 150  # caps 빈 컴포넌트 LLM 보강 상한(0=끔, 키 있을 때만 동작)
    marketplace_mode: str = "off"  # off | on
    marketplace_url: str = ""  # 빈 값이면 소스 기본(anthropics/claude-plugins-official)
    # SkillsMP(skill 타입 보완) — 기본 off. `q` 필수·익명 50 req/day 라 열거가 아니라 질의형이고,
    # 질의 수를 어휘 크기가 아니라 이 상한으로 묶어 쿼터를 예측 가능하게 만든다.
    skillsmp_mode: str = "off"  # off | on
    skillsmp_key: str | None = None
    skillsmp_max_queries: int = 8
    catalog_sync_interval: int = 3600  # harvest→DB 주기(초, 기본 1h). 증분이 싸서 자주 돌려 신선도↑
    catalog_full_interval: int = 86400  # 전체 대조(full reconcile) 주기(초, 기본 24h). 드리프트 정리
    # 제로샷 caps 태깅(TASK 3) — 기본 off. 켜려면 **semantic 임베더(OpenAI 키)** 필요(LocalEmbedder 는
    # 정밀도 부족으로 스킵). 활성화 전 eval_zeroshot.py 로 threshold 를 재보정할 것.
    caps_zeroshot_mode: str = "off"  # off | on
    caps_zeroshot_threshold: float = 0.35
    # 추천 카드로 남길 임베딩 유사도 하한. **절대 임계값이라 임베더를 바꾸면 재보정 대상**이고,
    # 임베더는 HARNESS_EMBEDDER 로 런타임에 갈리므로 이것도 함께 조정 가능해야 한다.
    # (gap 판정은 통제어휘 정합이라 이 값과 무관 — 여기 오보정은 잡음 카드 표시 이슈일 뿐.)
    relevance_floor: float = DEFAULT_RELEVANCE_FLOOR

    @property
    def use_live_registry(self) -> bool:
        return self.live_registry_mode == "on"

    @property
    def use_marketplace(self) -> bool:
        return self.marketplace_mode == "on"

    @property
    def use_skillsmp(self) -> bool:
        return self.skillsmp_mode == "on"

    @property
    def use_caps_zeroshot(self) -> bool:
        return self.caps_zeroshot_mode == "on"

    @property
    def embedder_choice(self) -> str:
        """임베더 선택: local | openai (Voyage 제거). 명시 모드 우선, auto 는 openai_key 있으면 openai."""
        if self.embedder_mode in ("local", "openai"):
            return self.embedder_mode
        return "openai" if self.openai_key else "local"

    @property
    def use_claude(self) -> bool:
        if self.ranker_mode == "heuristic":
            return False
        if self.ranker_mode == "claude":
            return True
        return bool(self.anthropic_key)  # auto


def load_settings() -> Settings:
    return Settings(
        anthropic_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        openai_key=os.environ.get("OPENAI_API_KEY") or None,
        openai_embed_model=os.environ.get("HARNESS_OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        embedder_mode=os.environ.get("HARNESS_EMBEDDER", "auto"),
        ranker_mode=os.environ.get("HARNESS_RANKER", "auto"),
        claude_model=os.environ.get("HARNESS_CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
        live_registry_mode=os.environ.get("HARNESS_LIVE_REGISTRY", "off"),
        registry_url=os.environ.get("HARNESS_REGISTRY_URL", "https://registry.modelcontextprotocol.io"),
        registry_ttl=float(os.environ.get("HARNESS_REGISTRY_TTL", "300")),
        registry_max_pages=int(os.environ.get("HARNESS_REGISTRY_MAX_PAGES", "50")),
        registry_enrich_max=int(os.environ.get("HARNESS_REGISTRY_ENRICH_MAX", "150")),
        marketplace_mode=os.environ.get("HARNESS_MARKETPLACE", "off"),
        marketplace_url=os.environ.get("HARNESS_MARKETPLACE_URL", ""),
        skillsmp_mode=os.environ.get("HARNESS_SKILLSMP", "off"),
        skillsmp_key=os.environ.get("HARNESS_SKILLSMP_KEY") or None,
        skillsmp_max_queries=int(os.environ.get("HARNESS_SKILLSMP_MAX_QUERIES", "8")),
        catalog_sync_interval=int(os.environ.get("HARNESS_CATALOG_SYNC_INTERVAL", "3600")),
        catalog_full_interval=int(os.environ.get("HARNESS_CATALOG_FULL_INTERVAL", "86400")),
        caps_zeroshot_mode=os.environ.get("HARNESS_CAPS_ZEROSHOT", "off"),
        caps_zeroshot_threshold=float(os.environ.get("HARNESS_CAPS_ZEROSHOT_THRESHOLD", "0.35")),
        relevance_floor=float(os.environ.get("HARNESS_RELEVANCE_FLOOR", str(DEFAULT_RELEVANCE_FLOOR))),
    )

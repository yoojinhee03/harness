"""RAG 설정 일원화 — 환경변수에서 모드·모델명을 읽는다. 개발: 기술 스택 §2·§4.

키가 없으면 자동으로 로컬 폴백. 명시 모드로 강제도 가능(테스트·재현).
  HARNESS_EMBEDDER = auto | local | voyage
  HARNESS_RANKER   = auto | heuristic | claude

라이브 카탈로그(공식 MCP 레지스트리 실시간 연동) — 기본 off, 옵트인.
  HARNESS_LIVE_REGISTRY   = off | on   (on 이면 공식 레지스트리를 런타임에 물림)
  HARNESS_REGISTRY_URL    = 레지스트리 베이스 URL(기본: registry.modelcontextprotocol.io)
  HARNESS_REGISTRY_TTL    = 캐시 신선도 초(기본 300 — REST 폴링이라 이 주기로 실시간 갱신)
  HARNESS_REGISTRY_MAX_PAGES = 페이지네이션 상한(기본 50 — 절단 시 경고 로그)
  HARNESS_REGISTRY_ENRICH_MAX = caps 빈 컴포넌트 LLM 보강 상한(기본 150, 0=끔; ANTHROPIC_API_KEY 있을 때만)
  HARNESS_MARKETPLACE     = off | on   (on 이면 Claude Code 플러그인 마켓플레이스를 non-mcp 타입 소스로 물림)
  HARNESS_MARKETPLACE_URL = 마켓플레이스 marketplace.json URL(기본: anthropics/claude-plugins-official)
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_key: str | None
    voyage_key: str | None
    embedder_mode: str  # auto | local | voyage
    ranker_mode: str  # auto | heuristic | claude
    embed_model: str
    claude_model: str
    # 라이브 카탈로그(공식 MCP 레지스트리) — 기본값과 함께 끝에 추가(기존 kwargs 생성 무파손).
    live_registry_mode: str = "off"  # off | on
    registry_url: str = "https://registry.modelcontextprotocol.io"
    registry_ttl: float = 300.0
    registry_max_pages: int = 50
    registry_enrich_max: int = 150  # caps 빈 컴포넌트 LLM 보강 상한(0=끔, 키 있을 때만 동작)
    marketplace_mode: str = "off"  # off | on
    marketplace_url: str = ""  # 빈 값이면 소스 기본(anthropics/claude-plugins-official)
    catalog_sync_interval: int = 3600  # harvest→DB 주기(초, 기본 1h). 증분이 싸서 자주 돌려 신선도↑
    catalog_full_interval: int = 86400  # 전체 대조(full reconcile) 주기(초, 기본 24h). 드리프트 정리

    @property
    def use_live_registry(self) -> bool:
        return self.live_registry_mode == "on"

    @property
    def use_marketplace(self) -> bool:
        return self.marketplace_mode == "on"

    @property
    def use_voyage(self) -> bool:
        if self.embedder_mode == "local":
            return False
        if self.embedder_mode == "voyage":
            return True
        return bool(self.voyage_key)  # auto

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
        voyage_key=os.environ.get("VOYAGE_API_KEY") or None,
        embedder_mode=os.environ.get("HARNESS_EMBEDDER", "auto"),
        ranker_mode=os.environ.get("HARNESS_RANKER", "auto"),
        embed_model=os.environ.get("HARNESS_EMBED_MODEL", "voyage-3.5"),
        claude_model=os.environ.get("HARNESS_CLAUDE_MODEL", "claude-sonnet-5"),
        live_registry_mode=os.environ.get("HARNESS_LIVE_REGISTRY", "off"),
        registry_url=os.environ.get("HARNESS_REGISTRY_URL", "https://registry.modelcontextprotocol.io"),
        registry_ttl=float(os.environ.get("HARNESS_REGISTRY_TTL", "300")),
        registry_max_pages=int(os.environ.get("HARNESS_REGISTRY_MAX_PAGES", "50")),
        registry_enrich_max=int(os.environ.get("HARNESS_REGISTRY_ENRICH_MAX", "150")),
        marketplace_mode=os.environ.get("HARNESS_MARKETPLACE", "off"),
        marketplace_url=os.environ.get("HARNESS_MARKETPLACE_URL", ""),
        catalog_sync_interval=int(os.environ.get("HARNESS_CATALOG_SYNC_INTERVAL", "3600")),
        catalog_full_interval=int(os.environ.get("HARNESS_CATALOG_FULL_INTERVAL", "86400")),
    )

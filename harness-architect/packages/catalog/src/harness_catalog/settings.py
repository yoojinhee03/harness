"""RAG 설정 일원화 — 환경변수에서 모드·모델명을 읽는다. 개발: 기술 스택 §2·§4.

키가 없으면 자동으로 로컬 폴백. 명시 모드로 강제도 가능(테스트·재현).
  HARNESS_EMBEDDER = auto | local | voyage
  HARNESS_RANKER   = auto | heuristic | claude
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
    )

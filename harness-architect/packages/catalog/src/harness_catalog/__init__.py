"""harness_catalog — 카탈로그 엔진 + RAG (로딩·임베딩·검색·랭킹·추천).

RAG 엔진 *코드* 는 백엔드에 잔류하고, 컴포넌트 *데이터* 는 별도 폴더(harness-catalog)다.
"""

from __future__ import annotations

from .embeddings import Embedder, LocalEmbedder, VoyageEmbedder, get_embedder
from .loader import build_registry, load_components, resolve_catalog_dir
from .ranking import RankedComponent, rank
from .reasoning import ClaudeReasoner, NullReasoner, Reasoner, get_reasoner
from .recommender import Recommendation, Recommender, RecommendResult
from .settings import Settings, load_settings
from .store import VectorStore
from .vocabulary import CAPABILITY_VOCAB, extract_capabilities_heuristic

__all__ = [
    "CAPABILITY_VOCAB",
    "ClaudeReasoner",
    "Embedder",
    "LocalEmbedder",
    "NullReasoner",
    "RankedComponent",
    "Reasoner",
    "RecommendResult",
    "Recommendation",
    "Recommender",
    "Settings",
    "VectorStore",
    "VoyageEmbedder",
    "build_registry",
    "extract_capabilities_heuristic",
    "get_embedder",
    "get_reasoner",
    "load_components",
    "load_settings",
    "rank",
    "resolve_catalog_dir",
]

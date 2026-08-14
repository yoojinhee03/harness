"""harness_catalog — 카탈로그 엔진 + RAG (로딩·임베딩·검색·랭킹·추천).

RAG 엔진 *코드* 는 백엔드에 잔류하고, 컴포넌트 *데이터* 는 별도 폴더(harness-catalog)다.
"""

from __future__ import annotations

from .embeddings import Embedder, LocalEmbedder, OpenAIEmbedder, get_embedder
from .enrichment import CapabilityClassifier, CapabilityEnricher, claude_classifier, get_classifier
from .harvest import ServerDescriptor, component_to_yaml, harvest, harvest_component, uncovered
from .loader import build_registry, load_components, resolve_catalog_dir
from .ranking import RankedComponent, rank
from .reasoning import ClaudeReasoner, NullReasoner, Reasoner, get_reasoner
from .recommender import LiveRecommender, Recommendation, Recommender, RecommendResult
from .registry_source import (
    DEFAULT_MARKETPLACE_URL,
    DEFAULT_REGISTRY_URL,
    FederatedRegistry,
    Fetcher,
    LiveSource,
    MarketplaceSource,
    MCPRegistrySource,
    build_live_sources,
    descriptor_from_entry,
    federate,
    plugin_to_component,
    urllib_fetcher,
)
from .settings import Settings, load_settings
from .store import VectorStore
from .vocabulary import CAPABILITY_VOCAB, extract_capabilities_heuristic

__all__ = [
    "CAPABILITY_VOCAB",
    "DEFAULT_MARKETPLACE_URL",
    "DEFAULT_REGISTRY_URL",
    "CapabilityClassifier",
    "CapabilityEnricher",
    "ClaudeReasoner",
    "Embedder",
    "FederatedRegistry",
    "Fetcher",
    "LiveRecommender",
    "LiveSource",
    "MarketplaceSource",
    "LocalEmbedder",
    "MCPRegistrySource",
    "NullReasoner",
    "RankedComponent",
    "Reasoner",
    "RecommendResult",
    "Recommendation",
    "Recommender",
    "ServerDescriptor",
    "Settings",
    "VectorStore",
    "OpenAIEmbedder",
    "build_live_sources",
    "build_registry",
    "claude_classifier",
    "component_to_yaml",
    "descriptor_from_entry",
    "extract_capabilities_heuristic",
    "federate",
    "get_classifier",
    "get_embedder",
    "get_reasoner",
    "plugin_to_component",
    "harvest",
    "harvest_component",
    "load_components",
    "load_settings",
    "rank",
    "resolve_catalog_dir",
    "uncovered",
    "urllib_fetcher",
]

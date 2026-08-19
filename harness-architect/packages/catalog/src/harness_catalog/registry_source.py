"""공식 MCP 레지스트리 라이브 연동 — registry.modelcontextprotocol.io 를 런타임에 물려 카탈로그 확장.

스냅샷 YAML 로 굽지 않고 **실시간(TTL 폴링)** 으로 연동한다. 손큐레이션 컴포넌트(로컬)와 라이브
레지스트리를 `FederatedRegistry` 로 합쳐 `Registry` 프로토콜(get/all/get_base)로 노출 →
리졸버·추천기·이젝트가 그대로 사용한다. 매핑은 기존 `harvest_component` 을 재사용한다
(레지스트리 서버 엔트리 → `ServerDescriptor` → `Component`).

설계 원칙(레포 이토스와 정합):
- 오프라인 완주: 네트워크 실패 시 마지막 캐시(또는 로컬만)로 폴백, 절대 크래시 금지.
- 신규 의존성 0: stdlib `urllib`. 테스트는 `Fetcher` 주입(네트워크 없음) — anthropic/voyage 주입 패턴과 동일.
- 옵트인: `HARNESS_LIVE_REGISTRY=on` 일 때만. 기본 off → 테스트·오프라인 결정성 유지.
- 로컬 우선: id 충돌 시 손큐레이션 컴포넌트가 라이브를 이긴다.

공식 레지스트리는 REST(푸시 없음)라 "실시간" 은 TTL 폴링으로 구현한다(`HARNESS_REGISTRY_TTL`, 기본 300s).
API: `GET /v0/servers?limit=&cursor=` (read 는 인증 불필요), `metadata.nextCursor` 커서 페이지네이션.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any, Protocol

from harness_resolver import Component, HarnessConfig, Registry
from harness_resolver.models import ComponentType

from .enrichment import CapabilityEnricher
from .harvest import ServerDescriptor, harvest_component
from .settings import Settings, load_settings
from .vocabulary import CAPABILITY_VOCAB, extract_capabilities_heuristic

log = logging.getLogger("harness_catalog.registry_source")

# URL → 파싱된 JSON 오브젝트. 테스트는 fake 를 주입한다(네트워크 없음).
Fetcher = Callable[[str], dict[str, Any]]

DEFAULT_REGISTRY_URL = "https://registry.modelcontextprotocol.io"
DEFAULT_MARKETPLACE_URL = (
    "https://raw.githubusercontent.com/anthropics/claude-plugins-official/main"
    "/.claude-plugin/marketplace.json"
)

# 레지스트리 package.registry_type → (러너 명령, args 접두). 미지 타입은 npx 로 가정.
_RUNNERS: dict[str, tuple[str, list[str]]] = {
    "npm": ("npx", ["-y"]),
    "pypi": ("uvx", []),
    "oci": ("docker", ["run", "-i", "--rm"]),
    "nuget": ("dnx", []),
}


def urllib_fetcher(timeout: float = 10.0) -> Fetcher:
    """stdlib 기반 기본 fetcher. https 만 허용(레지스트리는 공개 HTTPS)."""

    def _fetch(url: str) -> dict[str, Any]:
        if not url.startswith("https://"):
            raise ValueError(f"https 아닌 레지스트리 URL 거부: {url}")
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "harness-architect/0.1"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — https 강제 위에서 검증
            payload = json.loads(resp.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("레지스트리 응답이 JSON 오브젝트가 아님")
        return payload

    return _fetch


def _official_meta(entry: dict[str, Any]) -> dict[str, Any]:
    """엔트리의 official 레지스트리 메타 서브오브젝트(status·isLatest 등)를 방어적으로 찾는다."""
    meta = entry.get("_meta")
    if not isinstance(meta, dict):
        return {}
    for key, value in meta.items():
        if "official" in key and isinstance(value, dict):
            return value
    return {}


def _package_command(pkg: dict[str, Any]) -> tuple[str, list[str], dict[str, str]]:
    """레지스트리 package 스펙 → (command, args, env). registry_type 으로 러너를 고른다."""
    rtype = str(pkg.get("registry_type") or pkg.get("registryType") or "npm").lower()
    identifier = str(pkg.get("identifier") or pkg.get("name") or "").strip()
    runner, prefix = _RUNNERS.get(rtype, ("npx", ["-y"]))
    args = [*prefix, identifier] if identifier else list(prefix)
    env: dict[str, str] = {}
    for ev in pkg.get("environment_variables") or pkg.get("environmentVariables") or []:
        if isinstance(ev, dict) and ev.get("name"):
            env[str(ev["name"])] = str(ev.get("value") or "")
    return runner, args, env


def descriptor_from_entry(entry: dict[str, Any]) -> ServerDescriptor | None:
    """레지스트리 서버 엔트리 → ServerDescriptor. 최신·활성만 통과(deleted/구버전 스킵).

    실제 API 는 항목을 `{"server": {...}, "_meta": {...}}` 로 감싼다(서버 필드는 `server` 아래,
    상태는 형제 `_meta` 아래). 평면 형태(서브레지스트리·테스트)도 그대로 받도록 언랩한다.
    """
    official = _official_meta(entry)  # _meta 는 래퍼 레벨(서버 필드의 형제)
    if official.get("isLatest") is False:  # 목록은 전 버전을 주고 isLatest 로 최신을 표시 → 구버전 스킵
        return None
    status = official.get("status")
    if status not in (None, "active"):  # deleted/deprecated 등 → 스킵
        return None

    raw_srv = entry.get("server")
    srv: dict[str, Any] = raw_srv if isinstance(raw_srv, dict) else entry
    name = srv.get("name")
    if not name:
        return None

    desc = ServerDescriptor(
        id=str(name),
        name=str(srv.get("title") or name),
        description=str(srv.get("description") or ""),
        version=str(srv.get("version") or "0.1.0"),
    )

    # 실행 스펙: remote(url) 우선, 없으면 package → stdio 명령.
    remotes = srv.get("remotes")
    if isinstance(remotes, list) and remotes:
        first = remotes[0]
        url = first.get("url") if isinstance(first, dict) else None
        if url:
            desc.url = str(url)
            return desc

    packages = srv.get("packages")
    if isinstance(packages, list) and packages and isinstance(packages[0], dict):
        desc.command, desc.args, desc.env = _package_command(packages[0])
    return desc


def _max_updated(entry: dict[str, Any], current: str | None) -> str | None:
    """엔트리의 상류 updatedAt 과 현재 워터마크 중 큰 값(ISO 문자열 사전식 비교=UTC 시간순)."""
    ua = _official_meta(entry).get("updatedAt")
    if ua and (current is None or str(ua) > current):
        return str(ua)
    return current


def classify_entry(entry: dict[str, Any]) -> tuple[str, str, Component | None] | None:
    """레지스트리 엔트리 분류 → ('upsert', id, Component) | ('delete', id, None) | None(무시).

    최신(isLatest) 활성 → upsert. 최신 deleted/deprecated → delete. 구버전(isLatest=false) → 무시.
    증분 sync 는 upsert·delete 를 모두 처리하고, full sync 는 upsert 만 쓴다(삭제는 전체 교체로 처리).
    """
    official = _official_meta(entry)
    if official.get("isLatest") is False:  # 구버전 → 무시
        return None
    srv = entry.get("server") if isinstance(entry.get("server"), dict) else entry
    name = srv.get("name") if isinstance(srv, dict) else None
    if not name:
        return None
    if official.get("status") not in (None, "active"):  # deleted/deprecated → 삭제
        return ("delete", str(name), None)
    desc = descriptor_from_entry(entry)  # active+latest → 정상 파싱
    if desc is None:
        return None
    return ("upsert", str(name), harvest_component(desc))


class LiveSource(Protocol):
    """라이브 카탈로그 소스 — `components()` 로 현재 컴포넌트 스냅샷을 준다."""

    def components(self) -> list[Component]: ...


class _TTLSource:
    """TTL 캐시 + 오프라인 폴백 + (옵션) capability 보강 공통 베이스. 서브클래스는 `_fetch_all` 구현.

    `components()` 는 TTL 내엔 캐시를, 만료 시 재페치한다. 페치 실패는 마지막 캐시로 폴백하고
    실패 시각도 스탬프해 매 호출 재시도 폭주를 막는다(TTL 백오프). 스레드 안전은 목표 아님
    — 앱은 startup 에 워밍하고 프로세스당 한 인스턴스를 공유한다.
    """

    _label = "라이브 소스"
    supports_delta = False  # True 면 fetch_delta(updated_since) 로 증분 harvest 가능

    def __init__(
        self,
        fetcher: Fetcher | None,
        ttl_seconds: float,
        clock: Callable[[], float],
        enricher: CapabilityEnricher | None,
    ) -> None:
        self._fetch = fetcher or urllib_fetcher()
        self._ttl = ttl_seconds
        self._clock = clock
        self._enricher = enricher  # None 이면 무보강(휴리스틱 caps 유지)
        self._cache: list[Component] = []
        self._fetched_at: float | None = None
        self.last_watermark: str | None = None  # 마지막 full 페치에서 본 상류 updatedAt 최대치

    def _fresh(self) -> bool:
        return self._fetched_at is not None and (self._clock() - self._fetched_at) < self._ttl

    def components(self) -> list[Component]:
        """현재 라이브 컴포넌트(TTL 캐시). 실패 시 마지막 캐시로 폴백, 크래시하지 않는다."""
        if self._fresh():
            return self._cache
        try:
            fetched = self._fetch_all()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning("%s 페치 실패 — 캐시(%d개)로 폴백: %s", self._label, len(self._cache), exc)
            self._fetched_at = self._clock()  # 실패도 스탬프 → 재시도 폭주 방지
            return self._cache
        if self._enricher is not None and self._enricher.active:
            fetched = self._enricher.enrich(fetched)  # caps 빈 것 LLM 보강(키 있을 때만)
        self._cache = fetched
        self._fetched_at = self._clock()
        return fetched

    def _fetch_all(self) -> list[Component]:
        raise NotImplementedError


class MCPRegistrySource(_TTLSource):
    """공식 MCP 레지스트리 라이브 소스 — `/v0/servers` 커서 페이지네이션."""

    _label = "MCP 레지스트리"
    origin = "registry"  # DB 적재 시 origin 태그(catalog_store.sync_catalog)
    supports_delta = True  # updated_since 로 증분 harvest 지원

    def __init__(
        self,
        base_url: str = DEFAULT_REGISTRY_URL,
        fetcher: Fetcher | None = None,
        ttl_seconds: float = 300.0,
        page_limit: int = 100,
        max_pages: int = 50,
        clock: Callable[[], float] = time.monotonic,
        enricher: CapabilityEnricher | None = None,
    ) -> None:
        super().__init__(fetcher, ttl_seconds, clock, enricher)
        self._base = base_url.rstrip("/")
        self._page_limit = page_limit
        self._max_pages = max_pages

    def _paged(self, extra: str = "") -> Iterator[dict[str, Any]]:
        """/v0/servers 를 커서 페이지네이션하며 서버 엔트리를 순회. extra 는 추가 쿼리(예: updated_since)."""
        cursor: str | None = None
        pages = 0
        while pages < self._max_pages:
            url = f"{self._base}/v0/servers?limit={self._page_limit}{extra}"
            if cursor:
                url += f"&cursor={urllib.parse.quote(cursor, safe='')}"
            data = self._fetch(url)
            for entry in data.get("servers") or []:
                if isinstance(entry, dict):
                    yield entry
            pages += 1
            metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            cursor = metadata.get("nextCursor") if metadata else None
            if not cursor:
                return
        log.warning("MCP 레지스트리 %d페이지에서 절단(max_pages=%d, 커서 잔존)", pages, self._max_pages)

    def _fetch_all(self) -> list[Component]:
        components: list[Component] = []
        seen: set[str] = set()
        watermark: str | None = None
        for entry in self._paged():
            watermark = _max_updated(entry, watermark)
            cl = classify_entry(entry)
            if cl is None or cl[0] != "upsert" or cl[1] in seen or cl[2] is None:
                continue
            seen.add(cl[1])
            components.append(cl[2])
        self.last_watermark = watermark
        log.info("MCP 레지스트리 full: %d개 수집", len(components))
        return components

    def fetch_delta(self, updated_since: str) -> tuple[list[Component], list[str], str | None]:
        """updated_since 이후 바뀐 것만 → (upserts, deleted_ids, watermark). id별 마지막 분류가 이김."""
        changes: dict[str, tuple[str, Component | None]] = {}
        watermark: str | None = None
        extra = f"&updated_since={urllib.parse.quote(updated_since, safe='')}"
        for entry in self._paged(extra):
            watermark = _max_updated(entry, watermark)
            cl = classify_entry(entry)
            if cl is not None:
                changes[cl[1]] = (cl[0], cl[2])
        upserts = [c for kind, c in changes.values() if kind == "upsert" and c is not None]
        deletes = [cid for cid, (kind, _) in changes.items() if kind == "delete"]
        if self._enricher is not None and self._enricher.active:
            upserts = self._enricher.enrich(upserts)
        log.info("MCP 레지스트리 delta(since %s): +%d / -%d", updated_since, len(upserts), len(deletes))
        return upserts, deletes, watermark


# ── 플러그인 마켓플레이스(non-mcp 타입 소스) ──
_MCP_DESC_HINTS = ("mcp server", "mcp access", "bundles the official")
_HOOK_DESC_HINTS = ("hook", " monitor", "guardrail")
# context 감지 — 배경지식(knowledge)·프롬프트 조각(prompt) facet. 실행 마커가 없고 추출된 능력이
# 이 facet 들뿐이면 규칙·컨벤션·프롬프트 프리앰블 번들로 보고 context 로 분류한다.
_CONTEXT_FACETS = frozenset({"knowledge", "prompt"})


def _cap_facets(caps: list[str]) -> set[str]:
    """능력 id 목록 → facet 집합(어휘 미등록 능력은 무시)."""
    return {CAPABILITY_VOCAB[c][0] for c in caps if c in CAPABILITY_VOCAB}


def _source_url(source: Any) -> str | None:
    """marketplace source(문자열 로컬 경로 · {url,...} 오브젝트) → 출처 URL/경로."""
    if isinstance(source, str):
        return source
    if isinstance(source, dict):
        url = source.get("url")
        return str(url) if url else None
    return None


def _plugin_type(plugin: dict[str, Any], caps: list[str]) -> ComponentType:
    """플러그인이 선언한 배열·설명·능력 facet 으로 카탈로그 타입을 추론(subagent 는 skill 로 흡수)."""
    if isinstance(plugin.get("mcpServers"), dict):
        return "mcp"
    if plugin.get("hooks"):
        return "hook"
    if plugin.get("skills") or plugin.get("commands"):
        return "skill"
    desc = str(plugin.get("description") or "").lower()
    if any(h in desc for h in _MCP_DESC_HINTS):
        return "mcp"
    if any(h in desc for h in _HOOK_DESC_HINTS):
        return "hook"
    # 실행 마커가 없을 때: 가장 강한 능력 신호(top cap)의 facet 이 배경지식/프롬프트면 context —
    # 규칙·컨벤션·프롬프트 조각 번들. top 만 보므로 짧은 키워드의 약한 부수 매치 노이즈에 강하다.
    top_facet = _cap_facets(caps[:1])
    if top_facet and top_facet <= _CONTEXT_FACETS:
        return "context"
    return "skill"  # 기본 — 대다수 플러그인은 스킬 번들


def plugin_to_component(plugin: dict[str, Any]) -> Component | None:
    """marketplace 플러그인 엔트리 → Component(discovery 용). caps 는 휴리스틱(후속 LLM 보강 대상)."""
    name = plugin.get("name")
    if not name:
        return None
    description = str(plugin.get("description") or "")
    kw = [str(k) for k in (plugin.get("keywords") or [])]
    kw += [str(t) for t in (plugin.get("tags") or [])]
    category = plugin.get("category")
    if category:
        kw.append(str(category))
    caps = extract_capabilities_heuristic(" ".join([str(name), description, *kw]))
    return Component(
        id=str(name),
        type=_plugin_type(plugin, caps),
        name=str(plugin.get("displayName") or name),
        version=str(plugin.get("version") or "0.1.0"),
        summary=description[:120],
        description=description,
        keywords=kw,
        capability_tags=caps,
        provides=caps,
        source=_source_url(plugin.get("source")),  # 출처 레포(프로비넌스; eject 충실화는 후속)
    )


class MarketplaceSource(_TTLSource):
    """Claude Code 플러그인 마켓플레이스 소스 — `.claude-plugin/marketplace.json`(단일 파일).

    공식 anthropics/claude-plugins-official(400+ 플러그인)가 기본. skill·hook·context·mcp 를
    아우르는 non-mcp 타입 소스 = MCP 레지스트리가 못 채우는 타입을 보완한다.
    """

    _label = "플러그인 마켓플레이스"
    origin = "marketplace"  # DB 적재 시 origin 태그(catalog_store.sync_catalog)

    def __init__(
        self,
        url: str = DEFAULT_MARKETPLACE_URL,
        fetcher: Fetcher | None = None,
        ttl_seconds: float = 300.0,
        max_plugins: int = 500,
        clock: Callable[[], float] = time.monotonic,
        enricher: CapabilityEnricher | None = None,
    ) -> None:
        super().__init__(fetcher, ttl_seconds, clock, enricher)
        self._url = url
        self._max = max_plugins

    def _fetch_all(self) -> list[Component]:
        data = self._fetch(self._url)
        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            log.warning("마켓플레이스 응답에 plugins 배열 없음: %s", self._url)
            return []
        components: list[Component] = []
        seen: set[str] = set()
        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue
            comp = plugin_to_component(plugin)
            if comp is None or comp.id in seen:
                continue
            seen.add(comp.id)
            components.append(comp)
            if len(components) >= self._max:
                log.warning("마켓플레이스 %d개에서 절단(max_plugins=%d)", len(components), self._max)
                break
        log.info("플러그인 마켓플레이스: %d개 컴포넌트", len(components))
        return components


class FederatedRegistry:
    """로컬(손큐레이션) + 라이브 소스들을 합쳐 `Registry` 프로토콜로 노출. id 충돌 시 로컬 우선.

    로컬은 항상 오프라인으로 응답하고, 라이브는 TTL 캐시라 `all()`/`get()` 이 신선도 내에서
    최신 레지스트리 데이터를 반영한다 = 실시간 연동. 라이브가 죽어도 로컬은 그대로 뜬다.
    """

    def __init__(self, local: Registry, sources: list[LiveSource] | None = None) -> None:
        self._local = local
        self._sources: list[LiveSource] = sources or []

    @property
    def local(self) -> Registry:
        """로컬(손큐레이션) 레지스트리 — 라이브 페치 없이 접근(헬스체크 등 값싼 경로용)."""
        return self._local

    def _live(self) -> list[Component]:
        out: list[Component] = []
        for source in self._sources:
            out.extend(source.components())
        return out

    def get(self, component_id: str, version: str | None = None) -> Component | None:
        hit = self._local.get(component_id, version)
        if hit is not None:
            return hit
        for c in self._live():
            if c.id == component_id and (version is None or c.version == version):
                return c
        return None

    def all(self) -> list[Component]:
        local = self._local.all()
        seen = {c.id for c in local}
        merged = list(local)
        for c in self._live():
            if c.id not in seen:
                merged.append(c)
                seen.add(c.id)
        return merged

    def get_base(self, name: str) -> HarnessConfig | None:
        return self._local.get_base(name)

    def generation(self) -> int:
        """현재 컴포넌트 id 집합의 시그니처. 라이브 소스가 refresh(TTL)돼 내용이 바뀌면 값이 바뀐다.

        추천기(LiveRecommender)가 이 값 변화를 감지해 재인덱싱한다 → recommend 도 실시간 반영.
        `all()` 을 타므로 각 소스의 TTL 캐시를 존중한다(신선하면 네트워크 없음).
        """
        return hash(tuple(c.id for c in self.all()))


def build_live_sources(
    settings: Settings | None = None,
    fetcher: Fetcher | None = None,
    *,
    enricher: CapabilityEnricher | None = None,
) -> list[LiveSource]:
    """설정에 따라 라이브 소스 리스트를 만든다(공식 MCP 레지스트리 · 플러그인 마켓플레이스).

    둘 다 독립 옵트인(`HARNESS_LIVE_REGISTRY`·`HARNESS_MARKETPLACE`). 모두 off면 빈 리스트.
    enricher 를 주면 그걸 쓰고(앱 등록 키 주입 경로), 없으면 env 설정에서 만든다(무키면 무보강).
    """
    cfg = settings or load_settings()
    # 키가 있으면 caps 빈 컴포넌트를 LLM 으로 보강(없으면 enricher.active=False → 무보강). 두 소스가 공유.
    if enricher is None:
        enricher = CapabilityEnricher(settings=cfg, max_enrich=cfg.registry_enrich_max)
    sources: list[LiveSource] = []
    if cfg.use_live_registry:
        sources.append(
            MCPRegistrySource(
                base_url=cfg.registry_url,
                fetcher=fetcher,
                ttl_seconds=cfg.registry_ttl,
                max_pages=cfg.registry_max_pages,
                enricher=enricher,
            )
        )
    if cfg.use_marketplace:
        sources.append(
            MarketplaceSource(
                url=cfg.marketplace_url or DEFAULT_MARKETPLACE_URL,
                fetcher=fetcher,
                ttl_seconds=cfg.registry_ttl,
                enricher=enricher,
            )
        )
    return sources


def federate(
    local: Registry, settings: Settings | None = None, fetcher: Fetcher | None = None
) -> Registry:
    """로컬 레지스트리를 라이브 소스와 합친다. 라이브 비활성이면 로컬을 그대로 돌려준다(무비용)."""
    sources = build_live_sources(settings, fetcher)
    if not sources:
        return local
    return FederatedRegistry(local, sources)

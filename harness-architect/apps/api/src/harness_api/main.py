"""FastAPI 앱 — AI 하네스 아키텍트 백엔드.

엔드포인트 (화면 대응):
    GET  /health
    GET  /catalog                 카탈로그 목록 (화면 E)  — ?type= ?capability= 필터
    GET  /catalog/{id}            카탈로그 상세 (화면 E)
    POST /recommend               설명 → 요구 능력 + 추천 (화면 A→B)
    POST /resolve                 선택 구성 → 검증 진단 (화면 C, gap 되돌림)
    POST /generate                확정 → harness.yaml 생성 (화면 C→D)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from harness_catalog import (
    VOCAB_VERSION,
    FederatedRegistry,
    LiveRecommender,
    Recommender,
    build_registry,
    load_settings,
    resolve_catalog_dir,
)
from harness_resolver import Component, InMemoryRegistry, ResolveResult, resolve
from harness_runtime import AnthropicRunner, available_targets, build_request, emit
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

from .accounts import AccountStore
from .authoring import COMPONENT_TYPES, author_component, test_component, validate_component
from .catalog_store import CatalogStore, DbCatalogSource, sync_catalog
from .component_store import ComponentStore, UserComponentSource, component_event_stream
from .conversation_store import ConversationStore, conversation_event_stream
from .gap_demand import GapDemand
from .harness_build import parse_harness_yaml, to_harness_yaml
from .llm_client import DEFAULT_MODEL
from .llm_client import complete_json as _provider_complete_json
from .llm_client import complete_text as _provider_complete_text
from .llm_client import verify_key as _provider_verify_key
from .llm_settings import AppSettingsStore
from .observability import (
    ObservabilityMiddleware,
    configure_logging,
    db_ready,
    init_sentry,
    metrics_response,
)
from .orchestrator import run_agent as _run_agent
from .orchestrator import studio_run as _studio_run
from .orchestrator import suggest_title as _suggest_title
from .promotion import promote_component
from .schemas import (
    CatalogItem,
    ComponentAuthorBody,
    ComponentSaveBody,
    DevLoginBody,
    GenerateResponse,
    HarnessSaveBody,
    LlmSettingsBody,
    MemberBody,
    RecommendRequest,
    ResolveRequest,
    RunRequest,
    StudioChatBody,
    StudioCommitBody,
    StudioRunBody,
    TeamCreateBody,
    TokenCreateBody,
)
from .scoped_recommender import ScopedRecommender
from .store import (
    HarnessStore,
    SSEBroadcaster,
    VersionConflict,
    event_stream,
    make_broadcaster,
    resolve_store_dir,
    safe_id,
)

log = logging.getLogger("harness_api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 저장소 DB(SQL) + 계정 + SSE 브로드캐스터. DATABASE_URL 없으면 SQLite(store 폴더).
    from .db import make_engine, resolve_database_url

    init_sentry()  # SENTRY_DSN 있으면 에러 트래킹
    engine = make_engine(resolve_database_url(resolve_store_dir()))
    app.state.engine = engine
    app.state.store = HarnessStore(engine)
    app.state.component_store = ComponentStore(engine)  # 유저 저작 컴포넌트(스코프 격리)
    app.state.conversation_store = ConversationStore(engine)  # 스튜디오 대화 스레드(스코프 격리)
    app.state.app_settings = AppSettingsStore(engine)  # 앱 레벨 LLM/임베딩 키(암호화, 화면 등록)
    app.state.accounts = AccountStore(engine)
    app.state.broadcaster = make_broadcaster()  # REDIS_URL 있으면 Redis(스케일아웃)
    # OAuth CSRF state 임시 저장(state -> 생성 시각). 단일 인스턴스 개발용 — 멀티 인스턴스는 Redis/DB 로.
    app.state.oauth_states = {}
    app.state.gap_demand = GapDemand(engine)  # gap 수요 집계(DB 영속) — 저작 제안 신호
    log.info("저장소 DB: %s · 스코프 격리 · OAuth 인증", engine.url)

    # 카탈로그 — 서빙은 **DB 만** 읽어 즉시 응답한다(네트워크 무의존). 느린 harvest(레지스트리·
    # 마켓플레이스)는 백그라운드 주기 스케줄러가 DB 에 적재한다. 서빙과 harvest 를 DB 로 분리.
    cfg = load_settings()
    try:
        local = build_registry(resolve_catalog_dir())
        log.info("로컬 카탈로그 시드: %s개", len(local.all()))
    except FileNotFoundError as exc:
        log.warning("카탈로그를 찾지 못함 — 빈 레지스트리로 기동: %s", exc)
        local = InMemoryRegistry([])
    catalog_store = CatalogStore(engine)
    app.state.catalog_store = catalog_store
    harvest_on = cfg.use_live_registry or cfg.use_marketplace
    # off 면 로컬 시드만(결정적·오프라인). on 이면 로컬 + DB(harvest 결과)를 합쳐 서빙.
    registry = FederatedRegistry(local, [DbCatalogSource(catalog_store)]) if harvest_on else local
    app.state.registry = registry
    # 임베더 — 앱 등록 OpenAI 임베딩 키가 있으면 OpenAI, 없으면 Local(키 없이). 전역 인덱스라
    # 시작 시 확정한다(키 변경은 재시작으로 반영). 서버 env 는 쓰지 않는다.
    from harness_catalog import (
        CapabilityEnricher,
        ChainEnricher,
        LocalEmbedder,
        OpenAIEmbedder,
        make_classifier,
        make_reasoner,
        zeroshot_classifier,
    )

    _app_llm = AppSettingsStore(engine).resolve()
    _emb_key = _app_llm["embedding_key"]
    _provider, _llm_key = _app_llm["provider"], _app_llm["llm_key"]
    try:
        embedder = OpenAIEmbedder(api_key=_emb_key) if _emb_key else LocalEmbedder()
    except RuntimeError:  # openai 미설치 등 → 로컬 폴백
        embedder = LocalEmbedder()
    # 앱 등록 LLM 키(provider+key)를 추출·근거 reasoner 와 카탈로그 enrichment 에 주입(없으면 휴리스틱/무보강).
    # env 가 아니라 DB 등록 키를 쓰는 경로 — 키 변경은 재시작으로 반영(임베더와 동일 규약).
    reasoner = make_reasoner(_provider, _llm_key)
    # 벡터 스토어 — Postgres 면 pgvector 로 임베딩 영속(재시작 시 변경분만 재임베딩), 아니면 인메모리.
    vector_store = None
    if engine.dialect.name == "postgresql":
        from .pgvector_store import PgVectorStore

        try:
            vector_store = PgVectorStore(engine, getattr(embedder, "name", type(embedder).__name__))
            log.info("pgvector 임베딩 스토어 활성(model=%s)", getattr(embedder, "name", "?"))
        except Exception as exc:  # noqa: BLE001 — pgvector 미가용 시 인메모리로 폴백(서비스 지속)
            log.warning("pgvector 스토어 초기화 실패 — 인메모리 폴백: %s", exc)
            vector_store = None
    app.state.recommender = LiveRecommender(
        registry, embedder=embedder, reasoner=reasoner, store=vector_store
    )
    enricher: Any = CapabilityEnricher(
        classifier=make_classifier(_provider, _llm_key), max_enrich=cfg.registry_enrich_max
    )
    # TASK 3: 제로샷 caps 태깅(옵트인). semantic 임베더(OpenAI 키)가 있을 때만 활성 — LocalEmbedder 는
    # 정밀도 부족(baseline §6)이라 켜지 않는다. caps 임베더는 서빙과 **분리·고정**(결정성). 제로샷(전량,
    # 결정적) → LLM(모호한 잔여만) 순으로 체인. threshold 는 활성화 전 eval_zeroshot.py 로 재보정할 것.
    if cfg.use_caps_zeroshot and _emb_key:
        zs = CapabilityEnricher(
            classifier=zeroshot_classifier(
                threshold=cfg.caps_zeroshot_threshold, embedder=OpenAIEmbedder(api_key=_emb_key)
            ),
            max_enrich=1_000_000,
        )
        enricher = ChainEnricher([zs, enricher])
        log.info("caps 제로샷 활성(threshold=%.2f, semantic 임베더)", cfg.caps_zeroshot_threshold)
    elif cfg.use_caps_zeroshot:
        log.warning("caps 제로샷 요청됐으나 embedding 키 없음 — 정밀도 부족이라 스킵(무보강 유지)")

    async def _sync_loop() -> None:
        # 주기적으로 하이브리드 harvest→DB(증분 또는 full). 첫 기동엔 상태가 없어 즉시 1회(full),
        # 이후 sync_interval 마다 증분, full_interval(기본 24h)마다 전체 대조. due_for_sync 는 마지막
        # sync 시각(state) 기준이라 다중 레플리카 중복도 완화한다. 서빙은 이 루프와 무관하게 DB 를 읽는다.
        while True:
            try:
                if await asyncio.to_thread(catalog_store.due_for_sync, cfg.catalog_sync_interval):
                    res = await asyncio.to_thread(sync_catalog, engine, cfg, enricher=enricher)
                    total = await asyncio.to_thread(catalog_store.count)
                    log.info("카탈로그 sync 완료: %s (총 %s개)", res, total)
                    # sync 후 공급이 생긴 능력의 gap 을 resolved 로 표시(피드백 루프 — durable)
                    try:
                        provided: set[str] = set()
                        for c in registry.all():
                            provided.update(c.provides or [])
                            provided.update(c.capability_tags or [])
                        n_res = await asyncio.to_thread(app.state.gap_demand.mark_resolved, provided)
                        if n_res:
                            log.info("gap resolved 표시: %d개(공급 생김)", n_res)
                    except Exception as exc:  # noqa: BLE001 — 비차단
                        log.warning("gap resolved 표시 실패(무시): %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 실패해도 루프 유지(다음 주기 재시도)
                log.warning("카탈로그 sync 오류(다음 주기 재시도): %s", exc)
            await asyncio.sleep(min(cfg.catalog_sync_interval, 300))

    app.state.sync_task = asyncio.create_task(_sync_loop()) if harvest_on else None
    yield
    # 종료 — 진행 중인 sync 스케줄러 취소.
    task = getattr(app.state, "sync_task", None)
    if task is not None and not task.done():
        task.cancel()


app = FastAPI(
    title="AI 하네스 아키텍트 API",
    version="0.1.0",
    description="자연어 설명 → 하네스 구성요소 추천 → 검증 → harness.yaml 생성.",
    lifespan=lifespan,
)

# 레이트리밋(slowapi) — IP 기준. 계정 스팸·비용 유발 완화. 테스트에선 HARNESS_RATELIMIT=off 로 비활성.
limiter = Limiter(key_func=get_remote_address, enabled=os.environ.get("HARNESS_RATELIMIT", "on") != "off")
app.state.limiter = limiter
# slowapi 핸들러 시그니처(RateLimitExceeded)와 Starlette 기대(Exception)의 타입 불일치 — 런타임 정상.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# 관측성 — 구조적 로깅 + 요청 ID·메트릭 미들웨어(순수 ASGI, SSE 안전).
configure_logging()
app.add_middleware(ObservabilityMiddleware)

# CORS — 기본 거부(빈 allowlist). 웹은 리버스 프록시로 동일 오리진, 확장은 Node fetch(브라우저 CORS
# 무관)라 기본은 필요 없다. 크로스 오리진으로 API 를 직접 노출할 때만 HARNESS_CORS_ORIGINS(쉼표 구분).
_cors_origins = [o.strip() for o in os.environ.get("HARNESS_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],  # 페이지네이션 총계 헤더를 크로스오리진에서도 읽게
    )


def _registry(request: Request) -> InMemoryRegistry:
    return cast(InMemoryRegistry, request.app.state.registry)


def _recommender(request: Request) -> Recommender:
    # LiveRecommender.get() — 라이브 내용이 바뀌었으면 재인덱싱(동기 엔드포인트는 스레드풀 실행이라 안전).
    return cast(LiveRecommender, request.app.state.recommender).get()


def _curated_ids(request: Request) -> set[str]:
    """손큐레이션(로컬 시드) 컴포넌트 id 집합 = 최상위 신뢰. 외부 수확분은 여기 없다.

    FederatedRegistry 면 `.local`(오프라인 큐레이션분)만 본다. harvest off 면 registry 자체가 로컬.
    """
    reg = _registry(request)
    base = getattr(reg, "local", reg)
    return {c.id for c in base.all()}


# MCP 레지스트리에서 '공식'으로 볼 신뢰 네임스페이스(신원인증 + 유지보수 주체가 신뢰됨).
# 나머지 레지스트리 발행물은 신원은 인증됐어도 개별 검증은 안 된 community 로 둔다. 확장은 여기서.
_TRUSTED_NAMESPACES = frozenset(
    {"io.github.modelcontextprotocol", "io.modelcontextprotocol", "com.anthropic"}
)


def _origins_for(request: Request, ids: list[str]) -> dict[str, str]:
    store = getattr(request.app.state, "catalog_store", None)
    return store.origins_for(ids) if store is not None else {}


def _trust(component_id: str, curated: set[str], origins: dict[str, str]) -> str:
    """프로비넌스 신뢰 등급: curated | official | community.

    - curated: 손큐레이션 시드(직접 검토).
    - official: Anthropic 공식 마켓플레이스(origin=marketplace) 또는 신뢰 네임스페이스 레지스트리.
    - community: 그 외 외부 발행물 — 신원은 인증돼도 개별 안전성은 미검증.
    """
    if component_id in curated:
        return "curated"
    if origins.get(component_id) == "marketplace":
        return "official"  # anthropics/claude-plugins-official = 공식 큐레이션
    namespace = component_id.split("/", 1)[0] if "/" in component_id else ""
    if namespace in _TRUSTED_NAMESPACES:
        return "official"
    return "community"


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    """라이브니스 — 프로세스가 떠 있는지. 라이브 페치를 유발하지 않도록 로컬 카탈로그 크기만 본다."""
    reg = request.app.state.registry
    base = getattr(reg, "local", reg)  # FederatedRegistry 면 로컬만(네트워크 X)
    return {"status": "ok", "catalog_size": len(base.all())}


@app.get("/ready")
def ready(request: Request) -> Response:
    """레디니스 — 트래픽 받을 준비(DB 연결). 실패 시 503(로드밸런서가 제외)."""
    ok = db_ready(request.app.state.engine)
    return JSONResponse({"ready": ok}, status_code=200 if ok else 503)


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus 스크레이프 — 요청 수/지연."""
    return metrics_response()


@app.get("/catalog", response_model=list[CatalogItem])
def catalog(
    request: Request,
    response: Response,
    type: str | None = Query(default=None, description="skill|mcp|context|hook"),
    capability: str | None = Query(default=None, description="provides/capability_tags 로 필터"),
    q: str | None = Query(default=None, description="id·name·summary·태그 부분일치 검색"),
    limit: int | None = Query(default=None, ge=1, le=200, description="페이지 크기(미지정=전체)"),
    offset: int = Query(default=0, ge=0, description="페이지 시작 오프셋"),
    exclude_curated: bool = Query(default=False, description="손큐레이션 시드(curated) 제외 — 외부 수확분만"),
) -> list[CatalogItem]:
    """카탈로그 목록 — type·capability·q 로 필터/검색하고 limit·offset 으로 페이지네이션.

    총 개수(필터 적용 후)는 `X-Total-Count` 헤더로 준다(본문은 현재 페이지만). 카탈로그가
    수천 개로 커져도 서버에서 잘라 보내므로 페이로드·렌더가 가볍다. 필터·검색·정렬은 서버가 하므로
    검색이 현재 페이지가 아니라 전체에 걸린다. `exclude_curated` 는 우리 시드를 빼고 외부 소스만 본다.
    """
    curated = _curated_ids(request)
    comps = _registry(request).all()
    if exclude_curated:
        comps = [c for c in comps if c.id not in curated]
    if type:
        comps = [c for c in comps if c.type == type]
    if capability:
        comps = [c for c in comps if capability in c.provides or capability in c.capability_tags]
    if q:
        ql = q.lower()
        comps = [
            c
            for c in comps
            if ql in f"{c.id} {c.name} {c.summary} {' '.join(c.capability_tags)}".lower()
        ]
    total = len(comps)
    # 안정적 페이지 경계 — 타입·이름·id 순 정렬 후 슬라이스.
    comps.sort(key=lambda c: (c.type, c.name.lower(), c.id))
    page = comps[offset : offset + limit] if limit is not None else comps[offset:]
    origins = _origins_for(request, [c.id for c in page])
    response.headers["X-Total-Count"] = str(total)
    return [CatalogItem.from_component(c, trust=_trust(c.id, curated, origins)) for c in page]


@app.get("/catalog/{component_id:path}")
def catalog_detail(request: Request, component_id: str) -> dict[str, Any]:
    # `:path` 컨버터 — 연합 레지스트리 id 는 `io.github.owner/server` 처럼 슬래시를 포함한다.
    # 기본 `{id}`(단일 세그먼트)면 슬래시에서 라우트 매칭 실패 → 404 → 화면 크래시였다.
    c = _registry(request).get(component_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"컴포넌트 '{component_id}' 없음")
    data = c.model_dump()
    data["trust"] = _trust(component_id, _curated_ids(request), _origins_for(request, [component_id]))
    return data


# ─────────────── 멀티테넌시: 인증(Bearer) + 팀(자가서브) + 스코프 격리 저장소 ───────────────
# (resolve/generate 가 optional_user·_scoped_registry 를 기본인자로 참조하므로 그 앞에 정의한다)


def _store(request: Request) -> HarnessStore:
    return cast(HarnessStore, request.app.state.store)


def _broadcaster(request: Request) -> SSEBroadcaster:
    return cast(SSEBroadcaster, request.app.state.broadcaster)


def _accounts(request: Request) -> AccountStore:
    return cast(AccountStore, request.app.state.accounts)


def _gap_demand(request: Request) -> GapDemand:
    return cast(GapDemand, request.app.state.gap_demand)


def _record_gaps(request: Request, gaps: list[Any], source: str) -> None:
    """gap 수요를 provenance(카탈로그 상태·caps 소스)와 함께 기록. 비차단(내부에서 예외 삼킴)."""
    cs = cast(CatalogStore, request.app.state.catalog_store)
    try:
        rev, cand = cs.revision(), cs.count()
    except Exception:  # noqa: BLE001 — provenance 수집 실패해도 기록은 진행
        rev, cand = "", 0
    _gap_demand(request).record(
        gaps,
        source=source,
        catalog_revision=rev,
        candidate_count=cand,
        caps_source="heuristic",  # TASK 3 에서 zeroshot 로 승격 시 이 값이 바뀐다(hot-gap 게이팅 해제 트리거)
        vocab_version=VOCAB_VERSION,
    )


def _component_store(request: Request) -> ComponentStore:
    return cast(ComponentStore, request.app.state.component_store)


def _conversation_store(request: Request) -> ConversationStore:
    return cast(ConversationStore, request.app.state.conversation_store)


def _app_settings(request: Request) -> AppSettingsStore:
    return cast(AppSettingsStore, request.app.state.app_settings)


def _llm_complete(request: Request) -> Any:
    """LLM 호출 함수 (system,user,max_tokens)->JSON. 앱 등록 키 없으면 None(호출부가 차단).

    앱(인스턴스) 레벨 LLM 키만 사용한다 — 서버 env 폴백 없음. 전역 os.environ 은 건드리지 않는다.
    """
    res = _app_settings(request).resolve()
    key = res["llm_key"]
    if not key:
        return None
    provider = res["provider"] or "anthropic"
    model = DEFAULT_MODEL.get(provider, "")

    def _complete(system: str, user_msg: str, max_tokens: int) -> Any:
        return _provider_complete_json(provider, model, key, system, user_msg, max_tokens=max_tokens)

    return _complete


def _bearer(authorization: str | None, token: str | None) -> str:
    """Authorization: Bearer <t> 또는 ?token=<t> 에서 원문 토큰을 뽑는다(SSE 는 헤더 불가라 쿼리 허용)."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (token or "").strip()


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    """Bearer 토큰(세션 또는 PAT)으로 사용자 신원 확인. SSE(EventSource)는 ?token= 도 허용."""
    user = _accounts(request).user_by_token(_bearer(authorization, token))
    if user is None:
        raise HTTPException(status_code=401, detail="인증 필요 — 로그인하세요")
    return user


async def optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any] | None:
    """토큰 있으면 사용자, 없거나 무효면 None(401 안 냄). resolve/generate 를 미로그인에서도 열어두되
    로그인 시 그 유저의 ready 컴포넌트를 스코프-편입하기 위한 것."""
    return _accounts(request).user_by_token(_bearer(authorization, token))


def _scoped_registry(request: Request, user: dict[str, Any] | None) -> Any:
    """요청-스코프 레지스트리 — 전역 카탈로그 + (로그인 시) 그 유저의 가시 ready 컴포넌트.

    전역 app.state.registry 는 유저 무관이라 유저 컴포넌트를 절대 안 넣는다(전원 누출). 대신 요청마다
    그 유저 것만 담은 UserComponentSource 를 FederatedRegistry 로 감싸 resolve/generate 에 넘긴다.
    """
    base = _registry(request)
    if user is None:
        return base
    scopes = _accounts(request).visible_scope_keys(user["id"])
    return FederatedRegistry(base, [UserComponentSource(_component_store(request), scopes)])


@app.post("/recommend")
@limiter.limit("60/minute")
def recommend(request: Request, body: RecommendRequest) -> dict[str, Any]:
    result = _recommender(request).recommend(body.description, top_k=body.top_k)
    _record_gaps(request, result.gaps, "recommend")  # gap 수요 집계(provenance 포함)
    data = result.model_dump()
    # 추천 카드에도 프로비넌스 표시. (추천기 모델은 안 건드리고 API 에서 주입.)
    recs = data.get("recommendations", [])
    curated = _curated_ids(request)
    origins = _origins_for(request, [r.get("id", "") for r in recs])
    for rec in recs:
        rec["trust"] = _trust(rec.get("id", ""), curated, origins)
    return data


@app.get("/gaps/top")
def gaps_top(request: Request, n: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
    """자주 요청되나 카탈로그에 없는 능력 top-N(런타임 수요). 저작 제안·시딩 우선순위의 라이브 신호."""
    return {"gaps": _gap_demand(request).top(n)}


@app.post("/resolve", response_model=ResolveResult)
def resolve_endpoint(
    request: Request, body: ResolveRequest, user: dict[str, Any] | None = Depends(optional_user)
) -> ResolveResult:
    config = body.to_config()
    return resolve(config, _scoped_registry(request, user))


@app.post("/generate", response_model=GenerateResponse)
def generate(
    request: Request, body: ResolveRequest, user: dict[str, Any] | None = Depends(optional_user)
) -> GenerateResponse:
    config = body.to_config()
    result = resolve(config, _scoped_registry(request, user))
    return GenerateResponse(
        yaml=to_harness_yaml(config),
        ok=result.ok,
        gaps=len(result.diagnostics.gaps),
        warnings=len(result.diagnostics.warnings),
        errors=len(result.diagnostics.errors),
    )


@app.post("/run")
@limiter.limit("30/minute")
def run_endpoint(
    request: Request, body: RunRequest, user: dict[str, Any] | None = Depends(optional_user)
) -> dict[str, Any]:
    """resolve → build_request → (키 있으면) Anthropic 전송, 없으면 dry_run. 런타임 관통."""
    config = body.to_config()
    result = resolve(config, _scoped_registry(request, user))
    if not result.ok or result.resolved is None:
        return {"ok": False, "diagnostics": result.diagnostics.model_dump(), "built": None, "run": None}
    built = build_request(result.resolved, body.message)
    run = AnthropicRunner().run(built)
    return {
        "ok": True,
        "built": {
            "model": built.model,
            "system_chars": len(built.system),
            # API 로 전송되는 MCP 서버(원격 URL 만). stdio 서버는 eject 몫이라 여기 안 실린다.
            "mcp_servers": [m["name"] for m in built.mcp_servers],
            "hook_plan": built.hook_plan,
            "permissions": built.permissions,
        },
        "run": run.model_dump(),
    }


@app.get("/eject/targets")
def eject_targets() -> list[str]:
    """지원하는 eject 타깃 목록(프론트 타깃 셀렉터용)."""
    return available_targets()


@app.post("/eject")
def eject_endpoint(
    request: Request,
    body: ResolveRequest,
    target: str = Query("claude-code"),
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    """resolve → emit(target). ResolvedHarness IR 을 런타임 네이티브 파일 트리로 컴파일 (Phase 5)."""
    if target not in available_targets():
        raise HTTPException(status_code=400, detail=f"지원하지 않는 타깃: {target} (가능: {available_targets()})")
    result = resolve(body.to_config(), _scoped_registry(request, user))
    if not result.ok or result.resolved is None:
        return {"ok": False, "target": target, "diagnostics": result.diagnostics.model_dump(), "files": None}
    return {"ok": True, "target": target, "files": emit(result.resolved, target)}


# ─────────────── OAuth 로그인 (사람=이메일 신원) ───────────────
# 사람은 OAuth 로 로그인해 웹 세션 토큰을 받고, 기계(VSCode)는 설정에서 PAT 를 발급받아 붙인다.
# 공급자 앱 자격증명은 배포 env 로만 주입한다.

_GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
_GITHUB_USER = "https://api.github.com/user"
_GITHUB_EMAILS = "https://api.github.com/user/emails"
_SESSION_TTL_DAYS = 30


def _dev_auth() -> bool:
    return os.environ.get("HARNESS_DEV_AUTH", "") == "on"


def _github_client() -> tuple[str, str]:
    return os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""), os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")


def _redirect_base() -> str:
    # GitHub 앱에 등록하는 콜백의 베이스. 개발은 웹 오리진(:5173)의 /api 프록시를 거쳐 백엔드로.
    return os.environ.get("OAUTH_REDIRECT_BASE", "http://localhost:5173/api").rstrip("/")


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:5173").rstrip("/")


@app.get("/auth/config")
def auth_config() -> dict[str, Any]:
    """로그인 화면이 어떤 방법을 띄울지 — 구성된 OAuth 공급자 + 개발 로그인 가용 여부."""
    providers = ["github"] if _github_client()[0] else []
    return {"providers": providers, "dev_auth": _dev_auth()}


@app.get("/auth/oauth/{provider}/start")
def oauth_start(request: Request, provider: str) -> Response:
    """공급자 인증 페이지로 리다이렉트(state 로 CSRF 방지)."""
    if provider != "github":
        raise HTTPException(status_code=404, detail=f"지원하지 않는 공급자: {provider}")
    client_id, _ = _github_client()
    if not client_id:
        raise HTTPException(status_code=400, detail="GitHub OAuth 미구성 — GITHUB_OAUTH_CLIENT_ID 필요")
    state = secrets.token_urlsafe(24)
    request.app.state.oauth_states[state] = time.time()
    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": f"{_redirect_base()}/auth/oauth/github/callback",
            "scope": "read:user user:email",
            "state": state,
            "allow_signup": "true",
        }
    )
    return RedirectResponse(f"{_GITHUB_AUTHORIZE}?{params}")


def _pop_state(request: Request, state: str) -> bool:
    states: dict[str, float] = request.app.state.oauth_states
    ts = states.pop(state, None)
    # 만료(10분) 청소 + 유효성
    for k, v in list(states.items()):
        if time.time() - v > 600:
            states.pop(k, None)
    return ts is not None and time.time() - ts <= 600


@app.get("/auth/oauth/{provider}/callback")
def oauth_callback(
    request: Request, provider: str, code: str = Query(...), state: str = Query(...)
) -> Response:
    """공급자 콜백 — code 교환 → 프로필 조회 → 유저 upsert → 세션 발급 → 웹으로 리다이렉트."""
    if provider != "github" or not _pop_state(request, state):
        return RedirectResponse(f"{_web_base()}/?auth_error=invalid_state")
    client_id, client_secret = _github_client()
    try:
        with httpx.Client(timeout=10.0) as c:
            tok = c.post(
                _GITHUB_TOKEN,
                headers={"Accept": "application/json"},
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": f"{_redirect_base()}/auth/oauth/github/callback",
                },
            ).json()
            access = tok.get("access_token")
            if not access:
                return RedirectResponse(f"{_web_base()}/?auth_error=token_exchange")
            gh_headers = {"Authorization": f"token {access}", "Accept": "application/vnd.github+json"}
            gh = c.get(_GITHUB_USER, headers=gh_headers).json()
            email = gh.get("email")
            if not email:  # 공개 이메일이 없으면 primary·verified 이메일을 별도 조회
                emails = c.get(_GITHUB_EMAILS, headers=gh_headers).json()
                email = next(
                    (e["email"] for e in emails if e.get("primary") and e.get("verified")),
                    next((e["email"] for e in emails if e.get("verified")), None),
                )
            if not email:
                return RedirectResponse(f"{_web_base()}/?auth_error=no_email")
    except httpx.HTTPError:
        return RedirectResponse(f"{_web_base()}/?auth_error=provider_unreachable")

    user = _accounts(request).upsert_oauth_user(
        "github", str(gh.get("id")), email, gh.get("name") or gh.get("login") or "", gh.get("avatar_url") or ""
    )
    session = _accounts(request).create_token(user["id"], "session", name="web", ttl_days=_SESSION_TTL_DAYS)
    return RedirectResponse(f"{_web_base()}/?session={session['token']}")


@app.post("/auth/dev-login")
def dev_login(request: Request, body: DevLoginBody) -> dict[str, Any]:
    """개발 전용 로그인(HARNESS_DEV_AUTH=on) — 실제 OAuth 앱 없이 이메일로 세션 발급."""
    if not _dev_auth():
        raise HTTPException(status_code=404, detail="dev-login 비활성 (HARNESS_DEV_AUTH=on 필요)")
    email = body.email.strip().lower()
    user = _accounts(request).upsert_oauth_user("dev", email, email, email.split("@")[0], "")
    session = _accounts(request).create_token(user["id"], "session", name="dev", ttl_days=_SESSION_TTL_DAYS)
    return {"token": session["token"], "user": user}


@app.post("/auth/logout")
def logout(
    request: Request,
    authorization: str | None = Header(default=None),
    _user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    """현재 세션 토큰만 폐기(PAT·다른 기기 세션은 유지)."""
    return {"ok": _accounts(request).revoke_by_token(_bearer(authorization, None))}


# ── PAT(개인 액세스 토큰) — VSCode·기계 연결용, 설정 화면에서 관리 ──


@app.get("/auth/tokens")
def list_tokens(request: Request, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return _accounts(request).list_tokens(user["id"], kind="pat")


@app.post("/auth/tokens")
def create_pat(
    request: Request, body: TokenCreateBody, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    """PAT 발급 — 원문은 이 응답에서만 노출. 이후 목록엔 이름·발급일만 보인다."""
    name = body.name.strip() or "VSCode"
    return _accounts(request).create_token(user["id"], "pat", name=name)


@app.delete("/auth/tokens/{tid}")
def revoke_pat(
    request: Request, tid: str, user: dict[str, Any] = Depends(current_user)
) -> dict[str, bool]:
    if not _accounts(request).revoke_token(user["id"], tid):
        raise HTTPException(status_code=404, detail="토큰 없음")
    return {"ok": True}


def _resolve_scope(request: Request, user: dict[str, Any], scope: str, write: bool = False) -> str:
    """쿼리 scope('personal'|'team:<tid>')를 스코프 키로. 팀은 멤버십·역할을 검사.

    write=True(저장·삭제)면 owner/editor 만 허용(viewer 는 읽기 전용). 격리는 항상.
    """
    if scope in ("", "personal"):
        return f"personal:{user['id']}"
    if scope.startswith("team:"):
        tid = scope[len("team:") :]
        role = _accounts(request).member_role(tid, user["id"])
        if role is None:
            raise HTTPException(status_code=403, detail="이 팀의 멤버가 아닙니다")
        if write and role not in ("owner", "editor"):
            raise HTTPException(status_code=403, detail="뷰어는 쓰기 권한이 없습니다(읽기 전용)")
        return f"team:{tid}"
    raise HTTPException(status_code=400, detail=f"잘못된 scope: {scope} (personal|team:<id>)")


# ── 팀 ──


@app.get("/me")
def whoami(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {**user, "teams": _accounts(request).teams_of(user["id"])}


@app.post("/teams")
def create_team(
    request: Request, body: TeamCreateBody, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    return _accounts(request).create_team(body.name, user["id"])


@app.get("/teams")
def list_teams(request: Request, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return _accounts(request).teams_of(user["id"])


@app.post("/teams/{tid}/members")
def add_team_member(
    request: Request, tid: str, body: MemberBody, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    try:
        return _accounts(request).add_member(tid, user["id"], body.email, body.role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── 스코프 격리 하네스 저장소 (웹 ↔ VSCode 확장 양방향 동기화) ──


@app.get("/harnesses")
def list_harnesses(
    request: Request,
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    """내 가시 스코프(personal + 내 팀들)의 하네스 요약 목록(최신순). limit/offset 으로 페이지네이션."""
    scopes = sorted(_accounts(request).visible_scope_keys(user["id"]))
    return _store(request).list_scopes(scopes, limit=limit, offset=offset)


# ⚠ 라우트 순서: 고정 경로(/harnesses/events)를 {hid} 보다 먼저 선언해야 매칭이 가로채이지 않는다.
@app.get("/harnesses/events")
async def harness_events(
    request: Request, user: dict[str, Any] = Depends(current_user)
) -> EventSourceResponse:
    """SSE — 내 가시 스코프의 변경만 실시간 푸시. 연결 시 현재 목록을 ready 로 먼저 보낸다."""
    scopes = _accounts(request).visible_scope_keys(user["id"])
    return EventSourceResponse(event_stream(_store(request), _broadcaster(request), scopes))


@app.get("/harnesses/{hid}/versions")
def harness_versions(
    request: Request,
    hid: str,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    """현재 + 이전 버전들(최신순). 웹이 버전 간 diff 를 그린다."""
    sk = _resolve_scope(request, user, scope)
    v = _store(request).versions(sk, hid)
    if v is None:
        raise HTTPException(status_code=404, detail=f"하네스 '{hid}' 없음(scope={scope})")
    return v


@app.get("/harnesses/{hid}")
def get_harness(
    request: Request,
    hid: str,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    sk = _resolve_scope(request, user, scope)
    doc = _store(request).get(sk, hid)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"하네스 '{hid}' 없음(scope={scope})")
    return doc


@app.put("/harnesses/{hid}")
async def put_harness(
    request: Request,
    hid: str,
    body: HarnessSaveBody,
    scope: str = Query("personal"),
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """하네스 저장(upsert). 스코프 안에 저장하고 SSE 푸시. If-Match(버전)를 주면 낙관적 잠금 → 409."""
    sk = _resolve_scope(request, user, scope, write=True)
    store = _store(request)
    expected = int(if_match) if if_match and if_match.isdigit() else None
    try:
        doc = store.put(sk, hid, user["id"], body.name, body.description, body.yaml, expected_version=expected)
    except VersionConflict as exc:
        raise HTTPException(
            status_code=409, detail=f"버전 충돌 — 현재 v{exc.current}. 최신을 다시 불러온 뒤 저장하세요."
        ) from exc
    await _broadcaster(request).publish(
        {"type": "upsert", "id": doc["id"], "scope": sk, "harness": store.summary(doc)}
    )
    return doc


@app.delete("/harnesses/{hid}")
async def delete_harness(
    request: Request,
    hid: str,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    sk = _resolve_scope(request, user, scope, write=True)
    if not _store(request).delete(sk, hid):
        raise HTTPException(status_code=404, detail=f"하네스 '{hid}' 없음(scope={scope})")
    await _broadcaster(request).publish({"type": "delete", "id": safe_id(hid), "scope": sk})
    return {"ok": True, "id": safe_id(hid), "scope": sk}


# 저장된 하네스(에이전트)를 검증·내보내기 — 스튜디오가 조립한 에이전트를 하네스 화면에서 점검·eject.
# (구 '생성' 위저드 C·D 를 산출물 위로 이동: 대화가 빌드, 하네스 상세가 검증·export.)
@app.post("/harnesses/{hid}/validate", response_model=ResolveResult)
def validate_harness(
    request: Request, hid: str, scope: str = Query("personal"), user: dict[str, Any] = Depends(current_user)
) -> ResolveResult:
    """저장된 harness.yaml 을 역파싱해 resolve — gap/충돌/인증 진단."""
    sk = _resolve_scope(request, user, scope)
    doc = _store(request).get(sk, hid)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"하네스 '{hid}' 없음(scope={scope})")
    try:
        config = parse_harness_yaml(doc["yaml"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"harness.yaml 파싱 실패: {exc}") from exc
    return resolve(config, _scoped_registry(request, user))


@app.post("/harnesses/{hid}/eject")
def eject_harness(
    request: Request,
    hid: str,
    scope: str = Query("personal"),
    target: str = Query("claude-code"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """저장된 하네스를 런타임 네이티브 파일 트리로 eject(claude-code 등)."""
    if target not in available_targets():
        raise HTTPException(status_code=400, detail=f"지원하지 않는 타깃: {target} (가능: {available_targets()})")
    sk = _resolve_scope(request, user, scope)
    doc = _store(request).get(sk, hid)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"하네스 '{hid}' 없음(scope={scope})")
    try:
        config = parse_harness_yaml(doc["yaml"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"harness.yaml 파싱 실패: {exc}") from exc
    result = resolve(config, _scoped_registry(request, user))
    if not result.ok or result.resolved is None:
        return {"ok": False, "target": target, "diagnostics": result.diagnostics.model_dump(), "files": None}
    return {"ok": True, "target": target, "files": emit(result.resolved, target)}


# ── 유저 저작 컴포넌트 (스튜디오: 채팅 생성 → 검증 → 테스트 → 내 구성요소) ──


def _component_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """저장 doc 의 data(JSON 문자열)를 파싱해 `component` 로 노출(프런트 편의)."""
    out = {k: v for k, v in doc.items() if k not in ("data",)}
    try:
        out["component"] = json.loads(doc["data"]) if doc.get("data") else None
    except (json.JSONDecodeError, TypeError):
        out["component"] = None
    return out


@app.post("/components/author")
@limiter.limit("30/minute")
def component_author(
    request: Request, body: ComponentAuthorBody, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    """자연어 → context 컴포넌트 초안(아직 미저장). prior_id 주면 가시 스코프의 이전본을 리파인."""
    store = _component_store(request)
    prior: Component | None = None
    if body.prior_id:
        for sk in _accounts(request).visible_scope_keys(user["id"]):
            d = store.get(sk, body.prior_id)
            if d:
                try:
                    prior = Component.model_validate_json(d["data"])
                except Exception:  # noqa: BLE001
                    prior = None
                break
    complete = _llm_complete(request)
    if complete is None:
        raise HTTPException(status_code=400, detail="LLM 키가 없습니다 — 설정에서 LLM 키를 등록하세요")
    comp = author_component(body.prompt, body.type, prior, complete=complete)
    return {"component": comp.model_dump()}


@app.get("/components")
def list_components(
    request: Request,
    status: str | None = Query(default=None, description="draft|valid|ready 필터"),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    """내 가시 스코프(personal + 팀)의 유저 컴포넌트 요약 목록(최신순)."""
    scopes = sorted(_accounts(request).visible_scope_keys(user["id"]))
    return _component_store(request).list_scopes(scopes, status=status, limit=limit, offset=offset)


# ⚠ 라우트 순서: 고정 경로(/components/events)를 {cid} 보다 먼저 선언(매칭 가로채임 방지).
@app.get("/components/events")
async def component_events(
    request: Request, user: dict[str, Any] = Depends(current_user)
) -> EventSourceResponse:
    """SSE — 내 가시 스코프의 컴포넌트 변경만 실시간 푸시(하네스와 브로드캐스터 공유, kind 로 구분)."""
    scopes = _accounts(request).visible_scope_keys(user["id"])
    return EventSourceResponse(component_event_stream(_component_store(request), _broadcaster(request), scopes))


@app.get("/components/ready")
def list_ready_components(
    request: Request, user: dict[str, Any] = Depends(current_user)
) -> list[dict[str, Any]]:
    """위저드(화면 B) 선택용 — 내 가시 스코프의 ready 컴포넌트를 추천 카드 형태로. ref 는 id@semver."""
    scopes = _accounts(request).visible_scope_keys(user["id"])
    comps = _component_store(request).ready_components(sorted(scopes))
    return [
        {
            "id": c.id, "type": c.type, "name": c.name, "version": c.version,
            "summary": c.summary, "reason": "내가 만든 구성요소(검증·테스트 완료)",
            "provides": c.provides, "requires": c.requires, "matched_capabilities": c.provides,
            "context_tokens": c.cost.context_tokens, "added_tools": c.cost.added_tools,
            "exclusive_group": c.constraints.exclusive_group, "conflicts_with": c.conflicts_with,
            "auth_required": bool(c.auth and c.auth.required), "score": 0.0, "trust": "user",
        }
        for c in comps
    ]


@app.get("/components/{cid}")
def get_component(
    request: Request,
    cid: str,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    sk = _resolve_scope(request, user, scope)
    doc = _component_store(request).get(sk, cid)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"컴포넌트 '{cid}' 없음(scope={scope})")
    return _component_doc(doc)


@app.put("/components/{cid}")
async def put_component(
    request: Request,
    cid: str,
    body: ComponentSaveBody,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """저장(upsert) — data(Component dict) 검증 후 status 갱신(valid/draft). 편집은 테스트를 무효화한다."""
    sk = _resolve_scope(request, user, scope, write=True)
    try:
        comp = Component.model_validate(body.data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"컴포넌트 형식 오류: {exc}") from exc
    val = validate_component(comp)
    status = "valid" if val["ok"] else "draft"
    store = _component_store(request)
    doc = store.put(
        sk, cid, user["id"], body.name or comp.name, body.description or comp.summary,
        comp.model_dump_json(), type_=comp.type, status=status,
    )
    await _broadcaster(request).publish(
        {"type": "upsert", "kind": "component", "id": doc["id"], "scope": sk, "component": store.summary(doc)}
    )
    return {**_component_doc(doc), "validation": val}


@app.post("/components/{cid}/test")
async def test_component_endpoint(
    request: Request,
    cid: str,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """LLM 심사(적합성 + 인젝션/안전). 통과 시 status=ready(위저드 사용 가능). draft 는 검증 먼저."""
    sk = _resolve_scope(request, user, scope, write=True)
    store = _component_store(request)
    doc = store.get(sk, cid)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"컴포넌트 '{cid}' 없음(scope={scope})")
    if doc["status"] == "draft":
        raise HTTPException(status_code=400, detail="검증(valid)을 먼저 통과해야 테스트할 수 있습니다")
    complete = _llm_complete(request)
    if complete is None:
        raise HTTPException(status_code=400, detail="LLM 키가 없습니다 — 설정에서 LLM 키를 등록하세요")
    comp = Component.model_validate_json(doc["data"])
    result = test_component(comp, complete=complete)
    new_status = doc["status"]
    if result.get("pass"):
        updated = store.set_status(sk, cid, "ready")
        new_status = updated["status"] if updated else "ready"
        await _broadcaster(request).publish(
            {
                "type": "upsert",
                "kind": "component",
                "id": doc["id"],
                "scope": sk,
                "component": store.summary(updated or doc),
            }
        )
    return {"result": result, "status": new_status}


@app.post("/components/{cid}/promote")
async def promote_component_endpoint(
    request: Request,
    cid: str,
    scope: str = Query("personal"),
    allow_unsandboxed: bool = Query(False),  # sandbox=none 훅 추가 심사(거버넌스 게이트)
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """저작 컴포넌트를 공유 카탈로그로 승격(Phase 14 피드백 루프). 게이트: ready + validate 통과.

    승격되면 origin='promoted' 로 모든 유저 검색에 등장(gap 을 남의 것까지 닫음). 신뢰등급은 community.
    """
    sk = _resolve_scope(request, user, scope, write=True)
    catalog_store = getattr(request.app.state, "catalog_store", None)
    if catalog_store is None:
        raise HTTPException(status_code=503, detail="카탈로그 스토어가 없습니다(harvest off).")
    result = promote_component(
        _component_store(request), catalog_store, sk, cid, allow_unsandboxed=allow_unsandboxed
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail="; ".join(result["errors"]))
    return result


@app.delete("/components/{cid}")
async def delete_component(
    request: Request,
    cid: str,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    sk = _resolve_scope(request, user, scope, write=True)
    if not _component_store(request).delete(sk, cid):
        raise HTTPException(status_code=404, detail=f"컴포넌트 '{cid}' 없음(scope={scope})")
    await _broadcaster(request).publish({"type": "delete", "kind": "component", "id": safe_id(cid), "scope": sk})
    return {"ok": True, "id": safe_id(cid), "scope": sk}


# ── 스튜디오: 대화형 카탈로그 스튜디오 (채팅 → 자동분류 → 추천/저작 → 저장/테스트) ──
# 대화가 1급 객체다. 매 턴 LLM 이 도구(get_catalog_item·search_catalog·draft_component)를 자율 호출하며
# 자연스럽게 답하되 항상 '카탈로그 구성요소 생성'으로 수렴한다. 응답은 SSE 로 스트리밍('진짜 챗봇').


def _sse(event: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)}


async def _abridge(sync_iter: Any) -> AsyncIterator[dict[str, Any]]:
    """블로킹 LLM 호출을 포함한 동기 제너레이터를 스레드로 브리지해 async 로 흘린다(루프 블로킹 방지)."""
    sentinel = object()

    def _next() -> Any:
        try:
            return next(sync_iter)
        except StopIteration:
            return sentinel

    while True:
        item = await asyncio.to_thread(_next)
        if item is sentinel:
            break
        yield cast("dict[str, Any]", item)


@app.post("/studio/conversations")
async def create_conversation(
    request: Request, scope: str = Query("personal"), user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    """새 대화 스레드 생성(빈 제목 — 첫 턴에서 자동 명명)."""
    sk = _resolve_scope(request, user, scope, write=True)
    doc = _conversation_store(request).create(sk, user["id"])
    await _broadcaster(request).publish(
        {"type": "upsert", "kind": "conversation", "id": doc["id"], "scope": sk, "conversation": doc}
    )
    return doc


@app.get("/studio/conversations")
def list_conversations(
    request: Request,
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    """내 가시 스코프의 대화 목록(최신순) — 사이드바용."""
    scopes = sorted(_accounts(request).visible_scope_keys(user["id"]))
    return _conversation_store(request).list_scopes(scopes, limit=limit, offset=offset)


# ⚠ 라우트 순서: 고정 경로(/studio/conversations/events)를 {cid} 보다 먼저 선언.
@app.get("/studio/conversations/events")
async def conversation_events(
    request: Request, user: dict[str, Any] = Depends(current_user)
) -> EventSourceResponse:
    """SSE — 내 가시 스코프의 대화 목록 변경 실시간 푸시(브로드캐스터 공유, kind=conversation)."""
    scopes = _accounts(request).visible_scope_keys(user["id"])
    return EventSourceResponse(
        conversation_event_stream(_conversation_store(request), _broadcaster(request), scopes)
    )


@app.get("/studio/conversations/{cid}")
def get_conversation(
    request: Request, cid: str, scope: str = Query("personal"), user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    sk = _resolve_scope(request, user, scope)
    doc = _conversation_store(request).get(sk, cid)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"대화 '{cid}' 없음(scope={scope})")
    return doc


@app.delete("/studio/conversations/{cid}")
async def delete_conversation(
    request: Request, cid: str, scope: str = Query("personal"), user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    sk = _resolve_scope(request, user, scope, write=True)
    if not _conversation_store(request).delete(sk, cid):
        raise HTTPException(status_code=404, detail=f"대화 '{cid}' 없음(scope={scope})")
    await _broadcaster(request).publish({"type": "delete", "kind": "conversation", "id": cid, "scope": sk})
    return {"ok": True, "id": cid, "scope": sk}


@app.post("/studio/conversations/{cid}/chat")
@limiter.limit("30/minute")
async def studio_chat(
    request: Request,
    cid: str,
    body: StudioChatBody,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> EventSourceResponse:
    """대화 한 턴 — tool-use 에이전트가 도구를 자율 호출하며 답하고 결과를 SSE 로 스트리밍한다.

    이벤트: status(도구 실행 알림) · recommendations(검색 결과) · draft(초안) · title(자동제목) ·
    token(응답 청크) · done · error. 사용자·어시스턴트 메시지와 초안은 서버에 영속한다.
    """
    sk = _resolve_scope(request, user, scope, write=True)
    store = _conversation_store(request)
    full = store.get(sk, cid)
    if full is None:
        raise HTTPException(status_code=404, detail=f"대화 '{cid}' 없음(scope={scope})")

    res = _app_settings(request).resolve()
    key = res["llm_key"]
    if not key:
        raise HTTPException(status_code=400, detail="LLM 키가 없습니다 — 설정에서 LLM 키를 등록하세요")
    provider = res["provider"] or "anthropic"
    model = DEFAULT_MODEL.get(provider, "")

    def _complete(system: str, user_msg: str, max_tokens: int) -> Any:
        return _provider_complete_json(provider, model, key, system, user_msg, max_tokens=max_tokens)

    history = [{"role": m["role"], "content": m["content"]} for m in full["messages"]]
    has_title = bool(full.get("title"))
    dset = full.get("draft_set") or {"components": [], "harness": None}
    current_components: list[Component] = []
    for cd in dset.get("components") or []:
        try:
            current_components.append(Component.model_validate(cd))
        except Exception:  # noqa: BLE001 — 손상 초안은 건너뜀
            continue
    current_harness = dset.get("harness")
    start_version = full.get("version")
    # 스코프 인지(Phase 14 피드백 루프) — 유저 저작(ready) 컴포넌트를 검색·재사용에 편입한다.
    # 추천기: 전역 결과 + 유저 컴포넌트 병합(ScopedRecommender). 레지스트리: get_catalog_item 이 유저 것도 찾게.
    _user_scopes = _accounts(request).visible_scope_keys(user["id"])
    _user_comps = _component_store(request).ready_components(list(_user_scopes))
    recommender = ScopedRecommender(_recommender(request), _user_comps)
    registry = _scoped_registry(request, user)
    broadcaster = _broadcaster(request)
    gap_demand = _gap_demand(request)
    hot_capabilities = gap_demand.hot_capabilities()  # 자주 요청되는 공백 → 저작 우선 제안 근거
    user_msg = body.message
    forced_type = body.forced_type if body.forced_type in COMPONENT_TYPES else None

    # 사용자 메시지 먼저 영속(응답 스트림과 무관하게 남는다).
    store.add_message(sk, cid, "user", user_msg)

    async def gen() -> AsyncIterator[dict[str, Any]]:
        try:
            recommendations: list[dict[str, Any]] | None = None
            rec_gaps: list[dict[str, Any]] | None = None
            cur_components: list[dict[str, Any]] = [c.model_dump() for c in current_components]
            cur_harness: dict[str, Any] | None = current_harness
            new_version: int | None = start_version
            parts: list[str] = []
            agent = _run_agent(
                history, user_msg, current_components, current_harness, provider=provider, model=model,
                api_key=key, complete=_complete, recommender=recommender, registry=registry,
                forced_type=forced_type, search_key=res.get("search_key", ""),
                hot_capabilities=hot_capabilities,
            )
            async for ev in _abridge(agent):
                kind = ev.get("type")
                if kind == "status":
                    yield _sse("status", {"label": ev["label"]})
                elif kind == "side":
                    se = ev["event"]
                    st = se.get("type")
                    if st == "recommendations":
                        recommendations = se["items"] or None
                        rec_gaps = se.get("gaps") or None
                        _record_gaps(request, se.get("gaps") or [], "studio")  # 스튜디오 검색 gap 수요 집계
                        yield _sse(
                            "recommendations",
                            {"items": se["items"], "gaps": se.get("gaps", []), "reused": se.get("reused", False)},
                        )
                    elif st == "drafts":
                        cur_components = se["components"]
                        new_version = store.save_set(sk, cid, cur_components, cur_harness)
                        yield _sse("drafts", {"components": cur_components, "version": new_version})
                    elif st == "harness":
                        cur_harness = se["harness"]
                        new_version = store.save_set(sk, cid, cur_components, cur_harness)
                        yield _sse("harness", {"harness": cur_harness, "version": new_version})
                elif kind == "token":
                    parts.append(ev["text"])
                    yield _sse("token", {"text": ev["text"]})

            prose = "".join(parts).strip() or "무엇을 만들어 드릴까요? 예: '슬랙에 PR 알림 보내는 훅'."
            if not has_title:
                title = await asyncio.to_thread(_suggest_title, _complete, user_msg, prose)
                if title:
                    store.set_title(sk, cid, title)
                    yield _sse("title", {"title": title})

            meta = {
                "components": [{"type": c.get("type"), "name": c.get("name")} for c in cur_components] or None,
                "harness": (cur_harness.get("name") if cur_harness else None),
                "recommendations": recommendations,
                "gaps": rec_gaps,
                "version": new_version,
            }
            amsg = store.add_message(sk, cid, "assistant", prose, meta)
            header = store.header(sk, cid)
            if header is not None:
                await broadcaster.publish({
                    "type": "upsert", "kind": "conversation", "id": cid,
                    "scope": sk, "conversation": store.summary(header),
                })
            yield _sse("done", {
                "message_id": amsg["id"], "version": new_version,
                "title": (header or {}).get("title"),
            })
        except Exception as exc:  # noqa: BLE001 — 스트림 안에서 오류를 이벤트로 전달(연결은 정상 종료)
            log.exception("스튜디오 대화 턴 실패")
            yield _sse("error", {"detail": f"{type(exc).__name__}: {exc}"})

    return EventSourceResponse(gen())


@app.post("/studio/conversations/{cid}/commit")
async def studio_commit(
    request: Request,
    cid: str,
    body: StudioCommitBody,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """대화의 초안 세트를 통째로 저장 — 구성요소들은 카탈로그(user_components)에, 조립된 하네스는 하네스 저장소에."""
    sk = _resolve_scope(request, user, scope, write=True)
    cstore = _conversation_store(request)
    conv = cstore.get(sk, cid)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"대화 '{cid}' 없음(scope={scope})")
    dset = conv.get("draft_set") or {}
    comp_dicts = dset.get("components") or []
    if not comp_dicts:
        raise HTTPException(status_code=400, detail="저장할 구성요소가 없습니다 — 먼저 만들어 주세요")

    store = _component_store(request)
    saved: list[dict[str, Any]] = []
    for cd in comp_dicts:
        try:
            comp = Component.model_validate(cd)
        except Exception:  # noqa: BLE001 — 손상 초안은 건너뜀
            continue
        val = validate_component(comp)
        status = "valid" if val["ok"] else "draft"
        doc = store.put(
            sk, comp.id, user["id"], comp.name, comp.summary,
            comp.model_dump_json(), type_=comp.type, status=status,
        )
        saved.append({"id": comp.id, "type": comp.type, "name": comp.name, "status": status, "validation": val})
        await _broadcaster(request).publish(
            {"type": "upsert", "kind": "component", "id": doc["id"], "scope": sk, "component": store.summary(doc)}
        )

    # 조립된 하네스가 있으면 하네스 저장소에 저장(하네스 화면에 등장 · eject/run 가능).
    harness = dset.get("harness")
    harness_saved: dict[str, Any] | None = None
    if isinstance(harness, dict) and harness.get("yaml"):
        hstore = _store(request)
        hname = harness.get("name") or "agent"
        hid = safe_id(hname)
        if hid in ("harness", "agent"):  # 한글 등 비ASCII 이름은 fallback 로 뭉개짐 → 이름 해시로 고유화(충돌 방지)
            hid = "agent-" + hashlib.sha1(hname.encode("utf-8")).hexdigest()[:8]  # noqa: S324 - id 슬러그(비암호)
        hdoc = hstore.put(
            sk, hid, user["id"], harness.get("name") or hid, harness.get("description") or "", harness["yaml"]
        )
        harness_saved = {"id": hdoc["id"], "name": hdoc["name"], "version": hdoc["version"]}
        await _broadcaster(request).publish(
            {"type": "upsert", "id": hdoc["id"], "scope": sk, "harness": hstore.summary(hdoc)}
        )

    cstore.set_component(sk, cid, harness_saved["id"] if harness_saved else (saved[0]["id"] if saved else ""))
    ok_count = sum(1 for s in saved if s["validation"]["ok"])
    note = f"{len(saved)}개 구성요소 저장(검증 통과 {ok_count}개)"
    note += f" + 하네스 '{harness_saved['name']}' 저장" if harness_saved else ""
    note += ". 각 구성요소는 '내 구성요소'에서 테스트하면 사용가능(ready)이 됩니다."
    cstore.add_message(sk, cid, "assistant", note, {"kind": "commit", "saved": saved, "harness": harness_saved})
    header = cstore.header(sk, cid)
    if header is not None:
        await _broadcaster(request).publish(
            {"type": "upsert", "kind": "conversation", "id": cid, "scope": sk, "conversation": cstore.summary(header)}
        )
    return {"ok": True, "saved": saved, "harness": harness_saved, "conversation_id": cid}


@app.post("/studio/conversations/{cid}/test")
async def studio_test(
    request: Request, cid: str, scope: str = Query("personal"), user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    """대화의 저장된 구성요소들을 인라인 테스트(LLM 심사) — 통과분은 ready 로. 결과를 대화 메시지로 남긴다."""
    sk = _resolve_scope(request, user, scope, write=True)
    cstore = _conversation_store(request)
    conv = cstore.get(sk, cid)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"대화 '{cid}' 없음(scope={scope})")
    comp_dicts = (conv.get("draft_set") or {}).get("components") or []
    complete = _llm_complete(request)
    if complete is None:
        raise HTTPException(status_code=400, detail="LLM 키가 없습니다 — 설정에서 LLM 키를 등록하세요")
    store = _component_store(request)
    results: list[dict[str, Any]] = []
    for cd in comp_dicts:
        cid_r = cd.get("id")
        doc = store.get(sk, cid_r) if cid_r else None
        if doc is None or doc["status"] == "draft":
            continue  # 저장(valid) 안 된 구성요소는 스킵
        comp = Component.model_validate_json(doc["data"])
        result = test_component(comp, complete=complete)
        if result.get("pass"):
            updated = store.set_status(sk, cid_r, "ready")
            await _broadcaster(request).publish(
                {"type": "upsert", "kind": "component", "id": cid_r, "scope": sk,
                 "component": store.summary(updated or doc)}
            )
        results.append({"id": cid_r, "name": comp.name, "pass": bool(result.get("pass")), "risk": result.get("risk")})
    if not results:
        raise HTTPException(status_code=400, detail="테스트할 저장된(valid) 구성요소가 없습니다 — 먼저 저장하세요")
    passed = sum(1 for r in results if r["pass"])
    verdicts = ", ".join(f"{r['name']}={'✅' if r['pass'] else '보류'}" for r in results)
    note = f"테스트: {passed}/{len(results)} 통과. {verdicts}"
    msg = cstore.add_message(sk, cid, "assistant", note, {"kind": "test", "results": results})
    header = cstore.header(sk, cid)
    if header is not None:
        await _broadcaster(request).publish(
            {"type": "upsert", "kind": "conversation", "id": cid, "scope": sk, "conversation": cstore.summary(header)}
        )
    return {"results": results, "message": msg}


@app.post("/studio/conversations/{cid}/run")
@limiter.limit("30/minute")
def studio_run_endpoint(
    request: Request,
    cid: str,
    body: StudioRunBody,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """조립된 에이전트를 테스트 입력으로 실행(미리보기) — build→run 루프(Phase 14 에이전트 빌더 경험).

    대화의 초안들로 resolve → 합성 시스템 프롬프트를 앱 등록 키로 단일턴 실행. MCP 도구는 실행 안 함
    (프롬프트·절차 미리보기). gap/에러를 함께 반환해 '실행하려면 뭘 더 넣어야 하나'를 보여준다.
    """
    sk = _resolve_scope(request, user, scope)
    conv = _conversation_store(request).get(sk, cid)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"대화 '{cid}' 없음(scope={scope})")
    drafts: list[Component] = []
    for cd in (conv.get("draft_set") or {}).get("components") or []:
        try:
            drafts.append(Component.model_validate(cd))
        except Exception:  # noqa: BLE001 — 손상 초안은 스킵
            continue
    res = _app_settings(request).resolve()
    key, provider = res["llm_key"], res["provider"] or "anthropic"
    if not key:
        raise HTTPException(status_code=400, detail="LLM 키가 없습니다 — 설정에서 LLM 키를 등록하세요")
    model = DEFAULT_MODEL.get(provider, "")
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    def execute(built: Any, msgs: list[dict[str, Any]]) -> dict[str, Any]:
        # Anthropic + 원격 MCP 서버가 있으면 실제 runtime 으로 도구까지 실행(커넥터). 아니면 프롬프트 미리보기.
        if provider == "anthropic" and built.mcp_servers:
            b = built.model_copy(update={"messages": msgs})
            out = AnthropicRunner(api_key=key).run(b)
            return {"output": out.text or "", "mode": "prompt" if out.dry_run else "tools"}
        text = _provider_complete_text(provider, model, key, built.system, msgs, max_tokens=1024)
        return {"output": text, "mode": "prompt"}

    return _studio_run(drafts, messages, execute)


# ── 사용자별 LLM 설정 (화면에서 입력·저장 · provider/모델 선택 · 키 암호화) ──


@app.get("/settings/llm")
def get_llm_settings(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """앱 LLM/임베딩 키 상태 — provider·키 설정 여부(마스킹). 원문 키는 반환하지 않는다."""
    return _app_settings(request).status()


@app.put("/settings/llm")
def put_llm_settings(
    request: Request, body: LlmSettingsBody, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    """앱 LLM/임베딩 키 저장 — 키는 None=유지·""=삭제·값=교체(암호화). 임베딩 키 변경은 재시작 후 인덱스 반영."""
    return _app_settings(request).put(
        provider=body.provider,
        llm_key=body.llm_key,
        embedding_key=body.embedding_key,
        search_key=body.search_key,
    )


@app.post("/settings/llm/verify")
def verify_llm_settings(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    """등록된 LLM/임베딩 키로 최소 호출을 시도해 실제 연동 여부 확인(원문 키는 반환 안 함)."""
    res = _app_settings(request).resolve()
    out: dict[str, str] = {}
    if not res["llm_key"]:
        out["llm"] = "unset"
    else:
        provider = res["provider"] or "anthropic"
        try:
            _provider_verify_key(provider, DEFAULT_MODEL.get(provider, ""), res["llm_key"])
            out["llm"] = "ok"
        except Exception as exc:  # noqa: BLE001 — 인증/네트워크/SDK 오류를 요약 전달
            out["llm"] = f"error: {type(exc).__name__}"
    if not res["embedding_key"]:
        out["embedding"] = "unset"
    else:
        try:
            from harness_catalog import OpenAIEmbedder

            OpenAIEmbedder(api_key=res["embedding_key"]).embed(["ping"])
            out["embedding"] = "ok"
        except Exception as exc:  # noqa: BLE001
            out["embedding"] = f"error: {type(exc).__name__}"
    if not res.get("search_key"):
        out["search"] = "unset"
    else:
        from .web_search import web_search

        r = web_search(res["search_key"], "ping", max_results=1)
        out["search"] = "error" if r.startswith(("웹검색 실패", "웹검색 미설정")) else "ok"
    return out


# to_harness_yaml 은 harness_build 로 이동(스튜디오 하네스 조립과 공유, 순환 import 회피).

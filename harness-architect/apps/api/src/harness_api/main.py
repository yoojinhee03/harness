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

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from harness_catalog import Recommender, build_registry, resolve_catalog_dir
from harness_resolver import HarnessConfig, InMemoryRegistry, ResolveResult, resolve
from harness_runtime import AnthropicRunner, available_targets, build_request, emit
from sse_starlette.sse import EventSourceResponse

from .accounts import AccountStore
from .schemas import (
    CatalogItem,
    GenerateResponse,
    HarnessSaveBody,
    KeyUpdate,
    MemberBody,
    RecommendRequest,
    RegisterBody,
    ResolveRequest,
    RunRequest,
    TeamCreateBody,
)
from .store import Broadcaster, HarnessStore, event_stream, resolve_store_dir, safe_id

log = logging.getLogger("harness_api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 카탈로그를 한 번 로드해 레지스트리·추천기를 준비한다. 없으면 빈 상태로 기동.
    try:
        catalog_dir = resolve_catalog_dir()
        registry = build_registry(catalog_dir)
        log.info("카탈로그 로드: %s개 (%s)", len(registry.all()), catalog_dir)
    except FileNotFoundError as exc:
        log.warning("카탈로그를 찾지 못함 — 빈 레지스트리로 기동: %s", exc)
        registry = InMemoryRegistry([])
    app.state.registry = registry
    app.state.keys = {}  # 런타임 API 키(메모리만 — 디스크 저장 안 함)
    app.state.recommender = Recommender(registry)
    # 공유 하네스 저장소(스코프 격리) + 계정(사용자·팀) + SSE 브로드캐스터.
    store_dir = resolve_store_dir()
    app.state.store = HarnessStore(store_dir / "harnesses")
    app.state.accounts = AccountStore(store_dir / "accounts")
    app.state.broadcaster = Broadcaster()
    log.info("하네스 저장소: %s (스코프 격리 · 계정 인증)", store_dir)
    yield


app = FastAPI(
    title="AI 하네스 아키텍트 API",
    version="0.1.0",
    description="자연어 설명 → 하네스 구성요소 추천 → 검증 → harness.yaml 생성.",
    lifespan=lifespan,
)

# CORS — 기본은 개발 편의상 전체 허용. 배포 시 HARNESS_CORS_ORIGINS(쉼표 구분)로 좁힌다.
_cors_origins = [o.strip() for o in os.environ.get("HARNESS_CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _registry(request: Request) -> InMemoryRegistry:
    return cast(InMemoryRegistry, request.app.state.registry)


def _recommender(request: Request) -> Recommender:
    return cast(Recommender, request.app.state.recommender)


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    reg = _registry(request)
    return {"status": "ok", "catalog_size": len(reg.all())}


# ─────────────────────────── 설정: API 키 (메모리만 · 마스킹 반환) ───────────────────────────

_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "voyage": "VOYAGE_API_KEY"}


def _mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "****"


def _apply_keys(request: Request) -> None:
    """메모리 키를 os.environ 에 반영하고 추천기를 재구성(embedder/reasoner 모드 전환)."""
    keys: dict[str, str] = request.app.state.keys
    for provider, env in _KEY_ENV.items():
        val = keys.get(provider)
        if val:
            os.environ[env] = val
        else:
            os.environ.pop(env, None)
    request.app.state.recommender = Recommender(_registry(request))


def _provider_status(keys: dict[str, str], provider: str) -> dict[str, Any]:
    key = keys.get(provider)
    return {"set": bool(key), "masked": _mask(key) if key else None}


def _key_status(request: Request) -> dict[str, Any]:
    from harness_catalog import load_settings

    keys: dict[str, str] = request.app.state.keys
    s = load_settings()
    return {
        "anthropic": _provider_status(keys, "anthropic"),
        "voyage": _provider_status(keys, "voyage"),
        # 유효 품질 모드(연동 결과가 실제로 어디에 반영되는지)
        "quality_mode": {
            "embedder": "voyage" if s.use_voyage else "local",
            "ranker": "claude" if s.use_claude else "heuristic",
        },
    }


@app.get("/settings/keys")
def get_keys(request: Request) -> dict[str, Any]:
    return _key_status(request)


@app.put("/settings/keys")
def put_keys(request: Request, body: KeyUpdate) -> dict[str, Any]:
    """키 설정/수정. 빈 문자열·None 은 변경 없음(삭제는 DELETE)."""
    keys: dict[str, str] = request.app.state.keys
    if body.anthropic_api_key:
        keys["anthropic"] = body.anthropic_api_key.strip()
    if body.voyage_api_key:
        keys["voyage"] = body.voyage_api_key.strip()
    _apply_keys(request)
    return _key_status(request)


@app.delete("/settings/keys/{provider}")
def delete_key(request: Request, provider: str) -> dict[str, Any]:
    if provider not in _KEY_ENV:
        raise HTTPException(status_code=404, detail=f"알 수 없는 provider: {provider}")
    request.app.state.keys.pop(provider, None)
    _apply_keys(request)
    return _key_status(request)


@app.post("/settings/keys/verify")
def verify_keys(request: Request) -> dict[str, str]:
    """설정된 키로 최소 호출을 시도해 실제 연동 여부를 확인(원본 키는 반환 안 함)."""
    keys: dict[str, str] = request.app.state.keys
    out: dict[str, str] = {}

    ak = keys.get("anthropic")
    if not ak:
        out["anthropic"] = "unset"
    else:
        try:
            import anthropic

            anthropic.Anthropic(api_key=ak).messages.create(
                model="claude-sonnet-5", max_tokens=1, messages=[{"role": "user", "content": "ping"}]
            )
            out["anthropic"] = "ok"
        except Exception as exc:  # noqa: BLE001 - 네트워크/인증 오류를 사용자에게 요약 전달
            out["anthropic"] = f"error: {type(exc).__name__}"

    vk = keys.get("voyage")
    if not vk:
        out["voyage"] = "unset"
    else:
        try:
            import voyageai

            voyageai.Client(api_key=vk).embed(["ping"], model="voyage-3.5", input_type="document")
            out["voyage"] = "ok"
        except Exception as exc:  # noqa: BLE001
            out["voyage"] = f"error: {type(exc).__name__}"
    return out


@app.get("/catalog", response_model=list[CatalogItem])
def catalog(
    request: Request,
    type: str | None = Query(default=None, description="skill|mcp|context|hook"),
    capability: str | None = Query(default=None, description="provides 로 필터"),
) -> list[CatalogItem]:
    comps = _registry(request).all()
    if type:
        comps = [c for c in comps if c.type == type]
    if capability:
        comps = [c for c in comps if capability in c.provides or capability in c.capability_tags]
    return [CatalogItem.from_component(c) for c in comps]


@app.get("/catalog/{component_id}")
def catalog_detail(request: Request, component_id: str) -> dict[str, Any]:
    c = _registry(request).get(component_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"컴포넌트 '{component_id}' 없음")
    return c.model_dump()


@app.post("/recommend")
def recommend(request: Request, body: RecommendRequest) -> dict[str, Any]:
    result = _recommender(request).recommend(body.description, top_k=body.top_k)
    return result.model_dump()


@app.post("/resolve", response_model=ResolveResult)
def resolve_endpoint(request: Request, body: ResolveRequest) -> ResolveResult:
    config = body.to_config()
    return resolve(config, _registry(request))


@app.post("/generate", response_model=GenerateResponse)
def generate(request: Request, body: ResolveRequest) -> GenerateResponse:
    config = body.to_config()
    result = resolve(config, _registry(request))
    return GenerateResponse(
        yaml=to_harness_yaml(config),
        ok=result.ok,
        gaps=len(result.diagnostics.gaps),
        warnings=len(result.diagnostics.warnings),
        errors=len(result.diagnostics.errors),
    )


@app.post("/run")
def run_endpoint(request: Request, body: RunRequest) -> dict[str, Any]:
    """resolve → build_request → (키 있으면) Anthropic 전송, 없으면 dry_run. 런타임 관통."""
    config = body.to_config()
    result = resolve(config, _registry(request))
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
    request: Request, body: ResolveRequest, target: str = Query("claude-code")
) -> dict[str, Any]:
    """resolve → emit(target). ResolvedHarness IR 을 런타임 네이티브 파일 트리로 컴파일 (Phase 5)."""
    if target not in available_targets():
        raise HTTPException(status_code=400, detail=f"지원하지 않는 타깃: {target} (가능: {available_targets()})")
    result = resolve(body.to_config(), _registry(request))
    if not result.ok or result.resolved is None:
        return {"ok": False, "target": target, "diagnostics": result.diagnostics.model_dump(), "files": None}
    return {"ok": True, "target": target, "files": emit(result.resolved, target)}


# ─────────────── 멀티테넌시: 인증(Bearer) + 팀(자가서브) + 스코프 격리 저장소 ───────────────


def _store(request: Request) -> HarnessStore:
    return cast(HarnessStore, request.app.state.store)


def _broadcaster(request: Request) -> Broadcaster:
    return cast(Broadcaster, request.app.state.broadcaster)


def _accounts(request: Request) -> AccountStore:
    return cast(AccountStore, request.app.state.accounts)


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    """Bearer 토큰으로 사용자 신원 확인. SSE(EventSource)는 헤더를 못 실어 ?token= 도 허용."""
    raw = ""
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    elif token:
        raw = token
    user = _accounts(request).user_by_token(raw)
    if user is None:
        raise HTTPException(status_code=401, detail="인증 필요 — Bearer 토큰(/auth/register 로 발급)")
    return user


def _resolve_scope(request: Request, user: dict[str, Any], scope: str) -> str:
    """쿼리 scope('personal'|'team:<tid>')를 스코프 키로. 팀은 멤버십을 검사(격리)."""
    if scope in ("", "personal"):
        return f"personal:{user['id']}"
    if scope.startswith("team:"):
        tid = scope[len("team:") :]
        if not _accounts(request).is_member(tid, user["id"]):
            raise HTTPException(status_code=403, detail="이 팀의 멤버가 아닙니다")
        return f"team:{tid}"
    raise HTTPException(status_code=400, detail=f"잘못된 scope: {scope} (personal|team:<id>)")


# ── 인증 · 팀 ──


@app.post("/auth/register")
def register(request: Request, body: RegisterBody) -> dict[str, Any]:
    """handle 로 계정 생성 + 토큰 발급(원문은 이 응답에서만 노출)."""
    try:
        return _accounts(request).register(body.handle)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/me")
def whoami(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {**user, "teams": _accounts(request).teams_of(user["id"])}


@app.post("/auth/token/rotate")
def rotate_token(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    """현재 사용자의 토큰 재발급(기존 무효화). 새 토큰 원문을 1회 반환."""
    return {"token": _accounts(request).rotate_token(user["id"])}


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
        return _accounts(request).add_member(tid, user["id"], body.handle)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── 스코프 격리 하네스 저장소 (웹 ↔ VSCode 확장 양방향 동기화) ──


@app.get("/harnesses")
def list_harnesses(request: Request, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    """내 가시 스코프(personal + 내 팀들)의 하네스 요약 목록(최신순)."""
    scopes = sorted(_accounts(request).visible_scope_keys(user["id"]))
    return _store(request).list_scopes(scopes)


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
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """하네스 저장(upsert). 스코프(personal|team:<id>) 안에 저장하고 그 스코프 구독자에게 SSE 푸시."""
    sk = _resolve_scope(request, user, scope)
    store = _store(request)
    doc = store.put(sk, hid, user["id"], body.name, body.description, body.yaml)
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
    sk = _resolve_scope(request, user, scope)
    if not _store(request).delete(sk, hid):
        raise HTTPException(status_code=404, detail=f"하네스 '{hid}' 없음(scope={scope})")
    await _broadcaster(request).publish({"type": "delete", "id": safe_id(hid), "scope": sk})
    return {"ok": True, "id": safe_id(hid), "scope": sk}


def to_harness_yaml(config: HarnessConfig) -> str:
    """HarnessConfig → harness.yaml 텍스트 (스펙 §2 구조)."""
    doc: dict[str, Any] = {
        "apiVersion": config.apiVersion,
        "kind": config.kind,
        "metadata": config.metadata.model_dump(exclude_defaults=False),
    }
    if config.extends:
        doc["extends"] = config.extends
    doc["model"] = config.model.model_dump()
    if config.prompt is not None:
        # 최소 표현 — 기본값/None 필드는 생략해 authored 입력에 가깝게 직렬화.
        doc["prompt"] = config.prompt.model_dump(exclude_defaults=True, exclude_none=True)
    if config.permissions:
        doc["permissions"] = config.permissions
    doc["components"] = [
        ({"ref": s.ref, "config": s.config} if s.config else {"ref": s.ref})
        for s in config.components
    ]
    if config.budget:
        doc["budget"] = config.budget.model_dump()
    return cast(str, yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))

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
from contextlib import asynccontextmanager
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from harness_catalog import Recommender, build_registry, resolve_catalog_dir
from harness_resolver import HarnessConfig, InMemoryRegistry, ResolveResult, resolve
from harness_runtime import AnthropicRunner, build_request

from .schemas import (
    CatalogItem,
    GenerateResponse,
    RecommendRequest,
    ResolveRequest,
    RunRequest,
)

log = logging.getLogger("harness_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 카탈로그를 한 번 로드해 레지스트리·추천기를 준비한다. 없으면 빈 상태로 기동.
    try:
        catalog_dir = resolve_catalog_dir()
        registry = build_registry(catalog_dir)
        log.info("카탈로그 로드: %s개 (%s)", len(registry.all()), catalog_dir)
    except FileNotFoundError as exc:
        log.warning("카탈로그를 찾지 못함 — 빈 레지스트리로 기동: %s", exc)
        registry = InMemoryRegistry([])
    app.state.registry = registry
    app.state.recommender = Recommender(registry)
    yield


app = FastAPI(
    title="AI 하네스 아키텍트 API",
    version="0.1.0",
    description="자연어 설명 → 하네스 구성요소 추천 → 검증 → harness.yaml 생성.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발용. 배포 시 좁힌다.
    allow_methods=["*"],
    allow_headers=["*"],
)


def _registry(request: Request) -> InMemoryRegistry:
    return request.app.state.registry


def _recommender(request: Request) -> Recommender:
    return request.app.state.recommender


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    reg = _registry(request)
    return {"status": "ok", "catalog_size": len(reg.all())}


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
    built = build_request(result.resolved, body.prompt)
    run = AnthropicRunner().run(built)
    return {
        "ok": True,
        "built": {
            "model": built.model,
            "system_chars": len(built.system),
            "mcp_servers": [m["id"] for m in built.mcp_servers],
            "hook_plan": built.hook_plan,
            "permissions": built.permissions,
        },
        "run": run.model_dump(),
    }


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
    if config.permissions:
        doc["permissions"] = config.permissions
    doc["components"] = [
        ({"ref": s.ref, "config": s.config} if s.config else {"ref": s.ref})
        for s in config.components
    ]
    if config.budget:
        doc["budget"] = config.budget.model_dump()
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)

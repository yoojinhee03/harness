"""앱(인스턴스) 레벨 LLM 설정 — 화면에서 등록하는 LLM 키(provider)와 임베딩 키(OpenAI).

서버 env 키는 쓰지 않는다. 키는 crypto 로 at-rest 암호화하고, 조회(status)는 마스킹만 노출한다.
단일 행(id='app'). 카탈로그 임베딩 인덱스가 전역이라 키도 인스턴스 단위다(자체호스팅/단일조직 전제).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from .crypto import decrypt, encrypt, mask
from .db import app_settings
from .store import now_iso

PROVIDERS = ("anthropic", "openai")
_ROW_ID = "app"


class AppSettingsStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _row(self) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            r = conn.execute(select(app_settings).where(app_settings.c.id == _ROW_ID)).mappings().first()
        return dict(r) if r else None

    def resolve(self) -> dict[str, Any]:
        """내부용 — 복호한 키 포함. provider/llm_key/embedding_key/search_key."""
        r = self._row()
        if r is None:
            return {"provider": "anthropic", "llm_key": "", "embedding_key": "", "search_key": ""}
        return {
            "provider": r["provider"] or "anthropic",
            "llm_key": decrypt(r["llm_key_enc"]),
            "embedding_key": decrypt(r["embedding_key_enc"]),
            "search_key": decrypt(r["search_key_enc"] or ""),
        }

    def status(self) -> dict[str, Any]:
        """표시용 — 원문 키 없이 set/masked 만."""
        res = self.resolve()
        return {
            "provider": res["provider"],
            "llm": {"set": bool(res["llm_key"]), "masked": mask(res["llm_key"])},
            "embedding": {"set": bool(res["embedding_key"]), "masked": mask(res["embedding_key"])},
            "search": {"set": bool(res["search_key"]), "masked": mask(res["search_key"])},
        }

    def put(
        self,
        *,
        provider: str | None = None,
        llm_key: str | None = None,
        embedding_key: str | None = None,
        search_key: str | None = None,
    ) -> dict[str, Any]:
        """저장. 키는 None=유지 · ""=삭제 · 값=교체(암호화). provider 도 None=유지."""
        ts = now_iso()
        existing = self._row()

        def key_enc(new: str | None, cur: str) -> str:
            if new is None:
                return cur
            return encrypt(new) if new else ""

        llm_enc = key_enc(llm_key, existing["llm_key_enc"] if existing else "")
        emb_enc = key_enc(embedding_key, existing["embedding_key_enc"] if existing else "")
        search_enc = key_enc(search_key, (existing.get("search_key_enc") or "") if existing else "")
        prov = (
            provider if provider is not None else (existing["provider"] if existing else "anthropic")
        ) or "anthropic"
        if prov not in PROVIDERS:
            prov = "anthropic"

        with self.engine.begin() as conn:
            if existing is None:
                conn.execute(
                    insert(app_settings).values(
                        id=_ROW_ID, provider=prov, llm_key_enc=llm_enc, embedding_key_enc=emb_enc,
                        search_key_enc=search_enc, updated_at=ts,
                    )
                )
            else:
                conn.execute(
                    update(app_settings)
                    .where(app_settings.c.id == _ROW_ID)
                    .values(
                        provider=prov, llm_key_enc=llm_enc, embedding_key_enc=emb_enc,
                        search_key_enc=search_enc, updated_at=ts,
                    )
                )
        return self.status()

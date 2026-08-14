"""사용자별 LLM 설정 — 암호화·마스킹·요청별 provider 주입 · OpenAI 임베더 선택.

원문 키는 응답에 절대 안 실리고(마스킹), 저장은 at-rest 암호화. 주입된 complete 로 provider 경로 검증.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("HARNESS_SECRET_KEY", "test-secret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from harness_api.main import app

    with TestClient(app) as c:
        yield c


def auth(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/auth/dev-login", json={"email": email})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ── crypto ──


def test_crypto_roundtrip_and_mask(monkeypatch):
    monkeypatch.setenv("HARNESS_SECRET_KEY", "s")
    from harness_api.crypto import decrypt, encrypt, mask

    assert decrypt(encrypt("sk-abc123")) == "sk-abc123"
    assert encrypt("") == "" and decrypt("") == ""
    assert mask("sk-abcd1234") == "…1234"
    assert mask("") is None
    assert decrypt("not-a-valid-token") == ""  # 손상 → 미설정 취급


# ── AppSettingsStore ──


def test_app_settings_store_encrypt_keep_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_SECRET_KEY", "s")
    from harness_api.db import make_engine
    from harness_api.llm_settings import AppSettingsStore

    st = AppSettingsStore(make_engine(f"sqlite:///{tmp_path / 'l.db'}"))
    assert st.status()["llm"]["set"] is False  # 기본 미설정

    st.put(provider="openai", llm_key="sk-llm-xyz", embedding_key="sk-emb-abc")
    s = st.status()
    assert s["provider"] == "openai"
    assert s["llm"]["set"] and s["llm"]["masked"] == "…-xyz"
    assert "sk-llm-xyz" not in str(s) and "sk-emb-abc" not in str(s)  # 원문 비노출
    r = st.resolve()
    assert r["llm_key"] == "sk-llm-xyz" and r["embedding_key"] == "sk-emb-abc"  # 내부는 복호

    st.put(llm_key=None, embedding_key="")  # None=유지, ""=삭제
    r2 = st.resolve()
    assert r2["llm_key"] == "sk-llm-xyz" and r2["embedding_key"] == ""


# ── API (마스킹·인증·게이트) ──


def test_llm_settings_api_masks_key(client):
    a = auth(client, "alice@x.io")
    assert client.get("/settings/llm", headers=a).json()["llm"]["set"] is False
    r = client.put("/settings/llm", json={"provider": "anthropic", "llm_key": "sk-test-9999"}, headers=a)
    assert r.status_code == 200 and r.json()["llm"]["set"] is True
    assert "sk-test-9999" not in r.text  # 원문 비노출
    body = client.get("/settings/llm", headers=a).json()
    assert body["llm"]["masked"] == "…9999" and body["provider"] == "anthropic"


def test_settings_llm_requires_auth(client):
    assert client.get("/settings/llm").status_code == 401


def test_author_uses_injected_provider(client, monkeypatch):
    """앱 LLM 키가 있으면 author 가 주입된 provider 호출을 사용(휴리스틱이 아니라)."""
    import harness_api.main as m

    monkeypatch.setattr(
        m,
        "_provider_complete_json",
        lambda provider, model, key, system, user, *, max_tokens=1024: {
            "name": "주입된 컨텍스트", "summary": "s", "description": "d", "body": "b",
            "provides": ["convention.coding"],
        },
    )
    a = auth(client, "alice@x.io")
    client.put("/settings/llm", json={"llm_key": "sk-x"}, headers=a)  # 키 있어야 complete 생성
    comp = client.post("/components/author", json={"prompt": "뭐든"}, headers=a).json()["component"]
    assert comp["name"] == "주입된 컨텍스트" and comp["provides"] == ["convention.coding"]


# ── 임베더 선택 (Voyage 제거: openai | local) ──


def test_embedder_choice():
    from harness_catalog.settings import Settings

    def mk(**kw):
        base = dict(
            anthropic_key=None, voyage_key=None, embedder_mode="auto",
            ranker_mode="heuristic", embed_model="x", claude_model="y",
        )
        base.update(kw)
        return Settings(**base)  # type: ignore[arg-type]

    assert mk().embedder_choice == "local"
    assert mk(openai_key="o").embedder_choice == "openai"  # auto + openai 키 → openai
    assert mk(embedder_mode="openai").embedder_choice == "openai"  # 명시 강제
    assert mk(openai_key="o", embedder_mode="local").embedder_choice == "local"  # 명시가 auto 무시

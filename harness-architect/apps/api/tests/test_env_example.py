"""`.env.example` ↔ 코드 드리프트 펜스.

이 문서가 코드보다 낡으면 조용히 사람을 헷갈리게 한다. 실제로 그랬다: settings 가 18개 env 를
읽는데 예시엔 7개만 있었고, 제거된 공급자(`VOYAGE_API_KEY`)는 남아 있고 실제로 쓰는
`OPENAI_API_KEY` 는 빠져 있었다. 품질 모드를 켜려는 사람은 예시만 보고는 켤 수 없었다.

그래서 **코드가 읽는 모든 env 가 예시에 언급되는지**를 테스트로 고정한다. 값까지 맞출 필요는
없다(주석 처리된 옵션이 대부분) — 이름이 등장하기만 하면 된다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[4]  # <repo>
_ENV_EXAMPLE = _ROOT / ".env.example"
_SOURCE_DIRS = [_ROOT / "harness-architect" / "packages", _ROOT / "harness-architect" / "apps"]

# 코드에서 env 를 읽는 형태들.
_READ = re.compile(r'os\.environ(?:\.get)?\(\s*"([A-Z][A-Z0-9_]*)"|os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"')

# 예시에 적지 않는 것들 — 테스트 전용이거나 표준 런타임 변수.
_EXEMPT = {
    "PATH",
    "HOME",
    "PYTEST_CURRENT_TEST",
}


def _env_names_in_source() -> set[str]:
    names: set[str] = set()
    for root in _SOURCE_DIRS:
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if ".venv" in parts or "tests" in parts or "__pycache__" in parts:
                continue
            for m in _READ.finditer(path.read_text(encoding="utf-8")):
                names.add(m.group(1) or m.group(2))
    return names - _EXEMPT


def test_env_example_exists():
    assert _ENV_EXAMPLE.is_file(), f"{_ENV_EXAMPLE} 가 없습니다"


def test_every_env_var_read_by_code_is_documented():
    """코드가 읽는 env 는 전부 `.env.example` 에 등장해야 한다(주석 처리도 인정)."""
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = sorted(name for name in _env_names_in_source() if name not in text)
    assert missing == [], (
        "`.env.example` 에 없는 환경변수: " + ", ".join(missing) + "\n"
        "코드가 읽는 설정은 예시에도 적어야 한다 — 안 그러면 켤 방법을 아무도 모른다."
    )


def test_no_removed_provider_leftovers():
    """제거된 공급자의 잔재가 남아 있으면 안 된다 — 채워도 아무 일이 안 일어난다."""
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    for dead in ("VOYAGE_API_KEY", "HARNESS_EMBED_MODEL="):
        assert dead not in text, f"{dead} 는 더 이상 쓰이지 않는다"


@pytest.mark.parametrize(
    "name",
    ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HARNESS_SECRET_KEY"],
)
def test_key_variables_are_uncommented(name):
    """실제로 채워야 하는 키는 주석이 아니라 빈 대입으로 둔다 — cp 후 바로 채울 수 있게."""
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    assert re.search(rf"^{name}=", text, re.M), f"{name} 이 주석 처리돼 있다"

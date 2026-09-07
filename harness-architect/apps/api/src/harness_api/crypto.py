"""사용자 API 키의 at-rest 암호화 — 서버 시크릿(HARNESS_SECRET_KEY)으로 Fernet.

키를 평문으로 DB 에 두지 않는다. 조회 응답엔 절대 원문을 싣지 않고 `mask()` 로 끝 4자만 노출한다.
`HARNESS_SECRET_KEY` 가 없으면 **새 키 저장을 거부한다**. 예전엔 공개된 고정 문자열로 조용히
암호화하고 경고 로그만 남겼는데, 로그 한 줄은 놓치기 쉽고 그렇게 저장된 사용자 API 키는 레포를
읽을 수 있는 누구나 복호할 수 있다("암호화됐다"는 착각이 평문보다 위험하다).

읽기는 계속 폴백을 허용한다 — 이미 개발용 키로 저장한 로컬 데이터를 못 읽게 만들면 조용히
"키 미설정"으로 보여 더 헷갈린다. 즉 **쓰기는 막고 읽기는 살린다.**
급하면 `HARNESS_ALLOW_INSECURE_SECRET=on` 으로 예전 동작을 되살릴 수 있다(로컬 전용).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("harness_api")

_DEV_SECRET = "harness-dev-insecure-secret"  # HARNESS_SECRET_KEY 없을 때 폴백(개발 전용)


def secret_is_insecure() -> bool:
    """서버 시크릿이 미설정인가 — `/ready` 가 운영에 노출한다(로그보다 눈에 띄게)."""
    return not os.environ.get("HARNESS_SECRET_KEY")


def _allow_insecure() -> bool:
    return os.environ.get("HARNESS_ALLOW_INSECURE_SECRET", "").lower() in ("on", "1", "true")


def _fernet() -> Fernet:
    secret = os.environ.get("HARNESS_SECRET_KEY")
    if not secret:
        log.warning("HARNESS_SECRET_KEY 미설정 — 개발용 키 사용(신규 키 저장은 거부됨)")
        secret = _DEV_SECRET
    # 임의 문자열 시크릿 → Fernet 규격 키(32바이트 urlsafe-base64)로 파생.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


class InsecureSecretError(RuntimeError):
    """서버 시크릿 없이 새 키를 저장하려 했다 — 조용히 약한 암호화를 하는 대신 거부한다."""


def encrypt(plaintext: str) -> str:
    """평문 키 → 암호문(str). 빈 값은 빈 값 그대로(미설정 표현).

    시크릿이 없으면 거부한다 — 공개된 고정 키로 암호화한 값은 암호화가 아니다.
    """
    if not plaintext:
        return ""
    if secret_is_insecure() and not _allow_insecure():
        raise InsecureSecretError(
            "HARNESS_SECRET_KEY 가 설정되지 않아 키를 저장할 수 없습니다. "
            "서버 시크릿을 설정하세요(로컬에서 임시로 진행하려면 HARNESS_ALLOW_INSECURE_SECRET=on)."
        )
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """암호문 → 평문. 복호 실패(시크릿 변경 등)면 빈 값(미설정 취급)."""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        log.warning("저장된 키 복호 실패 — 미설정으로 취급(시크릿이 바뀌었을 수 있음)")
        return ""


def mask(plaintext: str) -> str | None:
    """표시용 마스킹 — 끝 4자만. 미설정이면 None."""
    if not plaintext:
        return None
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"…{tail}"

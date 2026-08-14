"""사용자 API 키의 at-rest 암호화 — 서버 시크릿(HARNESS_SECRET_KEY)으로 Fernet.

키를 평문으로 DB 에 두지 않는다. 조회 응답엔 절대 원문을 싣지 않고 `mask()` 로 끝 4자만 노출한다.
HARNESS_SECRET_KEY 미설정 시 개발용 결정적 키로 폴백하되 경고 — 프로덕션은 반드시 설정할 것.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("harness_api")

_DEV_SECRET = "harness-dev-insecure-secret"  # HARNESS_SECRET_KEY 없을 때 폴백(개발 전용)


def _fernet() -> Fernet:
    secret = os.environ.get("HARNESS_SECRET_KEY")
    if not secret:
        log.warning("HARNESS_SECRET_KEY 미설정 — 개발용 키로 암호화(프로덕션에서 반드시 설정)")
        secret = _DEV_SECRET
    # 임의 문자열 시크릿 → Fernet 규격 키(32바이트 urlsafe-base64)로 파생.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """평문 키 → 암호문(str). 빈 값은 빈 값 그대로(미설정 표현)."""
    if not plaintext:
        return ""
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

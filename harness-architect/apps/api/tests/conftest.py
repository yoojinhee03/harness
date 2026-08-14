"""테스트 공통 설정 — 레이트리밋 비활성(반복 register 가 429 에 걸리지 않도록).

main 모듈 import 전에 env 를 세팅해야 하므로 conftest(수집 시 먼저 로드)에서 설정한다.
레이트리밋 자체의 동작은 test_ratelimit 에서 한정적으로 켜서 검증한다.
"""

import os

os.environ.setdefault("HARNESS_RATELIMIT", "off")
os.environ.setdefault("HARNESS_DEV_AUTH", "on")  # 테스트 로그인은 dev-login(이메일)으로

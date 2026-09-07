"""테스트 공통 설정 — 레이트리밋 비활성 + **저장소 격리**.

main 모듈 import 전에 env 를 세팅해야 하므로 conftest(수집 시 먼저 로드)에서 설정한다.
레이트리밋 자체의 동작은 test_ratelimit 에서 한정적으로 켜서 검증한다.

⚠️ **저장소 격리가 여기 있는 이유** — `HARNESS_STORE_DIR` 이 없으면 저장소가
`~/.harness/harnesses/harness.db` 를 쓴다. test_api.py 의 module-scope `client` 픽스처가 그걸
설정하지 않아 **개발자의 실 DB 에 테스트 데이터가 쌓이고 있었다.** 실제 피해:

  · 공출현 테이블에 `github-mcp+slack-mcp` 128쌍, 피드백에 정확히 20관측씩 — 전부 테스트 산물.
  · 그걸 실사용 데이터로 착각하면 "백로그 #2 의 데이터 게이트가 충족됐다"는 잘못된 판단으로 이어진다
    (실제로 한 번 오독할 뻔했다).
  · 테스트가 순서·과거 실행 이력에 의존하게 된다(격리 상실).

세션 단위 임시 디렉터리를 기본값으로 깔아, 개별 픽스처가 `HARNESS_STORE_DIR` 을 지정하지 않아도
홈 디렉터리를 건드리지 않게 한다. 개별 픽스처의 monkeypatch 는 이걸 덮어쓰므로 그대로 동작한다.
"""

import os
import tempfile

os.environ.setdefault("HARNESS_RATELIMIT", "off")
os.environ.setdefault("HARNESS_DEV_AUTH", "on")  # 테스트 로그인은 dev-login(이메일)으로
os.environ.setdefault("HARNESS_STORE_DIR", tempfile.mkdtemp(prefix="harness-test-store-"))

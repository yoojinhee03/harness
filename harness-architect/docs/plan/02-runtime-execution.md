# Phase 2 — 런타임 실연동 (Anthropic 호출 + sandbox 격리 실행)

> 설계: 기획 §3.2, 설계 훅 실행 모델 §3·§5. 현재 `builder`·`HookEngine` 은 스켈레톤이고
> 미등록 훅은 no-op 통과. 이 Phase 는 (a) 조립된 요청을 실제 Anthropic API 로 보내는 러너와
> (b) 훅을 sandbox 수준·timeout 으로 실행하는 실행기를 붙인다.

## 목표

`ResolvedHarness → build_request → 훅 체인(격리·timeout) → Anthropic 호출 → 응답 훅` 이
관통한다. 키 없으면 러너는 명확한 오류/드라이런으로 폴백.

## 작업

1. **AnthropicRunner** — `runtime/runner.py`. `build_request` 결과를 anthropic SDK 로 전송
   (`claude-sonnet-5`). 클라이언트 주입 가능(테스트는 fake). 키 없으면 `dry_run` 결과 반환.
2. **훅 실행기 (sandbox)** — `runtime/sandbox.py`. `Executor` 프로토콜 +
   - `InProcessExecutor`(sandbox=none, 신뢰 1st-party만),
   - `SubprocessExecutor`(sandbox=restricted, 별도 프로세스 + `timeout_ms` 강제; 네트워크/FS
     차단은 스텁 주석으로 남김).
   `HookEngine` 이 step.sandbox 에 맞는 실행기를 골라 `timeout_ms` 안에서 핸들러 실행.
3. **권한 강제** — 선언되지 않은 `can_modify_*`/`blocking` 은 런타임에서 차단(카탈로그 선언=상한).
4. **테스트** — fake 러너로 요청 조립·전송 계약 검증; 훅 실행기 timeout·fail_closed·차단·변형
   파이프라인 검증; 미선언 권한 강제 검증.

## 완료 기준

- [x] `AnthropicRunner` (주입 가능, 키 없으면 dry_run) + fake 테스트.
- [x] `Executor` 2종(InProcess/ThreadIsolated) + `HookEngine` 이 sandbox/timeout 적용.
- [x] 미선언 권한 런타임 차단·변형 무시 테스트.
- [x] fail_open/closed·blocking·변형 연쇄·timeout 테스트.
- [x] `POST /run` 으로 런타임 관통(API dry_run) + 테스트.
- [x] 전체 pytest 통과(41) · ruff/mypy 클린.

**구현 노트:** `sandbox.py`(Executor: InProcess=none / ThreadIsolated=restricted·external,
timeout 강제) · `runner.py`(AnthropicRunner, 주입 가능, 키 없으면 dry_run) 신설. `HookEngine`
이 step.sandbox 로 실행기 선택 + blocking/can_modify 상한 강제. 진짜 프로세스/WASM 격리·
네트워크 차단은 후속(경계 주석).

## 검증 한계

실제 Anthropic 응답은 키 필요. timeout·격리·차단·변형 의미론은 fake 핸들러/러너로 완전 검증.
`SubprocessExecutor` 의 네트워크·FS 차단(seccomp/WASM급)은 후속(주석으로 경계 표시).

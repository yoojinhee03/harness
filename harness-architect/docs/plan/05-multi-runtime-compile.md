# Phase 5 — 다중 런타임 컴파일 (`eject` / `materialize`) + CLI

> 설계: 기획 스코프(핵심 가치 "실행 가능한 설정") + harness.yaml 스펙. 지금 산출물은
> `harness.yaml`(선언)과 `ResolvedHarness`(검증된 IR — `harness_resolver.models.ResolvedHarness`)
> 에서 멈춘다. 이 Phase 는 IR 을 **실제 에이전트 런타임의 네이티브 포맷으로 방출**하는
> 컴파일러를 붙여, "설명→검증"에서 끝나던 흐름을 "→ 그대로 도는 설정"까지 잇는다.

## 왜 (차별화)

기존 플러그인은 각자 포맷(`.cursorrules` ≠ `CLAUDE.md` ≠ `skill.md` ≠ `mcp.json`)에 락인된다.
여기선 검증된 IR 하나를 여러 타깃으로 컴파일하므로 **"한 번 선언 → 어디서든 실행 + 이식"**
이 성립한다. 이게 v2 의 플래그십이자 제일 방어 가능한 차별점이다.

## 목표

`ResolvedHarness → Emitter → FileTree(경로→내용)` 가 관통한다. 첫 타깃은 **Claude Code**.
- CLI: `harness eject --to claude-code [--out ./ ] [--dry-run]`
- API: `POST /eject?target=claude-code` → 파일 트리(zip 또는 JSON)

## 작업

1. **Emitter 프로토콜** — `runtime/emit/base.py`. `Emitter.emit(resolved: ResolvedHarness) -> FileTree`
   (`FileTree = dict[str, str | bytes]`, 상대경로→내용). 타깃별 구현을 등록 가능하게(플러그인).
2. **ClaudeCodeEmitter** — `runtime/emit/claude_code.py`. IR → `.claude/` 트리:
   - `permissions` → `.claude/settings.json` 의 `permissions.allow/deny`
   - `model` (`ModelConfig`) → `settings.json` 의 `model`
   - `type=mcp` 컴포넌트 → `.mcp.json` 의 `mcpServers`(auth/scopes 는 자리표시 주석)
   - `type=skill` (`entrypoint`·`injection_mode`) → `.claude/skills/<id>/SKILL.md`
   - `type=context` → `CLAUDE.md` 조각(또는 memory 파일)
   - `hook_plan`(event→정렬 스텝) → `settings.json` 의 `hooks`(event 매핑 표대로)
3. **매핑 규약 문서** — `runtime/emit/MAPPING.md`. 각 harness 개념 ↔ Claude Code 개념을 표로,
   그리고 **손실 없는 / 근사 / 미지원** 필드를 명시(환각·과장 금지 — 미지원은 주석으로 표기).
4. **FileTree 방출** — CLI 는 디스크에 쓰되 `--dry-run` 은 생성될 파일 diff 만 출력.
   API 는 zip 스트림 또는 `{path: content}` JSON.
5. **`harness` CLI 신설** — `apps/cli`(uv 워크스페이스 멤버). `init`(대화형 설명→`/recommend`
   →선택→harness.yaml), `resolve`, `eject`. `uvx harness ...` 로 배포. 웹 없이 터미널 완결.
6. **골든 스냅샷 테스트** — 시드 시나리오(PR 리뷰)를 resolve→eject→파일 트리 골든 스냅샷으로
   고정. 매핑이 바뀌면 스냅샷 diff 로 드러나게.

## 완료 기준

- [x] `Emitter` 프로토콜(`emit/base.py`) + `ClaudeCodeEmitter`(model/permissions/hooks/mcp +
      합성 프롬프트→`CLAUDE.md`) + dispatch(`emit(resolved, target)`).
- [x] `MAPPING.md` — 개념 대응 표 + 손실/근사/미지원 명시.
- [ ] `harness eject` CLI (디스크 쓰기 + `--dry-run` diff). → **다음 증분**
- [ ] `POST /eject?target=` API (zip/JSON). → **다음 증분**
- [ ] `harness init`/`resolve`/`eject` CLI 관통 (uvx 실행). → **다음 증분**
- [x] PR 리뷰 시나리오 골든 스냅샷 테스트(`test_emit.py`).
- [x] **로컬 폴백·기존 테스트 회귀 불변** — 전체 pytest 73 통과 · ruff/mypy 클린.

**구현 노트 (컴파일러 코어):** `emit/`(base·claude_code·__init__) 신설. skill 은 별도 `skills/`
디렉터리가 아니라 합성 프롬프트(→`CLAUDE.md`)에 포함(IR 이 entrypoint 를 안 담음 — MAPPING.md
한계). MCP 실행 스펙·훅 셸 명령은 자리표시(카탈로그 메타에 없음). CLI/API 표면은 다음 증분.

## 의존성

`ResolvedHarness` IR(완료) · `build_request`(완료, raw-API 타깃에서 재사용). **선행 없음 →
즉시 착수 가능.**

## 확장 (후속)

`CursorEmitter`(`.cursor/rules/*.mdc` + MCP), `ClineEmitter`(custom modes), `RawApiEmitter`
(`build_request` 재사용해 실행 스크립트/컬 예시). Emitter 프로토콜만 있으면 타깃 추가는 가법적.

## 검증 한계

파일 트리 **계약**은 골든 스냅샷으로 완전 고정. 실제 Claude Code 가 생성물을 로드·구동하는지는
수동 스모크(생성 → `.claude/` 로드 확인). 자동 e2e 는 Claude Code 헤드리스 실행이 가능해질 때 후속.

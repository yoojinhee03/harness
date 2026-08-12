# eject 매핑 규약 — harness ↔ 런타임

`ResolvedHarness`(IR)를 각 런타임 네이티브 포맷으로 컴파일할 때의 개념 대응과 **손실 지점**을
명시한다. 원칙: 손실 없는 건 그대로, 근사는 근사임을 표기, 불가능은 자리표시 + 문서화(환각 금지).

## Claude Code (`ClaudeCodeEmitter`, target=`claude-code`)

| harness (IR) | Claude Code | 충실도 | 비고 |
|---|---|---|---|
| `prompt.system_text` (합성 프롬프트) | `CLAUDE.md` | **손실 없음** | context·skill(각 `body`)·authored 레이어가 합성돼 그대로 들어감. `body` 없는 컴포넌트는 자리표시 |
| `model.name` | `.claude/settings.json` `model` | **손실 없음** | 이름 그대로 |
| `model.max_tokens`·`temperature` | — | 미지원 | Claude Code 가 자체 관리(settings 필드 아님) |
| `type=mcp` 컴포넌트 (실행 스펙 있음) | `.mcp.json` `mcpServers[id]` | **손실 없음** | 카탈로그 `mcp:` 블록 → stdio(command/args/env) 또는 http/sse(type/url) 그대로 방출. 비밀값은 `${ENV}` 확장 |
| `type=mcp` 컴포넌트 (실행 스펙 없음) | `.mcp.json` `mcpServers[id]` | **자리표시** | `mcp:` 블록 미선언 시 `command: "TODO:…"` — 카탈로그에 스펙을 채워야 함 |
| MCP `config` | — | 미지원(현재) | .mcp.json 표준 형태에 안 맞아 생략, 후속 검토 |
| `permissions` (capability→scope) | `settings.json` `permissions.allow` (`mcp__<id>`) | **근사** | 도구 단위 허용으로만 표현, **scope(read-only 등) 소실** |
| `hook_plan` `before_tool_call` | `hooks.PreToolUse` | **근사** | 매처 `*`, 명령은 자리표시 |
| `hook_plan` `after_tool_call` | `hooks.PostToolUse` | **근사** | 〃 |
| `hook_plan` `before_request` | `hooks.UserPromptSubmit` | **근사** | 의미 근사 |
| `hook_plan` `after_response` | `hooks.Stop` | **근사** | 의미 근사 |
| `hook_plan` `after_request` | — | **미지원** | Claude Code 대응 이벤트 없음 → 방출 생략 |
| 훅 (`emit_command` 있음) | hook `command` | **손실 없음** | 카탈로그가 준 실제 셸 명령을 그대로 방출(예: secret-scan 은 stdin 스캔 후 exit 2 로 차단) |
| 훅 (`emit_command` 없음) | hook `command` | **자리표시** | 인프로세스 핸들러라 셸 명령 등가물이 없음 → `echo '[harness] … 교체'` (핸들러/명령 채워야 함) |
| `auth_needs` | — | 미지원(현재) | MCP 인증은 Claude Code 커넥터 설정 몫 — 후속 |

## Cursor (`CursorEmitter`, target=`cursor`)

같은 IR 을 Cursor 네이티브 포맷으로 방출 — "단일 IR → 여러 런타임" 실증.

| harness (IR) | Cursor | 충실도 | 비고 |
|---|---|---|---|
| `prompt.system_text` (합성 프롬프트) | `.cursor/rules/harness.mdc` | **손실 없음** | `.mdc` frontmatter `alwaysApply: true` 로 항상 주입(CLAUDE.md 대응) |
| `type=mcp` 컴포넌트 | `.cursor/mcp.json` `mcpServers[id]` | **손실 없음** | Claude Code `.mcp.json` 과 동일 포맷(공용 헬퍼 재사용) |
| `hook_plan` | — | **미지원** | Cursor 에 라이프사이클 훅(커맨드) 네이티브 대응 없음 → 생략 |
| `model.name` | — | **미지원** | Cursor 는 모델을 UI 에서 선택 → settings 필드 아님 |
| `permissions` | — | **미지원** | Cursor 에 도구 단위 허용 목록 대응 없음 → 생략 |

Cursor 는 훅·모델·권한의 네이티브 대응이 없어 프롬프트+MCP 만 손실 없이 방출한다(생략은
자유 생성이 아니라 명시적 소실 — 위 표로 문서화).

### 알려진 한계 (IR 태생)

- context 의 `body`(프롬프트 조각)는 IR(`ResolvedComponent.body`)로 운반돼 합성 시스템 레이어
  (→ `CLAUDE.md`)에 들어간다. skill 의 `body`는 이제 CLAUDE.md 에 합치지 않고 컴포넌트마다
  `.claude/skills/<id>/SKILL.md`(네이티브 Agent Skill — frontmatter `name`/`description` + body)로
  분리 방출한다. 모델이 필요 시 스킬을 로드하는 Claude Code 규약을 따른다.
- MCP 상위 사용 지침(`ResolvedComponent.usage_note`)은 `CLAUDE.md` 의 `## Capabilities` 절로 방출한다.
  도구별 description 은 서버가 `tools/list` 로 노출하므로 authoring 하지 않는다(그 위의 사용 전략만).
- MCP **실행 스펙**은 이제 IR(`ResolvedComponent.mcp`)로 운반돼 그대로 도는 `.mcp.json` 으로
  나간다(카탈로그 `mcp:` 블록 필요). auth 는 여전히 Claude Code 커넥터/`${ENV}` 몫이며, MCP
  `config`(예: repo_filter)는 표준 `.mcp.json` 형태에 안 맞아 아직 생략한다.
- 훅 `command` 는 아직 자리표시다. 하네스 훅은 셸 명령이 아니라 인프로세스 핸들러라, 셸 명령으로의
  방출은 태생적 근사다(후속: 훅을 실행 가능한 명령으로 승격하는 스펙).

남은 한계들은 후속 증분(IR 확장)에서 좁힌다. 현재는 **가능한 건 손실 없이, 나머지는 자리표시 +
문서화**로 정직하게 표기한다.

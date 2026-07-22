# eject 매핑 규약 — harness ↔ 런타임

`ResolvedHarness`(IR)를 각 런타임 네이티브 포맷으로 컴파일할 때의 개념 대응과 **손실 지점**을
명시한다. 원칙: 손실 없는 건 그대로, 근사는 근사임을 표기, 불가능은 자리표시 + 문서화(환각 금지).

## Claude Code (`ClaudeCodeEmitter`, target=`claude-code`)

| harness (IR) | Claude Code | 충실도 | 비고 |
|---|---|---|---|
| `prompt.system_text` (합성 프롬프트) | `CLAUDE.md` | **손실 없음** | context·skill·authored 레이어가 합성돼 그대로 들어감 |
| `model.name` | `.claude/settings.json` `model` | **손실 없음** | 이름 그대로 |
| `model.max_tokens`·`temperature` | — | 미지원 | Claude Code 가 자체 관리(settings 필드 아님) |
| `type=mcp` 컴포넌트 | `.mcp.json` `mcpServers[id]` | **근사** | 실행 스펙(command/url)이 카탈로그에 없어 자리표시 — 채워야 함 |
| MCP `config` | — | 미지원(현재) | .mcp.json 표준 형태에 안 맞아 생략, 후속 검토 |
| `permissions` (capability→scope) | `settings.json` `permissions.allow` (`mcp__<id>`) | **근사** | 도구 단위 허용으로만 표현, **scope(read-only 등) 소실** |
| `hook_plan` `before_tool_call` | `hooks.PreToolUse` | **근사** | 매처 `*`, 명령은 자리표시 |
| `hook_plan` `after_tool_call` | `hooks.PostToolUse` | **근사** | 〃 |
| `hook_plan` `before_request` | `hooks.UserPromptSubmit` | **근사** | 의미 근사 |
| `hook_plan` `after_response` | `hooks.Stop` | **근사** | 의미 근사 |
| `hook_plan` `after_request` | — | **미지원** | Claude Code 대응 이벤트 없음 → 방출 생략 |
| 훅 핸들러(샌드박스) | hook `command` | **근사** | 하네스 훅은 셸 명령이 아니라 자리표시(교체 필요) |
| `auth_needs` | — | 미지원(현재) | MCP 인증은 Claude Code 커넥터 설정 몫 — 후속 |

### 알려진 한계 (IR 태생)

- `ResolvedComponent` 는 skill 의 `entrypoint`/본문을 담지 않는다 → 개별 `skills/<id>/SKILL.md`
  네이티브 방출은 불가. 대신 skill 기여는 합성 프롬프트(→ `CLAUDE.md`)에 포함된다.
- MCP 실행 스펙·auth 는 카탈로그 메타에 없어 자리표시로 나간다. 실 배포엔 사용자가 채워야 한다.

이 한계들은 후속 증분(카탈로그에 실행 스펙 추가 / IR 확장)에서 좁힌다. 현재는 **자리표시 +
문서화**로 정직하게 표기한다.

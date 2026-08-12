# harness MCP 서버 — 에디터 안에서 recommend → resolve → eject

백엔드(FastAPI)·프론트 없이 패키지(`resolver`·`catalog`·`runtime`)를 **in-process** 로 감싸,
`recommend`/`resolve`/`eject` 로직을 **MCP 툴**로 노출한다. Claude Code·Cursor·Cline·VSCode(Copilot
agent) 등 **어떤 MCP 클라이언트에서도** 호출할 수 있고, `eject` 산출물(`.claude/` 등)이 떨어지는
바로 그 에디터 안에서 루프가 닫힌다.

> **VSCode 화 경로 A** — "네이티브 확장(.vsix)"을 만들기 전에, 이미 있는 이 MCP 서버를 에디터에
> 등록해 실제 사용 루프를 먼저 검증하는 단계. 검증 후 필요하면 그 위에 네이티브 확장(경로 B)을 얹는다.

## 노출 툴

| 툴 | 하는 일 |
|----|---------|
| `recommend_harness(description, top_k)` | 프로젝트 설명(자연어) → 카탈로그 근거 추천(요구 능력·점수·비용·충돌·auth) |
| `list_catalog(type, capability)` | 컴포넌트 카탈로그 나열/필터(skill·mcp·context·hook) |
| `resolve_harness(harness_yaml)` | `harness.yaml` 검증 — 진단(errors/gaps/warnings) + resolved 요약 |
| `eject_harness(harness_yaml, target, out_dir)` | 검증된 하네스를 런타임 네이티브 포맷으로 컴파일. `out_dir` 주면 디스크에 씀 |

카탈로그는 `CATALOG_DIR` → 옆 폴더(`../harness-catalog/components`) → 패키지 내장 순으로 자동
탐색한다. 못 찾으면 빈 레지스트리로 기동한다(recommend 는 빈 결과).

## 사전 준비 — 서버 설치

레포 루트(`harness/`)에서 워크스페이스 의존성을 한 번 설치한다. `harness-architect/.venv/bin/harness-mcp`
콘솔 스크립트가 생기고, 이 스크립트의 shebang 이 venv python 을 직접 가리키므로 **PATH·uv 에 의존하지
않는다**(GUI 로 띄운 VSCode 에서도 안전).

```bash
cd harness-architect
uv sync            # .venv 와 harness-mcp 엔트리포인트 생성
```

빠른 자체 점검(선택) — stdio 로 initialize → tools/list 핸드셰이크:

```bash
harness-architect/.venv/bin/harness-mcp    # 기동 후 Ctrl-C. 에러 없이 떠야 정상
```

## 에디터별 등록

경로/이름만 다르고 형식은 대동소이하다. 아래 커맨드는 **워크스페이스 루트 = `harness/`** 기준.

### VSCode (Copilot agent mode, 1.102+)

이 레포에는 이미 [`.vscode/mcp.json`](../../../.vscode/mcp.json) 이 커밋돼 있다. VSCode 에서 워크스페이스를
열고 Copilot Chat 을 **Agent** 모드로 두면 `harness` 서버가 자동으로 뜬다(상태는 채팅의 도구 아이콘에서
확인). 형식:

```jsonc
{
  "servers": {
    "harness": {
      "type": "stdio",
      "command": "${workspaceFolder}/harness-architect/.venv/bin/harness-mcp",
      "env": { "CATALOG_DIR": "${workspaceFolder}/harness-catalog/components" }
    }
  }
}
```

### Claude Code 확장(또는 CLI)

프로젝트 스코프 `.mcp.json`(키가 `mcpServers`) 또는 커맨드로 등록:

```bash
claude mcp add harness \
  --env CATALOG_DIR="$PWD/harness-catalog/components" \
  -- "$PWD/harness-architect/.venv/bin/harness-mcp"
```

### Cursor

`.cursor/mcp.json`(프로젝트) 또는 `~/.cursor/mcp.json`(전역):

```jsonc
{
  "mcpServers": {
    "harness": {
      "command": "${workspaceFolder}/harness-architect/.venv/bin/harness-mcp",
      "env": { "CATALOG_DIR": "${workspaceFolder}/harness-catalog/components" }
    }
  }
}
```

### Cline / Continue 등

설정 UI 의 "MCP Servers"에 stdio 서버 추가 —
command `…/harness-architect/.venv/bin/harness-mcp`, env `CATALOG_DIR=…/harness-catalog/components`.

### 이식형 대안 — venv 절대경로 대신 `uv run`

머신 간 이동이나 venv 경로를 박고 싶지 않으면 `command: "uv"`, `args: ["run", "--project",
"${workspaceFolder}/harness-architect", "harness-mcp"]`. 단 `uv` 가 에디터 프로세스의 PATH 에 있어야
한다(GUI 실행 VSCode 는 `~/.local/bin` 이 빠질 수 있어, 그럴 땐 위의 venv 콘솔 스크립트가 더 안전).

## 사용 루프 (등록 후)

에디터 채팅(agent 모드)에서 자연어로:

1. **추천** — "이 프로젝트에 맞는 하네스 추천해줘" → `recommend_harness` 가 카탈로그 근거로 후보를 낸다.
   여기서 고른 컴포넌트 `id` 를 `harness.yaml` 의 `components[].ref` 로 쓴다.
2. **검증** — `harness.yaml` 초안을 `resolve_harness` 로 검증(충돌·예산·gap 진단).
3. **방출** — `eject_harness(target="claude-code", out_dir="<이 워크스페이스>")` 로 `.claude/`·`.mcp.json`·
   `CLAUDE.md` 를 현재 프로젝트에 바로 생성. `out_dir` 을 비우면 파일 트리만 미리보기로 돌려준다.

`target` 은 `available_targets()` 중 하나(현재 `claude-code`, `cursor`).

## 트러블슈팅

- **서버가 안 뜸 / "command not found"** — `harness-architect/.venv/bin/harness-mcp` 가 있는지 확인.
  없으면 `cd harness-architect && uv sync`.
- **추천이 항상 빈 결과** — 카탈로그를 못 찾은 것. `CATALOG_DIR` 이 `harness-catalog/components` 를
  가리키는지 확인(서버 로그 `카탈로그 로드: N개` 를 stderr 에서 확인).
- **`recommend` 가 느리거나 랭킹이 약함** — 임베딩/랭킹에 `ANTHROPIC_API_KEY`·`VOYAGE_API_KEY` 를
  env 로 주면 실측 랭킹, 없으면 로컬 폴백으로 동작한다.

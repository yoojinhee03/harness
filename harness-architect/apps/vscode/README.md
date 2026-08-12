# Harness Architect — VSCode 확장

카탈로그에 **근거**해 하네스 구성요소(Skill·MCP·Context·Hook)를 추천하고, `harness.yaml` 을
**검증(resolve)** 하고 런타임 네이티브 포맷으로 **컴파일(eject)** 한다 — 전부 VSCode 안에서.

백엔드 로직은 새로 짜지 않고, 레포에 이미 있는 **harness MCP 서버**(`harness-architect/apps/mcp`)를
자식 프로세스로 띄워 stdio 로 호출한다(확장 자체의 런타임 의존성 0).

## 기능

| 커맨드 | 하는 일 |
|--------|---------|
| **Harness: 구성요소 추천** | 프로젝트를 자연어로 설명 → 카탈로그 근거 추천을 웹뷰에 카드로. "harness.yaml 스타터 생성" 버튼 |
| **Harness: 현재 harness.yaml 검증(resolve)** | 충돌·예산·gap 을 검사해 **Problems 패널**에 표시. gap 은 추천으로 되돌릴 수 있음 |
| **Harness: eject** | 검증된 하네스를 `claude-code`·`cursor` 포맷으로 컴파일. 워크스페이스에 쓰기 또는 미리보기 |
| **카탈로그 사이드바** | 액티비티바의 Harness 아이콘 → 컴포넌트를 type 별로 탐색, 클릭 시 `id@version` 복사 |

`*.harness.yaml` / `harness.yaml` 파일 상단엔 **resolve · eject 코드렌즈**가 뜬다.

## 사전 준비 — 백엔드 서버

확장은 harness MCP 서버 실행 파일을 호출한다. 레포 루트에서 한 번 설치하면 venv 콘솔 스크립트가 생긴다:

```bash
cd harness-architect
uv sync            # harness-architect/.venv/bin/harness-mcp 생성
```

기본 설정이 이 경로(`${workspaceFolder}/harness-architect/.venv/bin/harness-mcp`)를 가리키므로, 이
모노레포를 워크스페이스로 열면 추가 설정 없이 동작한다. 다른 위치면 아래 설정을 바꾼다.

## 설정

| 키 | 기본값 | 설명 |
|----|--------|------|
| `harness.serverCommand` | `${workspaceFolder}/harness-architect/.venv/bin/harness-mcp` | 서버 실행 파일. `${workspaceFolder}`·`~` 확장 |
| `harness.serverArgs` | `[]` | 실행 인자. `uv run` 방식 쓰려면 command=`uv`, args=`["run","--project","${workspaceFolder}/harness-architect","harness-mcp"]` |
| `harness.catalogDir` | `${workspaceFolder}/harness-catalog/components` | `CATALOG_DIR`. 비우면 서버가 자동 탐색 |
| `harness.defaultTarget` | `claude-code` | eject 기본 타깃 |

## 개발 / 빌드

```bash
cd harness-architect/apps/vscode
npm install
npm run compile        # dist/extension.js 번들
# F5 (Run Harness Extension) — 확장 개발 호스트로 실행

npm run vsix           # harness-architect.vsix 패키징
code --install-extension harness-architect.vsix   # 로컬 설치
```

## 아키텍처

```
VSCode 확장(TS)  ──stdio JSON-RPC(MCP)──►  harness-mcp (파이썬)
  · 커맨드/트리/웹뷰/코드렌즈                 · recommend / list_catalog
  · Problems 패널 진단                        · resolve / eject
                                             └─ packages: resolver·catalog·runtime
```

확장은 얇은 UI 셸이고 모든 도메인 로직은 파이썬 패키지에 남는다 — CLI·API·MCP 와 같은 로직을 공유한다.

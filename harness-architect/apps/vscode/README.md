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
| **카탈로그 사이드바** | 액티비티바의 Harness Architect 아이콘 → 컴포넌트를 type 별로 탐색, 클릭 시 `id@version` 복사 |
| **챗 참가자 `@harness`** | Copilot Chat 패널에서 `@harness <설명>` → 카탈로그 근거 추천을 대화로 |

`*.harness.yaml` / `harness.yaml` 파일 상단엔 **resolve · eject 코드렌즈**가 뜬다.

### 챗 참가자 `@harness`

Copilot Chat 패널(Agent/Ask)에서:

```
@harness 오전 9시마다 국내 주식 추천해주는 앱
```

→ ① `recommend_harness` 로 **카탈로그 근거** 추천(그라운딩) → ② 사용자의 Copilot 모델
(`request.model`)로 각 컴포넌트를 **유명 서비스에 빗댄 한 줄 이유**로 스트리밍(모델 없으면 서버
reason 폴백) → ③ **정확한 ref 목록**(권위 있는 그라운딩) + **"harness.yaml 스타터 생성" 버튼**.
후속 프롬프트 제안("MCP만", "알림 방식 바꾸기")으로 멀티턴 정제. Copilot(또는 다른 LM 제공자)이
설치돼 있어야 모델 표현이 동작한다.

## 백엔드 서버 — 두 가지 모드

확장은 harness MCP 서버 실행 파일을 호출한다. 서버를 찾는 **우선순위**는:

1. **사용자 지정** — `harness.serverCommand` 를 명시적으로 설정한 경우 그것.
2. **동봉된 자립 바이너리** — `.vsix` 안에 `server/bin/harness-mcp` 가 있으면 그것(+ `server/catalog`).
   **파이썬이 없어도 동작**한다. 마켓/사내 배포용.
3. **venv 기본값** — `${workspaceFolder}/harness-architect/.venv/bin/harness-mcp`. 모노레포 개발자용.

### 모노레포 개발자 (모드 3)

```bash
cd harness-architect
uv sync            # harness-architect/.venv/bin/harness-mcp 생성
```
이 모노레포를 워크스페이스로 열면 추가 설정 없이 동작한다(server/ 를 빌드하지 않았다면).

### 파이썬 없는 사용자에게 배포 (모드 2)

서버를 자립 실행파일로 구워 `.vsix` 안에 동봉한다 — 받는 쪽은 파이썬·uv·소스가 필요 없다.

```bash
cd harness-architect/apps/vscode
npm run vsix:bundled      # 서버 빌드(PyInstaller) → server/ 동봉 → .vsix 패키징
```

`server/bin/harness-mcp`(현재 OS/아키텍처용, ~24MB) + `server/catalog/`(13개 YAML)가 vsix 에 들어간다.
설치한 사용자의 확장은 이 동봉 바이너리를 자동으로(모드 2) 쓰고, `CATALOG_DIR` 은 동봉 카탈로그로 맞춰진다.

> **오프라인 휴리스틱 모드** — 동봉 서버는 `anthropic`·`voyageai` 를 포함하지 않는다(용량·키 불요).
> 임베딩·랭킹은 로컬 휴리스틱 폴백으로 동작한다. Claude/Voyage 실측 랭킹이 필요하면 모드 1·3(키 주입)으로.

> **플랫폼별 빌드** — PyInstaller 산출물은 OS/아키텍처 종속이다. 여러 플랫폼에 뿌리려면 각 OS 러너
> (mac-arm64·mac-x64·linux-x64·win-x64)에서 `npm run build:server` 후
> `vsce package --target <platform>` 로 플랫폼별 vsix 를 만든다(§ 멀티플랫폼 배포).

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
npm run compile        # dist/extension.js 번들(esbuild)
npm run check-types    # tsc 타입체크
# F5 (Run Harness Extension) — 확장 개발 호스트로 실행

npm run vsix           # 확장만 패키징(서버 미동봉 — 모드 1·3 전제)
npm run vsix:bundled   # 서버까지 구워 동봉(모드 2 — 파이썬 없는 사용자용)
code --install-extension harness-architect.vsix   # 로컬 설치
```

`npm run build:server` 만 따로 돌리면 `server/` 만 갱신한다(내부에서 PyInstaller 로 굽고 카탈로그를 복사).
전제: `cd harness-architect && uv sync` 로 venv 가 있어야 한다.

## 멀티플랫폼 배포

PyInstaller 산출물은 빌드한 OS/아키텍처에서만 돈다. 여러 플랫폼에 뿌리려면 각 OS 러너에서 빌드해
**플랫폼별 vsix** 를 만든다(VSCode Marketplace 는 `--target` 별 vsix 를 지원):

```bash
# 각 러너(darwin-arm64 / darwin-x64 / linux-x64 / win32-x64)에서:
npm ci
npm run build:server
npx vsce package --no-dependencies --target darwin-arm64 -o harness-darwin-arm64.vsix
```

CI(GitHub Actions) 매트릭스로 4개 러너에서 위를 돌리고, `vsce publish --target <t>` 로 각각 올리면
사용자는 자기 플랫폼에 맞는 vsix 를 자동으로 받는다. 소스 배포(모드 3)만 쓸 거면 이 절은 건너뛴다.

## 아키텍처

```
VSCode 확장(TS)  ──stdio JSON-RPC(MCP)──►  harness-mcp (파이썬)
  · 커맨드/트리/웹뷰/코드렌즈                 · recommend / list_catalog
  · Problems 패널 진단                        · resolve / eject
  · 서버 자동 선택(사용자>동봉>venv)          └─ packages: resolver·catalog·runtime

배포 모드: (1) 사용자 지정 경로  (2) vsix 동봉 자립 바이너리(파이썬 불요)  (3) venv(개발)
```

확장은 얇은 UI 셸이고 모든 도메인 로직은 파이썬 패키지에 남는다 — CLI·API·MCP 와 같은 로직을 공유한다.
자립 바이너리는 그 파이썬 로직을 인터프리터째 얼려 담은 것이라 로직 중복이 없다.

# harness-catalog

AI 하네스 아키텍트의 **카탈로그 데이터 자산 레포**. 코드가 아니라 데이터다 — 추천 대상인
구성요소(Skill·MCP·Context·Hook)를 [설계: 카탈로그 스키마] 대로 기술한 YAML 모음.
백엔드(`harness-architect`)가 이 레포를 소비한다. RAG 엔진 *코드*는 백엔드
(`packages/catalog`)에 잔류하고, 컴포넌트 *데이터*(자산)만 여기로 분리된다.

```
harness-catalog/
├─ components/                    # 10개 컴포넌트 (4타입, 여러 facet)
│  ├─ github-mcp.yaml            # mcp     — vcs.code-hosting / issue-tracking / code-review
│  ├─ web-search-mcp.yaml        # mcp     — web.search / web.fetch
│  ├─ slack-mcp.yaml             # mcp     — comms.messaging
│  ├─ notion-mcp.yaml            # mcp     — knowledge.wiki
│  ├─ pr-review-skill.yaml       # skill   — review.code (requires vcs.*)
│  ├─ issue-triage-skill.yaml    # skill   — transform.classify (requires vcs.issue-tracking)
│  ├─ doc-draft-skill.yaml       # skill   — author.document (requires knowledge.wiki)
│  ├─ coding-convention-ctx.yaml # context — convention.coding
│  ├─ secret-scan-hook.yaml      # hook    — lifecycle.guardrail (before_tool_call)
│  └─ pii-redact-hook.yaml       # hook    — lifecycle.transform (after_response)
├─ schema/
│  └─ component.schema.json      # 컴포넌트 스키마 (검증용)
├─ README.md                     # 이 파일 — 소비 방식
└─ CONTRIBUTING.md               # 기여 규약 (이중 필드·통제 어휘·훅 리뷰 게이트)
```

## 소비 방식 (백엔드에서)

지금은 `harness-architect` 와 **같은 레포 안에 나란히** 있는 데이터 폴더다(별도 git 레포·
submodule 아님). 백엔드 카탈로그 로더는 `CATALOG_DIR` 환경변수 → 없으면 옆 폴더
`../harness-catalog/components` 순으로 찾는다.

```bash
# 기본: 옆 폴더를 자동으로 읽으므로 설정 불필요.
# 다른 위치에 두면:
export CATALOG_DIR=/path/to/harness-catalog/components
```

> 설계상 나중에 이 폴더만 별도 자산 레포로 떼어내 submodule 로 마운트할 수 있게 경계는
> 유지한다(RAG 엔진 *코드* 는 백엔드 `packages/catalog` 에 잔류, 데이터만 이동).

## 시나리오 (cross-type 연결 검증)

capability 통제 어휘로 skill → mcp cross-type 연결이 실제 동작하는지 확인하는 3개 경로.
리졸브 트레이스와 gap 데모는 백엔드 `packages/resolver/tests`·`packages/catalog/tests` 가
검증한다.

- **PR 리뷰 봇** — `pr-review-skill`(review.code, requires vcs.*) + `github-mcp` +
  `coding-convention-ctx` + `secret-scan-hook`. `github-mcp` 를 빼면 `vcs.code-hosting`·
  `vcs.code-review` 가 gap 으로 떠 추천기로 되돌아간다.
- **이슈 분류** — `issue-triage-skill`(requires vcs.issue-tracking) + `github-mcp`.
- **문서 초안** — `doc-draft-skill`(requires knowledge.wiki) + `notion-mcp`.

| id | type | provides | requires | 비고 |
|----|------|----------|----------|------|
| `github-mcp` | mcp | vcs.code-hosting/issue-tracking/code-review | — | exclusive_group `vcs`, oauth |
| `web-search-mcp` | mcp | web.search, web.fetch | — | api_key |
| `slack-mcp` | mcp | comms.messaging | — | oauth |
| `notion-mcp` | mcp | knowledge.wiki | — | oauth |
| `pr-review-skill` | skill | review.code | vcs.code-hosting, vcs.code-review | 접근은 MCP 위임 |
| `issue-triage-skill` | skill | transform.classify | vcs.issue-tracking | 접근은 MCP 위임 |
| `doc-draft-skill` | skill | author.document | knowledge.wiki | 접근은 MCP 위임 |
| `coding-convention-ctx` | context | convention.coding | — | 매 요청 1200토큰 |
| `secret-scan-hook` | hook | lifecycle.guardrail | — | before_tool_call, fail_closed |
| `pii-redact-hook` | hook | lifecycle.transform | — | after_response, can_modify_response |

## 스키마

공통 베이스 + 타입 델타. 필드는 **검색/랭킹용(RAG, 퍼지)** 과 **계약용(리졸버/빌더, 엄격)**
으로 나뉜다. 자세한 규약과 통제 어휘는 [CONTRIBUTING.md](./CONTRIBUTING.md), 검증
스키마는 [schema/component.schema.json](./schema/component.schema.json) 참고.

# 도메인 통제 어휘 (척추)

능력은 `domain.capability` 2단계다(CONTRIBUTING §2). **domain 은 척추** — 추가·개명은 리뷰 필수다.
capability 레벨은 도메인 아래에서 자유롭게 추가한다(도메인 폭증 방지). capability 레벨을 미리 다
채우지 않는다 — 실제 컴포넌트가 생길 때 늘어난다.

이 목록은 요구사항 추출기가 참고하는 코드 상수 `harness_catalog.vocabulary.DOMAIN_VOCAB` 와
일치해야 한다(요구사항 추출을 도메인 무관하게 넓히는 근거). **아직 컴포넌트가 없는 도메인도 등재**한다
— 그래야 그 도메인 요구가 카탈로그보다 넓게 잡혀 gap 으로 표면화되고, 시딩 큐로 흘러간다.

| domain      | 설명                                    | 기본 facet → 채우는 타입 |
| ----------- | --------------------------------------- | ------------------------ |
| `vcs`       | 버전관리·코드호스팅·이슈·CI/CD           | access → mcp             |
| `comms`     | 메시징·이메일 등 커뮤니케이션 채널       | access → mcp             |
| `knowledge` | 위키·파일스토리지 등 지식 저장소 접근    | access → mcp             |
| `data`      | 관계형·스프레드시트·벡터 데이터 저장소   | access → mcp             |
| `web`       | 웹 검색·페치·브라우저                    | access → mcp             |
| `pm`        | 작업·프로젝트 관리 도구                  | access → mcp             |
| `author`    | 문서·슬라이드·표 저작                    | task → skill             |
| `review`    | 리뷰(코드 등)                           | task → skill             |
| `analyze`   | 분석(데이터 등)                         | task → skill             |
| `transform` | 추출·분류·변환 절차                     | task → skill             |
| `media`     | 이미지·오디오·비디오 등 미디어 처리      | access → mcp             |
| `dataproc`  | ETL·파이프라인 등 데이터 처리 †          | task → skill             |
| `convention`| 코딩·프로세스 컨벤션(배경지식)          | knowledge → context      |
| `domain`    | 프로젝트별 도메인 지식                   | knowledge → context      |
| `lifecycle` | 요청 전후 라이프사이클 동작(훅)          | lifecycle → hook         |
| `prompt`    | 시스템 프롬프트 조각                     | prompt → context         |

`media` 는 라이브 카탈로그(공식 MCP 레지스트리)에 실존 서버가 다수 등장해 capability 레벨
어휘(`media.video/audio/image/edit`)를 등재했다 — 큐레이션 시드엔 아직 없지만 하베스트+enrichment 로
태깅돼 검색·재사용된다. † `dataproc` 는 아직 capability 도 컴포넌트도 없다 — 요구로 잡히되 gap 으로
나온다. 실사용 gap 집계(아래)가 수요를 보여주면 실존 도구를 시딩/등재한다.

## 카탈로그 성장 절차 (추측 아닌 수요 데이터로)

1. recommender 는 요구 능력을 카탈로그가 못 채울 때마다 `GAP_SIGNAL {json}` 로그를 남긴다.
2. 집계: `python harness-architect/packages/catalog/scripts/aggregate_gaps.py <로그…>`
   → "자주 요청되나 없는 능력"이 빈도순으로 나온다(콜드스타트 큐).
3. 상위 항목부터 **실존 도구**를 찾아 `TEMPLATE.yaml` 로 컴포넌트를 작성한다(실재 검증 필수).
4. 새 능력이 기존 도메인에 안 들어가면 이 표에 도메인을 추가(리뷰) 후 `DOMAIN_VOCAB` 도 갱신한다.

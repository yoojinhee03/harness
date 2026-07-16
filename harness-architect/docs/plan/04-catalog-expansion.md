# Phase 4 — 카탈로그 확장 (도메인 확대 + 둘째 시나리오)

> 설계: 카탈로그 시드 셋 문서 "다음" 항목(web-search·slack·notion 등), 카탈로그 스키마 §6
> 통제 어휘. 시드 4개(PR 봇 경로)에서 도메인을 넓혀 RAG·화면 E 를 풍부하게 하고, 둘째
> end-to-end 시나리오가 관통하는지 확인한다.

## 목표

capability 통제 어휘의 다른 facet 을 채우는 컴포넌트를 추가하고, "리서치/이슈 분류" 같은
둘째 시나리오가 A→B→C→생성까지 도는지 검증한다.

## 작업

1. **컴포넌트 추가** (각 스키마 준수, 이중 필드 채움):
   - `web-search-mcp` (mcp, web.search·web.fetch)
   - `slack-mcp` (mcp, comms.messaging) — 알림/리포트 경로
   - `notion-mcp` (mcp, knowledge.wiki) — 문서 저장 경로
   - `issue-triage-skill` (skill, review.code 아님 → transform.extract + pm.task-tracking requires)
   - `doc-draft-skill` (skill, author.document, requires knowledge.wiki)
   - `pii-redact-hook` (hook, lifecycle.transform, can_modify_request)
2. **cross-type 연결 확인** — 새 skill 의 requires 를 새 mcp 가 provides 로 충족하는지.
3. **둘째 시나리오 테스트** — "이슈 분류/문서 초안" 설명 → 추천에 신규 컴포넌트 등장 →
   선택 → resolve 성공/gap 트레이스.
4. **스키마 검증** — `python -m harness_catalog.loader --validate` 전부 통과.

## 완료 기준

- [x] 신규 컴포넌트 6종 추가(web/comms/knowledge/task/lifecycle facet 확대) → 총 10개, 스키마 검증 통과.
- [x] 둘째 시나리오(이슈 분류·문서 초안) recommender/resolver 테스트 추가·통과.
- [x] 기존 PR 봇 경로 회귀 없음(count 하드코딩 테스트 갱신).
- [x] 전체 pytest 통과(47).

**추가 컴포넌트:** web-search-mcp · slack-mcp · notion-mcp · issue-triage-skill ·
doc-draft-skill · pii-redact-hook. cross-type 링크: issue-triage→github(vcs.issue-tracking),
doc-draft→notion(knowledge.wiki) 검증.

## 검증

`--validate` + pytest(신규 시나리오 포함) + `/recommend` 라이브로 신규 컴포넌트 추천 확인.

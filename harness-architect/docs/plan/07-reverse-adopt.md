# Phase 7 — 역방향 임포트 (`adopt`) + gap 분석

> 설계: 기획(그라운딩 추천) + Phase 5 매핑 규약의 역방향. 신규 유저가 빈 화면에서 시작하지
> 않도록, **이미 있는 에이전트 설정을 harness.yaml 로 역추출**하고 부족분을 제안한다.

## 왜 (차별화)

기존 플러그인은 "처음부터 새로 조립"을 요구한다. 여기선 이미 쓰던 `.claude/`·`.cursorrules`·
`mcp.json` 을 흡수해 즉시 검증·개선 대상으로 만든다 → 진입장벽이 사실상 0. Phase 5(내보내기)
와 대칭을 이뤄 **왕복(round-trip)** 이 성립한다.

## 목표

`기존 프로젝트 디렉터리 → HarnessConfig(초안) → resolver 진단 + 빠진 능력 추천`.
- CLI: `harness adopt <dir> [--from claude-code]`
- API: `POST /adopt`

## 작업

1. **Importer 프로토콜** — `runtime/emit/base.py` 의 역. `Importer.parse(tree: FileTree) ->
   HarnessConfig`. Phase 5 매핑 표를 양방향으로 공유(단일 진실).
2. **ClaudeCodeImporter** — `.claude/settings.json`(permissions·model·hooks)·`.mcp.json`·
   `skills/`·`CLAUDE.md` 를 파싱해 컴포넌트로 매칭. **카탈로그에 있으면 `id` 링크, 없으면
   `unknown`/외부 컴포넌트로 안전 표기(환각 금지 — 지어내지 않는다).**
3. **gap 분석** — 역추출 구성을 `resolve()` 에 태워 gap/충돌 진단 + `Recommender` 로 "빠진
   능력" 제안(예: `review.code` 있는데 `secret-scan-hook` 없음 → 보강 추천).
4. **CLI/API** — `harness adopt` 는 결과를 harness.yaml 초안 + 진단 리포트로 출력.

## 완료 기준

- [ ] `Importer` 프로토콜 + `ClaudeCodeImporter`(+ 미지 컴포넌트 안전 표기).
- [ ] gap/추천 연계(`resolve` + `Recommender` 재사용) + 진단 리포트.
- [ ] `harness adopt` CLI + `POST /adopt` API.
- [ ] **왕복 테스트**: 시드 `.claude/` 픽스처 → adopt → resolve → eject 가 동치(± 근사 필드).
- [ ] **로컬 폴백·기존 테스트 회귀 불변**.

## 의존성

**Phase 5** (포맷 매핑 표를 역방향으로 재사용) · `resolve`/`Recommender`(완료). → 05 이후.

## 검증 한계

카탈로그에 없는 외부 컴포넌트는 `unknown` 으로만 표기 가능(그라운딩 원칙상 지어내지 않음).
매핑이 손실 근사인 필드(Phase 5 `MAPPING.md`)는 왕복에서 완전 동치가 아닐 수 있어, 테스트는
"의미 동치(±근사 필드)"로 판정한다.

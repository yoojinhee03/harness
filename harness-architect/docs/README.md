# 설계 문서 (Notion "하네스 프로젝트" 미러·링크)

코드는 아래 설계 문서를 근거로 구현됐다. 코드 ↔ 문서 대응은 루트 README 표 참고.

| 문서 | 링크 | 코드 대응 |
|------|------|-----------|
| 기획: AI 하네스 아키텍트 | https://app.notion.com/p/39636745494f81288fecdbe4dc491794 | 전체 |
| 결정: 하네스 스코프 | https://app.notion.com/p/39d36745494f81c0ae35f36d69589898 | `model`·`permissions` 최상위 필드 |
| 설계: 카탈로그 스키마 | https://app.notion.com/p/39636745494f81539a3bd9093d2e3ffe | `harness_resolver.models.Component`, 시드 YAML |
| 설계: 리졸버 검증 로직 | https://app.notion.com/p/39636745494f817999c9d99f8dfbed9c | `harness_resolver.resolver` (8단계) |
| 설계: harness.yaml 스펙 | https://app.notion.com/p/39d36745494f8133a34cf7538ae58c8d | `HarnessConfig`, `/generate` |
| 설계: 훅 실행 모델 | https://app.notion.com/p/39d36745494f817081d0efef9b8149f4 | `resolver._order_hooks`, `harness_runtime.hooks` |
| 설계: 피드백 루프 | https://app.notion.com/p/39d36745494f8152a8b3ebe53651d68b | `usage_count`·`retention_score` 랭킹 가중 |
| 설계: 화면 기획 | https://app.notion.com/p/39636745494f8148960bdf10510bba36 | `apps/web` 화면 A~F, API 엔드포인트 |
| 개발: 기술 스택 | https://app.notion.com/p/39d36745494f8132869afccffe41d7b0 | 스택 전반 |
| 카탈로그 시드 셋 | https://app.notion.com/p/39d36745494f8156a5afe62f2b3fb353 | `harness-catalog/components/*.yaml` |

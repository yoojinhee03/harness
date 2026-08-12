# Changelog

## 0.1.0

- 최초 릴리스. 카탈로그 사이드바, 구성요소 추천(웹뷰), resolve(→Problems 패널),
  eject(claude-code·cursor) 커맨드. 백엔드는 harness MCP 서버를 자식 프로세스로 재사용.
- 서버 번들링(PyInstaller) — `vsix:bundled` 로 자립 바이너리를 vsix 에 동봉해 파이썬 없는
  사용자에게도 배포 가능. 서버 자동 선택 우선순위: 사용자 지정 > 동봉 바이너리 > venv.
  (개발 모드 F5 에서는 동봉을 건너뛰고 venv 를 우선 — 파이썬 변경이 바로 반영되도록.)
- 챗 참가자 `@harness` — Copilot Chat 패널에서 프로젝트를 설명하면 카탈로그 근거로 추천.
  그라운딩은 MCP 서버(recommend), 벤치마크 이유 표현은 사용자의 Copilot 모델(request.model),
  정확한 ref 목록 + "harness.yaml 스타터 생성" 버튼 + 후속 프롬프트 제안.
- '내 하네스(동기화)' 뷰 — 웹과 같은 백엔드(`harness.apiUrl`)에 harness.yaml 을 저장/열기하고
  SSE 로 웹·다른 에디터의 변경을 실시간 수신(양방향 동기화). editor/title 저장 버튼.
- 멀티테넌시 — Bearer 토큰 로그인/가입(`harness.apiToken`), 사용자별 격리, 팀 생성·멤버 초대,
  저장 시 스코프(개인/팀) 선택. 팀 하네스는 팀원끼리 실시간 공유("팀 메모리 공유").

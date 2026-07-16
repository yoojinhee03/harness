# Phase 1 — RAG 실연동 (Voyage 임베딩 + Claude 추출·랭킹)

> 설계: 개발 기술 스택 §2, 기획 §3.1. 스왑 가능한 인터페이스는 이미 존재
> (`embeddings.get_embedder`, `llm.claude_available`). 이 Phase 는 그 경로를 **견고화 +
> 주입 가능화 + 테스트**한다. 로컬 폴백은 그대로 유지한다.

## 목표

키가 있으면 품질 모드(Voyage 임베딩 · Claude 요구사항 추출 · Claude 랭킹 근거),
없으면 로컬 폴백 — 둘 다 같은 인터페이스로 관통한다.

## 작업

1. **설정 일원화** — `settings.py` 로 모델명·차원·모드 플래그를 환경변수에서 읽어 한 곳에서 관리
   (`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `HARNESS_EMBEDDER`, `HARNESS_RANKER`).
2. **주입 가능화** — `Recommender(registry, embedder=?, reasoner=?)` 로 임베더·랭커를 주입 가능하게.
   기본은 환경 기반 자동 선택. 테스트가 fake 를 주입해 경로를 강제한다.
3. **Claude 추출·랭킹 경로 정리** — `llm` 헬퍼를 `Reasoner` 프로토콜로 감싸 recommender 가
   구현체에 비의존. `NullReasoner`(휴리스틱) / `ClaudeReasoner`(품질).
4. **테스트** — fake 임베더/reasoner 주입으로 (a) 품질 모드가 실제로 주입 경로를 타는지,
   (b) 키 없을 때 로컬 폴백이 동일 결과를 내는지 회귀 고정.

## 완료 기준

- [x] `Recommender` 가 embedder·reasoner 주입을 받는다.
- [x] fake 주입 테스트로 claude/voyage 모드 코드 경로 검증(네트워크 없이). → `test_rag_injection.py`
- [x] 로컬 폴백 회귀 테스트 통과(기존 결과 불변).
- [x] `settings.py` 로 모드 플래그 일원화, `.env.example` 반영.
- [x] 전체 pytest 통과(29) · ruff/mypy 클린.

**구현 노트:** `settings.py`(모드/모델 일원화) · `reasoning.py`(Reasoner 프로토콜 —
NullReasoner/ClaudeReasoner) 신설. `Recommender(registry, embedder=?, reasoner=?)` 주입 가능.
`get_embedder`/`get_reasoner` 가 Settings 로 auto 선택. Claude 실호출은 키 주입 시 자동 활성.

## 검증 한계

실제 Voyage/Claude 네트워크 호출은 키가 있어야 확인 가능. 이 Phase 는 **주입·폴백·경로**를
보장하고, 실호출은 키 주입 시 자동 활성으로 남긴다.

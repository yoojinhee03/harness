"""Capability 통제 어휘 — 설계: 카탈로그 스키마 §6.

`domain.capability` 2단계 어휘. `provides`/`requires`/`capability_tags` 가 공유한다.
각 capability 에 facet 과 요구사항 추출용 키워드(한/영)를 붙여둔다 — LLM 키가 없을 때의
휴리스틱 추출에 쓰인다(품질 모드에선 Claude 가 대체).
"""

from __future__ import annotations

Facet = str  # access | task | knowledge | lifecycle

# capability → (facet, [추출 키워드])
CAPABILITY_VOCAB: dict[str, tuple[Facet, list[str]]] = {
    # facet: access — 외부 시스템·데이터 접근 (주로 MCP)
    "vcs.code-hosting": ("access", ["repo", "저장소", "github", "gitlab", "git", "커밋", "commit"]),
    "vcs.issue-tracking": ("access", ["issue", "이슈", "티켓", "버그 트래킹"]),
    "vcs.code-review": ("access", ["pr", "pull request", "코드 리뷰", "code review", "리뷰 코멘트"]),
    "vcs.ci-cd": ("access", ["ci", "cd", "파이프라인", "빌드", "pipeline", "배포"]),
    "comms.messaging": ("access", ["슬랙", "slack", "메시지", "채팅", "알림", "notify"]),
    "comms.email": ("access", ["이메일", "email", "메일"]),
    "knowledge.wiki": ("access", ["노션", "notion", "위키", "wiki", "문서 저장소"]),
    "knowledge.file-storage": ("access", ["드라이브", "drive", "박스", "box", "파일 스토리지"]),
    "data.relational": ("access", ["sql", "postgres", "mysql", "db", "데이터베이스", "관계형"]),
    "data.spreadsheet": ("access", ["스프레드시트", "spreadsheet", "엑셀", "excel", "시트"]),
    "data.vector": ("access", ["벡터 검색", "vector", "embedding", "rag"]),
    "web.search": ("access", ["웹 검색", "web search", "검색 엔진", "구글"]),
    "web.fetch": ("access", ["url", "웹 페이지", "fetch", "가져오기", "크롤"]),
    "web.browse": ("access", ["브라우저", "browser", "브라우저 자동화", "browse"]),
    "pm.task-tracking": ("access", ["지라", "jira", "아사나", "asana", "작업 트래킹", "태스크"]),
    # facet: task — 절차·워크플로 (주로 Skill)
    "author.document": ("task", ["문서 작성", "docx", "리포트", "보고서", "document", "요약", "회의록", "초안"]),
    "author.slides": ("task", ["슬라이드", "발표", "ppt", "slides", "프레젠테이션"]),
    "author.spreadsheet": ("task", ["표 작성", "스프레드시트 생성"]),
    "review.code": ("task", ["코드 리뷰", "리뷰", "review", "pr 리뷰", "코멘트"]),
    "analyze.data": ("task", ["데이터 분석", "analyze", "분석", "통계"]),
    "transform.extract": ("task", ["추출", "파싱", "extract", "parse"]),
    "transform.classify": (
        "task",
        ["분류", "라벨", "라벨링", "label", "triage", "트리아지", "classify", "우선순위", "카테고리"],
    ),
    # facet: knowledge — 배경 지식 (주로 Context)
    "convention.coding": ("knowledge", ["코딩 컨벤션", "스타일 가이드", "convention", "style guide", "컨벤션"]),
    "convention.process": ("knowledge", ["프로세스 규칙", "팀 규칙", "process"]),
    "domain.knowledge": ("knowledge", ["도메인 지식", "domain"]),
    # facet: lifecycle — 요청 전후 동작 (주로 Hook)
    "lifecycle.logging": ("lifecycle", ["로깅", "logging", "로그", "audit"]),
    "lifecycle.validation": ("lifecycle", ["입출력 검증", "validation", "검증"]),
    "lifecycle.guardrail": (
        "lifecycle",
        ["가드레일", "guardrail", "보안", "security", "차단", "스캔", "secret", "시크릿", "비밀", "자격증명"],
    ),
    "lifecycle.approval": ("lifecycle", ["승인", "approval", "게이트"]),
    "lifecycle.transform": ("lifecycle", ["요청 변형", "응답 변형", "transform"]),
    # facet: prompt — 시스템 프롬프트 조각 (Context facet, prompt.system[].ref 로 주입)
    "prompt.role": ("prompt", ["페르소나", "persona", "역할 프롬프트", "톤", "리뷰어 역할"]),
    "prompt.format": ("prompt", ["출력 형식", "output format", "응답 형식", "포맷 지침", "구조화 출력"]),
    "prompt.safety": ("prompt", ["안전 지침", "safety preamble", "세이프티", "안전 프리앰블"]),
}


def facet_of(capability: str) -> Facet | None:
    entry = CAPABILITY_VOCAB.get(capability)
    return entry[0] if entry else None


def extract_capabilities_heuristic(description: str) -> list[str]:
    """LLM 없이 키워드 매칭으로 요구 능력을 추출한다(로컬 폴백)."""
    text = description.lower()
    hits: list[tuple[str, int]] = []
    for cap, (_facet, keywords) in CAPABILITY_VOCAB.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score:
            hits.append((cap, score))
    hits.sort(key=lambda x: (-x[1], x[0]))
    return [cap for cap, _ in hits]

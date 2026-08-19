"""Capability 통제 어휘 — 설계: 카탈로그 스키마 §6.

`domain.capability` 2단계 어휘. `provides`/`requires`/`capability_tags` 가 공유한다.
각 capability 에 facet 과 요구사항 추출용 키워드(한/영)를 붙여둔다 — LLM 키가 없을 때의
휴리스틱 추출에 쓰인다(품질 모드에선 Claude 가 대체).

어휘는 두 층위다:
- **domain (척추)** — `DOMAIN_VOCAB`. 추가·개명은 리뷰 필수(CONTRIBUTING §2). 요구사항 추출이
  카탈로그보다 넓게 gap 을 낼 수 있도록, 컴포넌트가 아직 없는 도메인도 여기 등재한다.
- **capability (도메인 아래 능력)** — `CAPABILITY_VOCAB`. 자유롭게 추가(도메인 폭증 방지).
  capability 레벨을 미리 다 채우지 않는다 — 실제 컴포넌트가 생길 때 늘어난다(작업 3).
"""

from __future__ import annotations

import re
from functools import lru_cache

Facet = str  # access | task | knowledge | lifecycle | prompt

# capability 형태 검증(스키마 §defs.capability 와 동일 규칙). 요구사항 추출은 이 형태만 통과시킨다.
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")


def is_valid_capability(cap: str) -> bool:
    """`domain.capability` 2단계 통제-어휘 형태인가(멤버십 아님, 형태만)."""
    return bool(CAPABILITY_RE.match(cap))


def capability_domain(cap: str) -> str:
    """`domain.capability` 에서 domain 조각. 형태가 아니면 빈 문자열."""
    return cap.split(".", 1)[0] if is_valid_capability(cap) else ""


# ── 도메인 척추 (controlled vocabulary, domain 레벨) ──
# 기존 컴포넌트/capability 에서 귀납 + 명백히 빠진 도메인(미디어·데이터 처리)을 추가.
# 값은 facet 기본값(그 도메인 아래 새 capability 가 gap 으로 뜰 때 "어떤 타입이 채우나"의 근거).
DOMAIN_VOCAB: dict[str, str] = {
    "vcs": "버전관리·코드호스팅·이슈·CI/CD",
    "comms": "메시징·이메일 등 커뮤니케이션 채널",
    "knowledge": "위키·파일스토리지 등 지식 저장소 접근",
    "data": "관계형·스프레드시트·벡터 등 데이터 저장소 접근",
    "web": "웹 검색·페치·브라우저",
    "pm": "작업·프로젝트 관리 도구",
    "author": "문서·슬라이드·표 저작",
    "review": "리뷰(코드 등)",
    "analyze": "분석(데이터 등)",
    "transform": "추출·분류·변환 절차",
    "media": "이미지·오디오·비디오 등 미디어 처리",  # 신규(컴포넌트 없음 — gap 으로 표면화)
    "dataproc": "ETL·파이프라인 등 데이터 처리",  # 신규(컴포넌트 없음)
    "convention": "코딩·프로세스 컨벤션(배경지식)",
    "domain": "프로젝트별 도메인 지식",
    "lifecycle": "요청 전후 라이프사이클 동작(훅)",
    "prompt": "시스템 프롬프트 조각",
}

# facet → 이 능력을 채울 수 있는 컴포넌트 타입 (CONTRIBUTING §2 의 facet 분류를 타입으로).
FACET_TO_TYPE: dict[Facet, str] = {
    "access": "mcp",
    "task": "skill",
    "knowledge": "context",
    "lifecycle": "hook",
    "prompt": "context",
}

# 통제어휘 버전 — 어휘를 바꾸면 올린다. gap provenance·caps 분류 재현성 태그로 쓰인다(TASK 2·3).
VOCAB_VERSION = "1"

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
    # facet: access — 미디어 처리 서비스 (media 도메인 — 라이브 카탈로그에 실존 MCP 81+개 등장 → 어휘 등재)
    "media.video": ("access", ["video", "영상", "비디오", "동영상", "유튜브", "youtube", "shorts", "쇼츠"]),
    "media.audio": ("access", ["audio", "오디오", "음악", "music", "bgm", "음성", "voice", "speech", "tts", "사운드"]),
    "media.image": ("access", ["image", "이미지", "사진", "photo", "썸네일", "thumbnail"]),
    "media.edit": (
        "access",
        ["편집", "edit", "editing", "컷", "cut", "transcode", "트랜스코딩", "transition", "전환",
         "자막", "subtitle", "ffmpeg", "encode", "인코딩", "render", "rendering", "렌더링"],
    ),
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


@lru_cache(maxsize=4096)
def _kw_pattern(kw: str) -> re.Pattern[str]:
    """키워드용 라틴 단어경계 매처. 양옆이 라틴 영숫자면 매칭 안 함.

    'ci' 가 'de**ci**sion' 안에서, 'pr' 이 '**pr**oduct' 안에서 잡히던 오탐(수확 태그 오염의 주범)을 막는다.
    한글·기호·공백은 라틴 영숫자가 아니라 경계로 취급되므로 'PR을'·'비밀키' 같은 한국어 매칭은 그대로 된다.
    """
    return re.compile(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])")


def _kw_hit(kw: str, text: str) -> bool:
    return _kw_pattern(kw).search(text) is not None


def extract_capabilities_heuristic(description: str) -> list[str]:
    """LLM 없이 키워드 매칭으로 요구 능력을 추출한다(로컬 폴백).

    라틴 단어경계 매칭이라 'ci'/'pr'/'db' 같은 짧은 영문 키워드가 큰 단어 속에서 오탐하지 않는다
    (수확된 MCP 태깅의 오염을 원천에서 줄인다 — 틀린 태그보다 빈 태그가 낫다). 통제 어휘 기반이라
    vocab 밖 신규 도메인은 못 뽑는다(그건 품질 모드 LLM 의 몫). vocab ⊋ 카탈로그이므로 카탈로그에
    없는 vocab 능력(예: comms.email)은 여기서도 추출돼 recommender 에서 gap 으로 표면화된다.
    """
    text = description.lower()
    hits: list[tuple[str, int]] = []
    for cap, (_facet, keywords) in CAPABILITY_VOCAB.items():
        score = sum(1 for kw in keywords if _kw_hit(kw, text))
        if score:
            hits.append((cap, score))
    hits.sort(key=lambda x: (-x[1], x[0]))
    return [cap for cap, _ in hits]


# domain → 기본 facet. vocab 에서 도메인별 다수결로 귀납하고, 컴포넌트 없는 신규 도메인은 명시.
def _derive_domain_facets() -> dict[str, Facet]:
    from collections import Counter

    tally: dict[str, Counter[str]] = {}
    for cap, (facet, _kw) in CAPABILITY_VOCAB.items():
        tally.setdefault(capability_domain(cap), Counter()).update([facet])
    derived = {domain: counts.most_common(1)[0][0] for domain, counts in tally.items()}
    # capability 가 아직 없는 도메인의 기본 facet(“무엇이 이걸 채우나”). media 는 이제 vocab 에서 access 로 귀납됨.
    derived.setdefault("dataproc", "task")
    return derived


DOMAIN_DEFAULT_FACET: dict[str, Facet] = _derive_domain_facets()


def facet_for_capability(cap: str) -> Facet | None:
    """능력의 facet. vocab 에 있으면 그 값, 없으면 도메인 기본값(신규 능력도 타입 추정 가능)."""
    known = CAPABILITY_VOCAB.get(cap)
    if known is not None:
        return known[0]
    return DOMAIN_DEFAULT_FACET.get(capability_domain(cap))


def suggested_component_type(cap: str) -> str:
    """이 능력을 채울 수 있는 컴포넌트 타입(gap 신호의 '무엇으로 채우나'). 미상이면 skill."""
    facet = facet_for_capability(cap)
    return FACET_TO_TYPE.get(facet or "", "skill")

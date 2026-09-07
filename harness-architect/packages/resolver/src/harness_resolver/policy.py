"""정책 as code — 조직 가드레일 (진행 플랜 Phase 8).

개인이 하네스를 자유 조립하는 도구에서, **조직이 규칙을 선언하면 리졸버가 강제**하는 팀 표준화
도구로 격상한다. 정책은 harness.yaml 과 분리된 조직 자산이다(하네스 작성자가 못 고친다).

**gap 과 의미가 다르다** — gap 은 "재조정하면 풀리는 것"이라 추천기로 되돌리는 신호이고,
정책 위반은 **차단**이다. 그래서 `policy_violation` 코드를 따로 쓰되 severity 는 기존 `error`
를 그대로 쓴다(새 severity 를 만들면 프론트·CLI 의 기존 분기가 전부 깨진다).

**순수하다** — 정책은 데이터로 들어와 진단으로 나간다. 리졸버의 순수함수 계약을 지킨다
(I/O·네트워크·전역 상태 없음). 파일 로딩은 호출부(CLI·API)의 몫이다.

**정적 검증까지만 책임진다** — "PII 훅이 실제로 마스킹하는가"는 런타임(Phase 2) 영역이다.
여기서 강제하는 것은 *선언*이다: 그 훅이 붙어 있는가, 예산 안에 있는가, scope 가 축소됐는가.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PolicyRequire(BaseModel):
    """반드시 있어야 하는 것."""

    model_config = ConfigDict(extra="forbid")

    capabilities: list[str] = Field(default_factory=list)  # 선택 집합이 제공해야 할 능력
    components: list[str] = Field(default_factory=list)  # 반드시 포함할 컴포넌트 id


class PolicyForbid(BaseModel):
    """있으면 안 되는 것."""

    model_config = ConfigDict(extra="forbid")

    # 정확한 id 또는 접두 glob("io.github.randomdev/*") — 연합 레지스트리 네임스페이스 차단용.
    components: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    # 격리 없이 도는 훅 차단. 훅은 라이프사이클 시점에 임의 로직을 실행하므로 공급망 위험이 크다
    # (공유 카탈로그 승격 게이트와 같은 근거).
    unsandboxed_hooks: bool = False


class PolicyBudget(BaseModel):
    """상한. None 이면 그 축은 제약 없음(harness 의 budget 은 warning, 정책 초과는 차단)."""

    model_config = ConfigDict(extra="forbid")

    context_tokens: int | None = None
    added_tools: int | None = None


class PolicyAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 허용 scope 화이트리스트. None = 제약 없음. 예: ["read-only"] → 쓰기 권한 부여 금지.
    allowed_scopes: list[str] | None = None
    # 인증이 필요한 컴포넌트는 permissions 로 축소값이 반드시 선언돼야 한다(광범위 권한 방지).
    require_narrowed: bool = False


class Policy(BaseModel):
    """조직 정책. `.harness/policy.yaml` 의 거버넌스 섹션에서 온다.

    같은 파일의 `severity:` 키는 verify(정적 검증)의 심각도 오버라이드로 **이미 쓰이고 있다**.
    별도 파일을 만들지 않고 한 파일에 섹션을 나눠 담는다 — 기존 로더는 `severity` 만 읽으므로
    하위호환이 유지된다.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    name: str = ""
    require: PolicyRequire = Field(default_factory=PolicyRequire)
    forbid: PolicyForbid = Field(default_factory=PolicyForbid)
    budget: PolicyBudget = Field(default_factory=PolicyBudget)
    auth: PolicyAuth = Field(default_factory=PolicyAuth)

    @property
    def is_empty(self) -> bool:
        """아무 규칙도 없는 정책 — 붙여도 동작이 변하지 않는다."""
        return self == Policy(version=self.version, name=self.name)


def matches(pattern: str, component_id: str) -> bool:
    """정확 일치 또는 접두 glob(`ns/*`). 정규식은 쓰지 않는다 — 정책은 읽고 감사할 수 있어야 한다."""
    if pattern.endswith("*"):
        return component_id.startswith(pattern[:-1])
    return component_id == pattern


def policy_from_document(doc: object) -> Policy | None:
    """`.harness/policy.yaml` 문서 → Policy. 거버넌스 키가 하나도 없으면 None(정책 미지정).

    `severity`(verify 용)만 있는 기존 파일은 None 을 돌려준다 — 정책을 안 쓰던 레포의 동작이
    이 기능 도입만으로 바뀌면 안 된다.
    """
    if not isinstance(doc, dict):
        return None
    keys = {"require", "forbid", "budget", "auth"}
    if not (keys & doc.keys()):
        return None
    payload = {k: v for k, v in doc.items() if k in keys or k in {"version", "name"}}
    return Policy.model_validate(payload)

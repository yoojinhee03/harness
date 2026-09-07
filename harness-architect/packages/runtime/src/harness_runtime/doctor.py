"""드리프트 진단 — 저장된 하네스가 카탈로그 갱신에 뒤처졌는가 (진행 플랜 Phase 9-2). CLI·API 공용.

하네스는 한 번 저장되면 그대로 굳지만 카탈로그는 계속 움직인다(버전 올라가고, deprecated 되고,
사라진다). 그 간극을 **저장 시점이 아니라 지금** 알려준다 — 안 그러면 eject 하거나 실행할 때에야
터진다.

**순수하다.** 설정과 레지스트리를 읽어 진단을 낸다. 파일·DB·네트워크를 모른다.

**고치지 않는다.** 제안만 낸다(`suggested_ref`). 조직 자산인 harness.yaml 을 도구가 말없이 고쳐
쓰면 안 된다 — 적용은 사람이 `--fix` 로 명시하거나 UI 에서 눌러야 한다.
"""

from __future__ import annotations

from harness_resolver import Component, HarnessConfig, Registry
from pydantic import BaseModel, Field

# 진단 종류. ok 를 제외하면 전부 "사람이 볼 값어치가 있는 간극"이다.
Issue = str  # ok | missing | deprecated | upgrade_available | unpinned


def _semver_key(version: str) -> tuple[int, ...]:
    """registry._semver_key 와 같은 규칙(비교 불가하면 최하위). 정렬 기준을 갈라놓지 않으려 맞춘다."""
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError:
        return (0,)


class ComponentDiagnosis(BaseModel):
    component_id: str
    issue: Issue
    pinned_version: str | None = None  # ref 에 박힌 버전. None = 미지정(최신 추종)
    current_version: str | None = None  # 그 핀으로 지금 잡히는 것
    latest_version: str | None = None  # 카탈로그의 최신 stable
    status: str = ""  # 잡힌 컴포넌트의 status
    detail: str = ""
    suggested_ref: str | None = None  # 제안(적용은 호출부·사람의 몫)

    @property
    def actionable(self) -> bool:
        return self.issue != "ok"


class DoctorReport(BaseModel):
    harness_id: str = ""
    findings: list[ComponentDiagnosis] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """손볼 게 없으면 True. `missing`·`deprecated` 만 심각하고 나머지는 권고다."""
        return not any(f.actionable for f in self.findings)

    @property
    def blocking(self) -> list[ComponentDiagnosis]:
        """지금 당장 깨지거나 곧 깨질 것 — 사라진 버전과 deprecated."""
        return [f for f in self.findings if f.issue in ("missing", "deprecated")]

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.issue] = counts.get(f.issue, 0) + 1
        return counts


def _latest_stable(registry: Registry, component_id: str) -> Component | None:
    """id 의 최신 stable(없으면 최신). Registry 프로토콜엔 버전 열거가 없어 all() 을 훑는다."""
    versions = [c for c in registry.all() if c.id == component_id]
    if not versions:
        return None
    stable = [c for c in versions if c.status == "stable"]
    return max(stable or versions, key=lambda c: _semver_key(c.version))


def _diagnose(
    cid: str,
    pinned: str | None,
    current: Component,
    latest: Component | None,
    issue: Issue,
    detail: str,
    suggested_ref: str | None = None,
) -> ComponentDiagnosis:
    """진단 한 건 조립 — 공통 필드(핀/현재/최신/status)를 한 곳에서 채운다."""
    return ComponentDiagnosis(
        component_id=cid,
        issue=issue,
        pinned_version=pinned,
        current_version=current.version,
        latest_version=latest.version if latest else None,
        status=current.status,
        detail=detail,
        suggested_ref=suggested_ref,
    )


def doctor(config: HarnessConfig, registry: Registry) -> DoctorReport:
    """저장된 하네스 ↔ 현재 카탈로그의 간극을 진단한다."""
    report = DoctorReport(harness_id=config.metadata.id)

    for sel in config.components:
        cid = sel.id
        pinned = sel.ref.split("@", 1)[1] if "@" in sel.ref else None
        current = registry.get(cid, pinned)
        latest = _latest_stable(registry, cid)

        if current is None:
            # 핀이 가리키던 버전이 사라졌거나 id 자체가 없어졌다. 후자면 latest 도 None 이다.
            if latest is None:
                report.findings.append(
                    ComponentDiagnosis(
                        component_id=cid,
                        issue="missing",
                        pinned_version=pinned,
                        detail="카탈로그에 이 컴포넌트가 없습니다(제거되었거나 id 가 바뀜)",
                    )
                )
            else:
                report.findings.append(
                    ComponentDiagnosis(
                        component_id=cid,
                        issue="missing",
                        pinned_version=pinned,
                        latest_version=latest.version,
                        status=latest.status,
                        detail=f"고정한 버전 {pinned} 이 카탈로그에 없습니다",
                        suggested_ref=f"{cid}@{latest.version}",
                    )
                )
            continue

        if current.status == "deprecated":
            # 대체를 제안한다 — 같은 능력을 주는 다른 컴포넌트가 있으면 그쪽으로.
            replacement = _replacement_for(registry, current)
            report.findings.append(
                _diagnose(
                    cid, pinned, current, latest,
                    "deprecated",
                    f"'{cid}@{current.version}' 는 deprecated 입니다"
                    + (f" — '{replacement}' 로 대체를 검토하세요" if replacement else ""),
                    replacement,
                )
            )
            continue

        if pinned is None:
            # 버전을 안 박으면 카탈로그가 움직일 때마다 조용히 다른 걸 쓴다. 그게 드리프트 그 자체다.
            report.findings.append(
                _diagnose(
                    cid, pinned, current, latest,
                    "unpinned",
                    f"버전이 고정돼 있지 않아 카탈로그 변경을 그대로 따라갑니다(현재 {current.version})",
                    f"{cid}@{current.version}",
                )
            )
            continue

        if latest is not None and _semver_key(latest.version) > _semver_key(current.version):
            report.findings.append(
                _diagnose(
                    cid, pinned, current, latest,
                    "upgrade_available",
                    f"상위 버전 {latest.version} 이 있습니다(현재 {current.version})",
                    f"{cid}@{latest.version}",
                )
            )
            continue

        report.findings.append(_diagnose(cid, pinned, current, latest, "ok", ""))

    if not config.components:
        report.notes.append("컴포넌트가 없어 진단할 것이 없습니다.")
    return report


def _replacement_for(registry: Registry, deprecated: Component) -> str | None:
    """deprecated 컴포넌트를 대신할 후보 — 같은 타입으로 같은 능력을 주는 stable 중 최신.

    자기 자신의 상위 버전이 있으면 그게 1순위다(가장 안전한 교체). 없으면 능력이 겹치는 다른
    컴포넌트를 제안하되, **제안일 뿐** 자동 적용하지 않는다(능력이 같아도 설정 계약은 다르다).
    """
    same_id_newer = [
        c
        for c in registry.all()
        if c.id == deprecated.id
        and c.status == "stable"
        and _semver_key(c.version) > _semver_key(deprecated.version)
    ]
    if same_id_newer:
        best = max(same_id_newer, key=lambda c: _semver_key(c.version))
        return f"{best.id}@{best.version}"

    wanted = set(deprecated.provides)
    if not wanted:
        return None
    candidates = [
        c
        for c in registry.all()
        if c.id != deprecated.id
        and c.type == deprecated.type
        and c.status == "stable"
        and wanted & set(c.provides)
    ]
    if not candidates:
        return None
    # 능력 겹침이 큰 순, 그다음 최신 버전.
    best = max(candidates, key=lambda c: (len(wanted & set(c.provides)), _semver_key(c.version)))
    return f"{best.id}@{best.version}"


def apply_suggestions(config: HarnessConfig, report: DoctorReport) -> HarnessConfig:
    """제안된 ref 로 교체한 **새 설정**을 만든다(원본 불변). `--fix` 가 쓴다.

    `deprecated` 의 타 컴포넌트 대체는 적용하지 않는다 — 능력이 겹쳐도 config 계약이 달라
    말없이 바꾸면 조용히 깨진다. 같은 id 의 상위 버전만 자동 교체 대상이다.
    """
    by_id = {f.component_id: f for f in report.findings}
    new_components = []
    for sel in config.components:
        f = by_id.get(sel.id)
        safe = f is not None and f.suggested_ref is not None and f.suggested_ref.split("@", 1)[0] == sel.id
        if safe and f is not None and f.suggested_ref is not None:
            new_components.append(sel.model_copy(update={"ref": f.suggested_ref}))
        else:
            new_components.append(sel)
    return config.model_copy(update={"components": new_components})

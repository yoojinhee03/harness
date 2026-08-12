import type { ComponentType, Recommendation } from "../api/client";
import type { Selection } from "../App";
import { Badge, Button, Card, Chip, TYPE_COLOR, TYPE_LABEL } from "../lib/ui";

const BUDGET = 8000;
const TYPE_ORDER: ComponentType[] = ["mcp", "skill", "context", "hook"];

export default function ScreenB({
  requirements,
  recommendations,
  groups,
  selection,
  setSelection,
  onBack,
  onValidate,
}: {
  requirements: string[];
  recommendations: Recommendation[];
  groups: Record<string, string[]>;
  selection: Selection;
  setSelection: (s: Selection) => void;
  onBack: () => void;
  onValidate: () => void;
}) {
  const selected = Object.values(selection);
  const usedTokens = selected.reduce((n, r) => n + r.context_tokens, 0);
  const usedTools = selected.reduce((n, r) => n + r.added_tools, 0);
  const overBudget = usedTokens > BUDGET;

  function toggle(rec: Recommendation) {
    const next = { ...selection };
    if (next[rec.id]) delete next[rec.id];
    else next[rec.id] = rec;
    setSelection(next);
  }

  function conflictHint(rec: Recommendation): string | null {
    for (const other of selected) {
      if (other.id === rec.id) continue;
      if (rec.conflicts_with.includes(other.id) || other.conflicts_with.includes(rec.id))
        return `${other.name} 와 충돌`;
      if (rec.exclusive_group && rec.exclusive_group === other.exclusive_group)
        return `배타 그룹 '${rec.exclusive_group}' 중복`;
    }
    return null;
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_300px]">
      <div>
        <div className="mb-4">
          <h2 className="text-[15px] font-semibold text-fg">추천 구성요소</h2>
          <p className="mt-0.5 text-sm text-muted">추출된 요구 능력에 근거한 추천입니다. 필요한 것을 고르세요.</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {requirements.map((cap) => (
              <Badge key={cap} className="bg-accent/15 text-accent">
                {cap}
              </Badge>
            ))}
            {requirements.length === 0 && <span className="text-xs text-muted">추출된 요구 능력 없음</span>}
          </div>
        </div>

        {TYPE_ORDER.filter((t) => (groups[t]?.length ?? 0) > 0).map((type) => (
          <section key={type} className="mb-6">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-muted">
              <Chip className={TYPE_COLOR[type]}>{TYPE_LABEL[type]}</Chip>
            </h3>
            <div className="grid gap-3 sm:grid-cols-2">
              {recommendations
                .filter((r) => r.type === type)
                .map((rec) => {
                  const isSel = !!selection[rec.id];
                  const conflict = conflictHint(rec);
                  return (
                    <button
                      key={rec.id}
                      onClick={() => toggle(rec)}
                      className={`rounded-xl border p-4 text-left transition-colors ${
                        isSel
                          ? "border-accent bg-accent/5 ring-1 ring-accent/40"
                          : "border-line bg-surface hover:border-muted/40"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="font-medium text-fg">{rec.name}</div>
                        <div className="flex items-center gap-1">
                          {rec.auth_required && <Badge className="bg-warn/15 text-warn">인증</Badge>}
                          {conflict && <Badge className="bg-err/15 text-err">{conflict}</Badge>}
                        </div>
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-muted">{rec.reason}</p>
                      <div className="mt-3 flex flex-wrap gap-1">
                        {rec.matched_capabilities.map((c) => (
                          <Badge key={c} className="bg-ok/15 text-ok">
                            {c}
                          </Badge>
                        ))}
                        {rec.requires.map((c) => (
                          <Badge key={c}>requires {c}</Badge>
                        ))}
                      </div>
                      <div className="mt-2 text-xs text-muted/70">
                        컨텍스트 {rec.context_tokens}토큰 · 도구 +{rec.added_tools} · score {rec.score}
                      </div>
                    </button>
                  );
                })}
            </div>
          </section>
        ))}
      </div>

      {/* 우측 선택 요약 패널 */}
      <aside className="lg:sticky lg:top-2 lg:self-start">
        <Card>
          <h3 className="text-sm font-semibold text-fg">선택 요약</h3>
          <div className="mt-3 space-y-1.5">
            {selected.length === 0 && <p className="text-xs text-muted">아직 선택된 구성요소가 없습니다.</p>}
            {selected.map((r) => (
              <div key={r.id} className="flex items-center justify-between text-xs">
                <span className="text-fg/90">{r.name}</span>
                <button className="text-muted hover:text-err" onClick={() => toggle(r)}>
                  ✕
                </button>
              </div>
            ))}
          </div>

          <div className="mt-4">
            <div className="mb-1 flex justify-between text-xs text-muted">
              <span>컨텍스트 예산</span>
              <span className={overBudget ? "text-err" : ""}>
                {usedTokens} / {BUDGET}
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
              <div
                className={`h-full ${overBudget ? "bg-err" : "bg-ok"}`}
                style={{ width: `${Math.min(100, (usedTokens / BUDGET) * 100)}%` }}
              />
            </div>
            <div className="mt-1 text-xs text-muted/70">추가 도구 {usedTools}개</div>
            {overBudget && <p className="mt-2 text-xs text-warn">예산 초과 — 검증에서 경고로 표시됩니다.</p>}
          </div>

          <div className="mt-5 flex flex-col gap-2">
            <Button onClick={onValidate} disabled={selected.length === 0}>
              검증하기 →
            </Button>
            <Button variant="ghost" onClick={onBack}>
              ← 설명 수정
            </Button>
          </div>
        </Card>
      </aside>
    </div>
  );
}

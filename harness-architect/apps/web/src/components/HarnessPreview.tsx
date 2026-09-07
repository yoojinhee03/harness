import { useQuery } from "@tanstack/react-query";
import { api, type BudgetView, type PreviewReport } from "../api/client";
import { Badge, codeBlock, SeverityDot, Spinner } from "../lib/ui";

/**
 * 실행 전 프리뷰 (Phase 6) — "실행하면 무슨 일이 벌어지는지"를 호출 없이 편다.
 *
 * 기존 플러그인은 돌려봐야 안다. 여기선 정규화 IR 조립 결과를 분해해 보여주므로 예산 초과·
 * 미충족 권한·훅 순서를 확정 전에 잡는다. 경고는 백엔드가 리졸버 진단을 그대로 실어 주고,
 * 이 컴포넌트는 그리기만 한다(판정 로직 없음).
 */
export function HarnessPreview({ id, scope, target }: { id: string; scope: string; target?: string }) {
  const q = useQuery({
    queryKey: ["harness-preview", id, scope, target ?? ""],
    queryFn: () => api.previewHarness(id, scope, target),
  });

  if (q.isLoading) return <div className="mt-2 flex justify-center py-4"><Spinner /></div>;
  if (q.isError) return <p className="mt-2 text-xs text-warn">프리뷰를 불러오지 못했습니다.</p>;

  const r = q.data as PreviewReport;
  if (!r.ok && r.components.length === 0) {
    return (
      <div className="mt-2">
        <p className="text-xs text-warn">resolve 실패 — 분해할 실행 명세가 없습니다.</p>
        <DiagList report={r} />
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <BudgetBar label="컨텍스트 토큰" budget={r.context_budget} />
        <BudgetBar label="추가 도구" budget={r.tool_budget} />
      </div>

      <Section title={`컴포넌트 ${r.components.length}개 — 무엇이 예산을 쓰는가`}>
        <ul className="space-y-1">
          {r.components.map((c) => (
            <li key={c.id} className="flex items-center gap-2 text-xs">
              <span className="w-40 shrink-0 truncate font-mono text-fg">{c.id}</span>
              {/* 점유율 막대 — "무엇을 빼야 예산이 도는가"가 이 뷰의 용도다. */}
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                <span className="block h-full rounded-full bg-accent" style={{ width: `${c.share * 100}%` }} />
              </span>
              <span className="w-24 shrink-0 text-right text-muted">
                {c.context_tokens}토큰{c.added_tools > 0 && ` ·+${c.added_tools}`}
              </span>
              {c.status === "deprecated" && <Badge className="bg-warn/15 text-warn">deprecated</Badge>}
            </li>
          ))}
        </ul>
      </Section>

      {r.prompt_sections.length > 0 && (
        <Section title={`시스템 프롬프트 ${r.prompt_chars}자 — 조각 ${r.prompt_sections.length}개`}>
          <ol className="space-y-1.5">
            {r.prompt_sections.map((s) => (
              <li key={`${s.layer}-${s.source}`}>
                <div className="flex items-baseline gap-2 text-xs">
                  <span className="text-muted">{s.layer}.</span>
                  <span className="font-mono text-fg">{s.source}</span>
                  <span className="text-muted">{s.tokens}토큰</span>
                </div>
                <pre className={`${codeBlock} mt-0.5 max-h-20 overflow-hidden text-[11px]`}>{s.excerpt}</pre>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {r.mcp_servers.length > 0 && (
        <Section title="MCP 서버">
          <ul className="space-y-1">
            {r.mcp_servers.map((m) => (
              <li key={m.id} className="flex items-center gap-2 text-xs">
                <span className="font-mono text-fg">{m.id}</span>
                <Badge className="bg-surface-2 text-muted">{m.transport}</Badge>
                {/* 이게 이 표의 핵심 정보다 — 원격만 API 요청에 실리고 stdio 는 eject 몫이다. */}
                <Badge className={m.sent_to_api ? "bg-ok/15 text-ok" : "bg-surface-2 text-muted"}>
                  {m.sent_to_api ? "API 전송" : "eject(로컬)"}
                </Badge>
                {m.endpoint && <span className="truncate text-muted">{m.endpoint}</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {Object.keys(r.hooks).length > 0 && (
        <Section title="훅 파이프라인">
          {Object.entries(r.hooks).map(([event, steps]) => (
            <div key={event} className="mb-1.5">
              <div className="text-[11px] uppercase tracking-wide text-muted">{event}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-1">
                {steps.map((s, i) => (
                  <span key={s.id} className="flex items-center gap-1">
                    {i > 0 && <span className="text-muted">→</span>}
                    <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-xs text-fg">
                      {s.id}
                      {s.blocking && <span className="ml-1 text-warn">blocking</span>}
                      {s.sandbox && <span className="ml-1 text-muted">{s.sandbox}</span>}
                      {s.timeout_ms != null && <span className="ml-1 text-muted">{s.timeout_ms}ms</span>}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </Section>
      )}

      {r.auth.length > 0 && (
        <Section title="인증 요구">
          <ul className="space-y-1">
            {r.auth.map((a) => (
              <li key={a.component_id} className="flex items-center gap-2 text-xs">
                <span className="font-mono text-fg">{a.component_id}</span>
                <Badge className={a.satisfied ? "bg-ok/15 text-ok" : "bg-warn/15 text-warn"}>
                  {a.satisfied ? `축소: ${a.granted_scope}` : "권한 미선언"}
                </Badge>
                {a.scopes.length > 0 && <span className="text-muted">요구 {a.scopes.join(", ")}</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <DiagList report={r} />

      {r.notes.length > 0 && (
        <ul className="space-y-0.5 border-t border-line pt-2">
          {r.notes.map((n) => (
            <li key={n} className="text-[11px] text-muted">
              ※ {n}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BudgetBar({ label, budget }: { label: string; budget: BudgetView | null }) {
  if (!budget) return null;
  const over = budget.used > budget.limit;
  const pct = budget.limit > 0 ? Math.min(100, (budget.used / budget.limit) * 100) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span className={over ? "text-err" : "text-fg"}>
          {budget.used} / {budget.limit}
          {budget.estimated && <span className="ml-1 text-muted">(추정)</span>}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div className={`h-full rounded-full ${over ? "bg-err" : "bg-ok"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-fg">{title}</div>
      {children}
    </div>
  );
}

function DiagList({ report }: { report: PreviewReport }) {
  if (report.diagnostics.length === 0) return null;
  return (
    <ul className="space-y-1">
      {report.diagnostics.map((d, i) => (
        <li key={`${d.code}-${i}`} className="flex items-center gap-2 text-xs">
          <SeverityDot severity={d.severity} />
          <span className={d.severity === "error" ? "text-err" : "text-warn"}>{d.message}</span>
        </li>
      ))}
    </ul>
  );
}

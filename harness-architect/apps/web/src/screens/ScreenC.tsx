import { useQuery } from "@tanstack/react-query";
import { api, type HarnessInput } from "../api/client";
import { Button, Card, SeverityDot, Spinner } from "../lib/ui";

export default function ScreenC({
  harness,
  onBackToRecommend,
  onConfirm,
}: {
  harness: HarnessInput;
  onBackToRecommend: () => void;
  onConfirm: () => void;
}) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["resolve", harness],
    queryFn: () => api.resolve(harness),
  });

  if (isPending)
    return (
      <Card className="mx-auto max-w-3xl flex items-center gap-2 text-sm text-muted">
        <Spinner /> 검증 중…
      </Card>
    );
  if (isError || !data) return <Card className="mx-auto max-w-3xl">검증 실패 — 백엔드(:8000) 확인.</Card>;

  const items = data.diagnostics.items;
  const errors = items.filter((d) => d.severity === "error");
  const warnings = items.filter((d) => d.severity === "warning");
  const gaps = items.filter((d) => d.severity === "gap");
  const authNeeds = data.resolved?.auth_needs ?? [];

  const banner = errors.length
    ? { tone: "err" as const, text: `오류 ${errors.length}건 — 생성 전 해결 필요` }
    : gaps.length
      ? { tone: "warn" as const, text: `gap ${gaps.length}건 — 재조정하면 풀립니다` }
      : warnings.length
        ? { tone: "warn" as const, text: `경고 ${warnings.length}건 — 진행 가능` }
        : { tone: "ok" as const, text: "모든 검사 통과 — 생성 준비 완료" };
  const bannerBg =
    banner.tone === "err" ? "bg-err/10 text-err" : banner.tone === "ok" ? "bg-ok/10 text-ok" : "bg-warn/10 text-warn";

  return (
    <div className="mx-auto max-w-3xl">
      <div className={`mb-5 rounded-xl border border-line px-4 py-3 text-sm font-medium ${bannerBg}`}>{banner.text}</div>

      <div className="space-y-3">
        <CheckSection title="참조 해소 · 충돌" ok={errors.length === 0}>
          {errors.length === 0 ? (
            <Passed text="모든 참조가 카탈로그에 존재하고 충돌 없음" />
          ) : (
            errors.map((d, i) => <DiagRow key={i} severity="error" message={d.message} />)
          )}
        </CheckSection>

        <CheckSection title="의존성 · 능력 충족" ok={gaps.length === 0}>
          {gaps.length === 0 ? (
            <Passed text="모든 requires 가 선택 집합 안에서 충족됨" />
          ) : (
            gaps.map((d, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg bg-warn/10 px-3 py-2">
                <div className="flex items-center gap-2 text-sm text-warn">
                  <SeverityDot severity="gap" />
                  <span>
                    <b>{d.component_id}</b> 가 요구하는 <b>{d.capability}</b> 미충족
                  </span>
                </div>
                <button
                  onClick={onBackToRecommend}
                  className="rounded-md border border-warn/40 px-2.5 py-1 text-xs font-medium text-warn hover:bg-warn/10"
                >
                  구성요소 추천 →
                </button>
              </div>
            ))
          )}
        </CheckSection>

        <CheckSection title="비용 예산" ok={warnings.filter((w) => w.code.includes("budget")).length === 0}>
          {warnings.filter((w) => w.code.includes("budget")).length === 0 ? (
            <Passed text="컨텍스트·도구 예산 내" />
          ) : (
            warnings
              .filter((w) => w.code.includes("budget"))
              .map((d, i) => <DiagRow key={i} severity="warning" message={d.message} />)
          )}
        </CheckSection>

        <CheckSection title="인증 · 권한" ok={true}>
          {authNeeds.length === 0 ? (
            <Passed text="인증이 필요한 구성요소 없음" />
          ) : (
            authNeeds.map((a) => (
              <div key={a.component_id} className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-2 text-sm">
                <span className="text-fg/90">
                  <b>{a.component_id}</b> — {a.type ?? "auth"} {a.scopes.join(", ")}
                  {a.granted_scope && <span className="text-ok"> · {a.granted_scope} 로 축소</span>}
                </span>
                <span className="text-xs text-muted">직접 연결 필요</span>
              </div>
            ))
          )}
        </CheckSection>
      </div>

      <div className="mt-6 flex justify-between">
        <Button variant="ghost" onClick={onBackToRecommend}>
          ← 재조정
        </Button>
        <Button onClick={onConfirm} disabled={errors.length > 0}>
          확정 → harness.yaml 생성
        </Button>
      </div>
    </div>
  );
}

function CheckSection({ title, ok, children }: { title: string; ok: boolean; children: React.ReactNode }) {
  return (
    <Card>
      <div className="mb-2 flex items-center gap-2">
        <SeverityDot severity={ok ? "ok" : "warning"} />
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
      </div>
      <div className="space-y-1.5">{children}</div>
    </Card>
  );
}

function Passed({ text }: { text: string }) {
  return <p className="text-sm text-muted">{text}</p>;
}

function DiagRow({ severity, message }: { severity: "error" | "warning"; message: string }) {
  const tone = severity === "error" ? "text-err" : "text-warn";
  return (
    <div className={`flex items-center gap-2 text-sm ${tone}`}>
      <SeverityDot severity={severity} />
      <span>{message}</span>
    </div>
  );
}

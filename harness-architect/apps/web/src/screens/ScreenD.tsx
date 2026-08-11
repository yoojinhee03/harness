import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type HarnessInput } from "../api/client";
import { Button, Card } from "../lib/ui";

export default function ScreenD({
  harness,
  onRevalidate,
  onSaved,
}: {
  harness: HarnessInput;
  onRevalidate: () => void;
  onSaved: (yaml: string) => void;
}) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["generate", harness],
    queryFn: () => api.generate(harness),
  });
  const [copied, setCopied] = useState(false);

  // 생성 성공 시 대시보드(F)에 저장. yaml 이 바뀔 때만(생성당 1회).
  useEffect(() => {
    if (data?.ok) onSaved(data.yaml);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.yaml]);

  if (isPending) return <Card>생성 중…</Card>;
  if (isError || !data) return <Card>생성 실패 — 백엔드(:8000) 확인.</Card>;

  async function copy() {
    await navigator.clipboard.writeText(data!.yaml);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">harness.yaml</h2>
          <p className="text-sm text-slate-500">
            실행 가능한 선언적 산출물 — 리졸버·런타임의 입력. gap {data.gaps} · 경고 {data.warnings} · 오류 {data.errors}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onRevalidate}>
            ← 다시 검증
          </Button>
          <Button onClick={copy}>{copied ? "복사됨 ✓" : "복사"}</Button>
        </div>
      </div>
      <pre className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900 p-4 text-xs leading-relaxed text-slate-100">
        <code>{data.yaml}</code>
      </pre>

      <EjectPanel harness={harness} />
    </div>
  );
}

// eject — 검증된 IR 을 런타임 네이티브 파일 트리로 컴파일해 브라우저에서 바로 확인한다.
function EjectPanel({ harness }: { harness: HarnessInput }) {
  const targetsQ = useQuery({ queryKey: ["eject-targets"], queryFn: api.ejectTargets });
  const targets = targetsQ.data ?? ["claude-code"];
  const [target, setTarget] = useState("claude-code");
  const ejectM = useMutation({ mutationFn: () => api.eject(harness, target) });
  const files = ejectM.data?.ok ? ejectM.data.files : null;

  return (
    <Card className="mt-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold text-slate-900">eject — 런타임 네이티브 설정 방출</h3>
          <p className="text-sm text-slate-500">검증된 IR 을 그대로 도는 파일 트리로 컴파일한다.</p>
        </div>
        <div className="flex items-center gap-2">
          {targets.map((t) => (
            <button
              key={t}
              onClick={() => setTarget(t)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                t === target ? "bg-slate-900 text-white" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-100"
              }`}
            >
              {t}
            </button>
          ))}
          <Button onClick={() => ejectM.mutate()} disabled={ejectM.isPending}>
            {ejectM.isPending ? "방출 중…" : "Eject"}
          </Button>
        </div>
      </div>

      {ejectM.isError && <p className="text-sm text-err">방출 실패 — 백엔드(:8000) 확인.</p>}
      {ejectM.data && !ejectM.data.ok && (
        <p className="text-sm text-warn">resolve 실패(gap·오류) — 검증 화면에서 먼저 해소하세요.</p>
      )}

      {files && (
        <div className="space-y-3">
          {Object.entries(files).map(([path, content]) => (
            <div key={path}>
              <div className="mb-1 font-mono text-xs text-slate-500">{path}</div>
              <pre className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">
                <code>{content}</code>
              </pre>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

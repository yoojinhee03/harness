import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
    </div>
  );
}

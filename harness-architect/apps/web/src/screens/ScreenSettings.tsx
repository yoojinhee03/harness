import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type ProviderStatus } from "../api/client";
import { Badge, Button, Card, Input, PageHeader } from "../lib/ui";

export default function ScreenSettings() {
  const statusQ = useQuery({ queryKey: ["keys"], queryFn: api.getKeys });
  const [verify, setVerify] = useState<Record<string, string> | null>(null);
  const verifyM = useMutation({ mutationFn: api.verifyKeys, onSuccess: setVerify });
  const status = statusQ.data;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="API 키"
        subtitle="키는 백엔드 메모리에만 저장됩니다(디스크 저장 안 함). 화면엔 마스킹된 값만 표시됩니다."
      />

      {status && (
        <Card className="mb-4">
          <div className="flex items-center gap-2 text-sm text-fg/90">
            현재 품질 모드 — 임베더 <Badge className="bg-sky-500/15 text-sky-400">{status.quality_mode.embedder}</Badge> · 랭커{" "}
            <Badge className="bg-violet-500/15 text-violet-400">{status.quality_mode.ranker}</Badge>
          </div>
          <p className="mt-1 text-xs text-muted">키를 저장하면 로컬 폴백 → 품질 모드로 전환됩니다.</p>
        </Card>
      )}

      <div className="space-y-3">
        <ProviderRow provider="anthropic" label="Anthropic (Claude 랭킹 · /run · /eval)" status={status?.anthropic} verify={verify?.anthropic} />
        <ProviderRow provider="voyage" label="Voyage (임베딩 품질 모드)" status={status?.voyage} verify={verify?.voyage} />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <Button variant="subtle" onClick={() => verifyM.mutate()} disabled={verifyM.isPending}>
          {verifyM.isPending ? "확인 중…" : "연동 확인"}
        </Button>
        <span className="text-xs text-muted">설정된 키로 최소 호출을 시도해 실제 연동 여부를 검사합니다.</span>
      </div>
    </div>
  );
}

function ProviderRow({
  provider,
  label,
  status,
  verify,
}: {
  provider: "anthropic" | "voyage";
  label: string;
  status?: ProviderStatus;
  verify?: string;
}) {
  const qc = useQueryClient();
  const [value, setValue] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["keys"] });
  const saveM = useMutation({
    mutationFn: () => api.putKeys(provider === "anthropic" ? { anthropic_api_key: value } : { voyage_api_key: value }),
    onSuccess: () => {
      setValue("");
      refresh();
    },
  });
  const delM = useMutation({ mutationFn: () => api.deleteKey(provider), onSuccess: refresh });

  return (
    <Card>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-fg">{label}</span>
        <span className="flex items-center gap-2 text-sm">
          {status?.set ? <Badge className="bg-ok/15 text-ok">{status.masked}</Badge> : <span className="text-muted">미설정</span>}
          {verify && (
            <Badge className={verify === "ok" ? "bg-ok/15 text-ok" : "bg-err/15 text-err"}>
              {verify === "ok" ? "연동 ✓" : verify === "unset" ? "—" : verify}
            </Badge>
          )}
        </span>
      </div>
      <div className="flex gap-2">
        <Input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={status?.set ? "새 키로 교체…" : "키 입력…"}
        />
        <Button onClick={() => saveM.mutate()} disabled={!value || saveM.isPending}>
          {saveM.isPending ? "저장…" : "저장"}
        </Button>
        {status?.set && (
          <Button variant="ghost" onClick={() => delM.mutate()} disabled={delM.isPending}>
            삭제
          </Button>
        )}
      </div>
    </Card>
  );
}

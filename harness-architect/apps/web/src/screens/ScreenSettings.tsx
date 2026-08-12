import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ProviderStatus } from "../api/client";
import { Button, Card, Chip } from "../lib/ui";

// 설정 — 런타임 API 키 관리(입력·저장·수정·삭제·연동 확인). 키는 백엔드 메모리에만 저장.
export default function ScreenSettings() {
  const statusQ = useQuery({ queryKey: ["keys"], queryFn: api.getKeys });
  const [verify, setVerify] = useState<Record<string, string> | null>(null);
  const verifyM = useMutation({ mutationFn: api.verifyKeys, onSuccess: setVerify });
  const status = statusQ.data;

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900">설정 — API 키</h2>
        <p className="text-sm text-slate-500">
          키는 <strong>백엔드 메모리에만</strong> 저장됩니다(디스크 저장 안 함). 화면엔 마스킹된 값만 표시됩니다.
        </p>
      </div>

      {status && (
        <Card className="mb-4">
          <div className="text-sm text-slate-700">
            현재 품질 모드 — 임베더 <Chip className="bg-sky-100 text-sky-700">{status.quality_mode.embedder}</Chip>{" "}
            · 랭커 <Chip className="bg-violet-100 text-violet-700">{status.quality_mode.ranker}</Chip>
          </div>
          <p className="mt-1 text-xs text-slate-400">키를 저장하면 로컬 폴백 → 품질 모드로 전환됩니다.</p>
        </Card>
      )}

      <div className="space-y-3">
        <ProviderRow
          provider="anthropic"
          label="Anthropic (Claude 랭킹 · /run · /eval)"
          status={status?.anthropic}
          verify={verify?.anthropic}
        />
        <ProviderRow
          provider="voyage"
          label="Voyage (임베딩 품질 모드)"
          status={status?.voyage}
          verify={verify?.voyage}
        />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <Button onClick={() => verifyM.mutate()} disabled={verifyM.isPending}>
          {verifyM.isPending ? "확인 중…" : "연동 확인"}
        </Button>
        <span className="text-xs text-slate-400">설정된 키로 최소 호출을 시도해 실제 연동 여부를 검사합니다.</span>
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
    mutationFn: () =>
      api.putKeys(provider === "anthropic" ? { anthropic_api_key: value } : { voyage_api_key: value }),
    onSuccess: () => {
      setValue("");
      refresh();
    },
  });
  const delM = useMutation({ mutationFn: () => api.deleteKey(provider), onSuccess: refresh });

  return (
    <Card>
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium text-slate-800">{label}</span>
        <span className="flex items-center gap-2 text-sm">
          {status?.set ? (
            <Chip className="bg-emerald-100 text-emerald-700">{status.masked}</Chip>
          ) : (
            <span className="text-slate-400">미설정</span>
          )}
          {verify && (
            <Chip className={verify === "ok" ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}>
              {verify === "ok" ? "연동 ✓" : verify === "unset" ? "—" : verify}
            </Chip>
          )}
        </span>
      </div>
      <div className="flex gap-2">
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={status?.set ? "새 키로 교체…" : "키 입력…"}
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        />
        <Button onClick={() => saveM.mutate()} disabled={!value || saveM.isPending}>
          {saveM.isPending ? "저장 중…" : "저장"}
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

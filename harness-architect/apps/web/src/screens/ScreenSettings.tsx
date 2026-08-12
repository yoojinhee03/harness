import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, auth, type ProviderStatus } from "../api/client";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, Input, Modal, PageHeader } from "../lib/ui";

export default function ScreenSettings({ onLogout }: { onLogout: () => void }) {
  const toast = useToast();
  const meQ = useQuery({ queryKey: ["me"], queryFn: api.me });
  const statusQ = useQuery({ queryKey: ["keys"], queryFn: api.getKeys });
  const [verify, setVerify] = useState<Record<string, string> | null>(null);
  const verifyM = useMutation({ mutationFn: api.verifyKeys, onSuccess: setVerify });
  const status = statusQ.data;

  // 토큰 재발급
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [newToken, setNewToken] = useState<string | null>(null);
  const rotateM = useMutation({
    mutationFn: api.rotateToken,
    onSuccess: (r) => {
      auth.setToken(r.token); // 현재 세션은 새 토큰 채택(기존 무효)
      setNewToken(r.token);
      setConfirmRotate(false);
      toast("토큰이 재발급됐어요 — 새 토큰을 복사하세요");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "재발급 실패", "error"),
  });

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <PageHeader title="설정" subtitle="계정 · API 키 · 품질 모드" />

        {/* 계정 */}
        <Card>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-accent/20 text-sm font-semibold text-accent">
                {(meQ.data?.handle ?? "?").slice(0, 1).toUpperCase()}
              </span>
              <div>
                <div className="text-sm font-semibold text-fg">{meQ.data?.handle ?? "…"}</div>
                <div className="text-xs text-muted">팀 {meQ.data?.teams.length ?? 0}개 · 이 브라우저에 토큰 저장됨</div>
              </div>
            </div>
            <Button variant="ghost" onClick={onLogout}>
              로그아웃
            </Button>
          </div>

          <div className="mt-4 flex items-center justify-between border-t border-line pt-4">
            <div>
              <div className="text-sm font-medium text-fg">API 토큰</div>
              <div className="text-xs text-muted">재발급하면 기존 토큰은 무효화됩니다(다른 기기·확장은 재로그인 필요).</div>
            </div>
            <Button variant="subtle" onClick={() => setConfirmRotate(true)} disabled={rotateM.isPending}>
              토큰 재발급
            </Button>
          </div>

          {newToken && (
            <div className="mt-3 rounded-lg border border-ok/40 bg-ok/5 p-3">
              <div className="text-xs font-medium text-ok">새 토큰 — 지금만 표시됩니다</div>
              <div className="mt-1.5 flex gap-2">
                <Input readOnly value={newToken} className="font-mono text-xs" onFocus={(e) => e.currentTarget.select()} />
                <Button variant="subtle" onClick={() => { navigator.clipboard?.writeText(newToken); toast("복사됨"); }}>
                  복사
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* API 키 */}
      <div>
        <h2 className="text-sm font-semibold text-fg">API 키</h2>
        <p className="mb-3 mt-0.5 text-sm text-muted">
          키는 백엔드 메모리에만 저장됩니다(디스크 저장 안 함). 화면엔 마스킹된 값만 표시됩니다.
        </p>

        {status && (
          <Card className="mb-3">
            <div className="flex items-center gap-2 text-sm text-fg/90">
              품질 모드 — 임베더 <Badge className="bg-sky-500/15 text-sky-400">{status.quality_mode.embedder}</Badge> · 랭커{" "}
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

      {confirmRotate && (
        <Modal title="토큰 재발급" onClose={() => setConfirmRotate(false)}>
          <p className="text-sm text-muted">
            기존 토큰이 즉시 무효화됩니다. 이 브라우저는 자동으로 새 토큰을 쓰지만, <b className="text-fg">VSCode 확장·다른 기기</b>는 새 토큰으로 다시 로그인해야 합니다.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmRotate(false)}>
              취소
            </Button>
            <Button variant="danger" onClick={() => rotateM.mutate()} disabled={rotateM.isPending}>
              재발급
            </Button>
          </div>
        </Modal>
      )}
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

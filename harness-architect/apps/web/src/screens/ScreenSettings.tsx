import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type ApiToken, type ProviderStatus } from "../api/client";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, EmptyState, Input, Modal, PageHeader } from "../lib/ui";

export default function ScreenSettings({ onLogout }: { onLogout: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const meQ = useQuery({ queryKey: ["me"], queryFn: api.me });
  const statusQ = useQuery({ queryKey: ["keys"], queryFn: api.getKeys });
  const tokensQ = useQuery({ queryKey: ["tokens"], queryFn: api.listTokens });
  const [verify, setVerify] = useState<Record<string, string> | null>(null);
  const verifyM = useMutation({ mutationFn: api.verifyKeys, onSuccess: setVerify });
  const status = statusQ.data;

  // PAT 발급 — 이름 입력 모달 → 발급 → 원문 1회 노출
  const [newName, setNewName] = useState<string | null>(null); // null 이면 모달 닫힘
  const [issued, setIssued] = useState<{ name: string; token: string } | null>(null);
  const createM = useMutation({
    mutationFn: (name: string) => api.createToken(name),
    onSuccess: (r) => {
      setIssued({ name: r.name, token: r.token });
      setNewName(null);
      qc.invalidateQueries({ queryKey: ["tokens"] });
      toast("토큰이 발급됐어요 — 지금 복사하세요");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "발급 실패", "error"),
  });
  const revokeM = useMutation({
    mutationFn: (id: string) => api.revokeToken(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tokens"] });
      toast("토큰이 폐기됐어요");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "폐기 실패", "error"),
  });

  const me = meQ.data;
  const display = me?.name || me?.email || "…";

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <PageHeader title="설정" subtitle="계정 · API 토큰 · 품질 모드" />

        {/* 계정 */}
        <Card>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {me?.avatar_url ? (
                <img src={me.avatar_url} alt="" className="h-9 w-9 rounded-full object-cover" />
              ) : (
                <span className="grid h-9 w-9 place-items-center rounded-full bg-accent/20 text-sm font-semibold text-accent">
                  {display.slice(0, 1).toUpperCase()}
                </span>
              )}
              <div>
                <div className="text-sm font-semibold text-fg">{display}</div>
                <div className="text-xs text-muted">
                  {me?.email ?? "…"} · 팀 {me?.teams.length ?? 0}개
                </div>
              </div>
            </div>
            <Button variant="ghost" onClick={onLogout}>
              로그아웃
            </Button>
          </div>
        </Card>
      </div>

      {/* API 토큰(PAT) — VSCode 연결 */}
      <div>
        <div className="mb-3 flex items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">API 토큰</h2>
            <p className="mt-0.5 text-sm text-muted">
              VSCode 확장·기계 연결용. 토큰은 발급 시 <b className="text-fg">한 번만</b> 보이니 안전하게 저장하세요.
            </p>
          </div>
          <Button variant="subtle" onClick={() => setNewName("")} disabled={createM.isPending}>
            + 새 토큰 발급
          </Button>
        </div>

        {issued && (
          <div className="mb-3 rounded-lg border border-ok/40 bg-ok/5 p-3">
            <div className="text-xs font-medium text-ok">
              새 토큰 “{issued.name}” — 지금만 표시됩니다
            </div>
            <div className="mt-1.5 flex gap-2">
              <Input
                readOnly
                value={issued.token}
                className="font-mono text-xs"
                onFocus={(e) => e.currentTarget.select()}
              />
              <Button
                variant="subtle"
                onClick={() => {
                  navigator.clipboard?.writeText(issued.token);
                  toast("복사됨");
                }}
              >
                복사
              </Button>
            </div>
            <p className="mt-2 text-xs text-muted">
              VSCode에서 <code>Harness Architect: 로그인</code> → 이 토큰을 붙여넣으세요.
            </p>
          </div>
        )}

        {tokensQ.data && tokensQ.data.length > 0 ? (
          <div className="space-y-2">
            {tokensQ.data.map((t) => (
              <TokenRow key={t.id} token={t} onRevoke={() => revokeM.mutate(t.id)} busy={revokeM.isPending} />
            ))}
          </div>
        ) : (
          <EmptyState
            title="아직 발급한 토큰이 없어요"
            hint="VSCode 확장을 연결하려면 토큰을 발급해 붙여넣으세요."
          />
        )}
      </div>

      {/* LLM 키 (배포 구성, 읽기전용) */}
      <div>
        <h2 className="text-sm font-semibold text-fg">LLM 키 (품질 모드)</h2>
        <p className="mb-3 mt-0.5 text-sm text-muted">
          키는 <b className="text-fg">배포 환경변수</b>(ANTHROPIC_API_KEY·VOYAGE_API_KEY)로만 설정됩니다. 운영 시크릿이라 화면에서 변경하지 않습니다.
        </p>

        {status && (
          <Card className="mb-3">
            <div className="flex items-center gap-2 text-sm text-fg/90">
              품질 모드 — 임베더 <Badge className="bg-sky-500/15 text-sky-400">{status.quality_mode.embedder}</Badge> · 랭커{" "}
              <Badge className="bg-violet-500/15 text-violet-400">{status.quality_mode.ranker}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted">키가 배포에 있으면 로컬 폴백 → 품질 모드로 자동 전환됩니다.</p>
          </Card>
        )}

        <div className="space-y-3">
          <ProviderRow label="Anthropic (Claude 랭킹 · /run · /eval)" status={status?.anthropic} verify={verify?.anthropic} />
          <ProviderRow label="Voyage (임베딩 품질 모드)" status={status?.voyage} verify={verify?.voyage} />
        </div>

        <div className="mt-4 flex items-center gap-3">
          <Button variant="subtle" onClick={() => verifyM.mutate()} disabled={verifyM.isPending}>
            {verifyM.isPending ? "확인 중…" : "연동 확인"}
          </Button>
          <span className="text-xs text-muted">배포 env 키로 최소 호출을 시도해 실제 연동 여부를 검사합니다.</span>
        </div>
      </div>

      {newName !== null && (
        <Modal title="새 API 토큰 발급" onClose={() => setNewName(null)}>
          <label className="block text-xs font-medium text-muted">
            토큰 이름
            <Input
              autoFocus
              className="mt-1.5"
              placeholder="예: 노트북 VSCode"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && createM.mutate(newName.trim() || "VSCode")}
            />
          </label>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setNewName(null)}>
              취소
            </Button>
            <Button onClick={() => createM.mutate(newName.trim() || "VSCode")} disabled={createM.isPending}>
              발급
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function TokenRow({ token, onRevoke, busy }: { token: ApiToken; onRevoke: () => void; busy: boolean }) {
  const created = new Date(token.created_at).toLocaleString("ko-KR");
  const lastUsed = token.last_used_at ? new Date(token.last_used_at).toLocaleString("ko-KR") : "미사용";
  return (
    <Card className="flex items-center justify-between">
      <div className="min-w-0">
        <div className="text-sm font-medium text-fg">{token.name || "(이름 없음)"}</div>
        <div className="mt-0.5 text-xs text-muted">
          발급 {created} · 마지막 사용 {lastUsed}
        </div>
      </div>
      <button
        className="rounded-lg px-2 py-1 text-xs text-muted transition-colors hover:text-err disabled:opacity-40"
        onClick={onRevoke}
        disabled={busy}
        title="토큰 폐기"
      >
        폐기
      </button>
    </Card>
  );
}

function ProviderRow({ label, status, verify }: { label: string; status?: ProviderStatus; verify?: string }) {
  return (
    <Card className="flex items-center justify-between">
      <div>
        <div className="text-sm font-medium text-fg">{label}</div>
        <div className="text-xs text-muted">배포 환경변수로 설정 · 런타임 변경 불가</div>
      </div>
      <span className="flex items-center gap-2 text-sm">
        {status?.set ? <Badge className="bg-ok/15 text-ok">{status.masked}</Badge> : <span className="text-muted">미설정</span>}
        {verify && (
          <Badge className={verify === "ok" ? "bg-ok/15 text-ok" : "bg-err/15 text-err"}>
            {verify === "ok" ? "연동 ✓" : verify === "unset" ? "—" : verify}
          </Badge>
        )}
      </span>
    </Card>
  );
}

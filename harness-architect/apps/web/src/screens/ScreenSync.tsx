import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, auth, scopePref, subscribeHarnessEvents, type Team } from "../api/client";
import { Badge, Button, Card, codeBlock, EmptyState, Input, PageHeader } from "../lib/ui";

export default function ScreenSync() {
  const [loggedIn, setLoggedIn] = useState(() => auth.token().length > 0);
  if (!loggedIn) return <LoginGate onLogin={() => setLoggedIn(true)} />;
  return <SyncBoard onLogout={() => setLoggedIn(false)} />;
}

function LoginGate({ onLogin }: { onLogin: () => void }) {
  const [handle, setHandle] = useState("");
  const [token, setToken] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function register() {
    setErr(null);
    try {
      const acct = await api.register(handle.trim());
      auth.setToken(acct.token);
      onLogin();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }
  function useToken() {
    if (!token.trim()) return;
    auth.setToken(token.trim());
    onLogin();
  }

  return (
    <div className="mx-auto max-w-md">
      <PageHeader title="공유 저장소 로그인" subtitle="사용자별 격리 + 팀 공유를 위한 신원. 토큰은 브라우저에 저장됩니다." />
      <Card className="space-y-4">
        <div>
          <label className="text-xs font-medium text-muted">새 계정 만들기 — handle</label>
          <div className="mt-1.5 flex gap-2">
            <Input placeholder="예: alice" value={handle} onChange={(e) => setHandle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && register()} />
            <Button onClick={register} disabled={!handle.trim()}>
              가입
            </Button>
          </div>
        </div>
        <div className="border-t border-line pt-4">
          <label className="text-xs font-medium text-muted">또는 기존 토큰 붙여넣기</label>
          <div className="mt-1.5 flex gap-2">
            <Input type="password" placeholder="토큰" value={token} onChange={(e) => setToken(e.target.value)} />
            <Button variant="subtle" onClick={useToken} disabled={!token.trim()}>
              로그인
            </Button>
          </div>
        </div>
        {err && <p className="text-sm text-err">{err}</p>}
      </Card>
    </div>
  );
}

function SyncBoard({ onLogout }: { onLogout: () => void }) {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const { data: list = [], isError } = useQuery({ queryKey: ["harnesses"], queryFn: api.listHarnesses });
  const [scope, setScope] = useState(() => scopePref.get());
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [doc, setDoc] = useState<string | null>(null);

  useEffect(() => subscribeHarnessEvents(() => qc.invalidateQueries({ queryKey: ["harnesses"] })), [qc]);

  function pickScope(s: string) {
    setScope(s);
    scopePref.set(s);
  }
  const teams: Team[] = me.data?.teams ?? [];

  async function openOne(id: string, sc: string) {
    const key = `${sc}/${id}`;
    if (openKey === key) {
      setOpenKey(null);
      setDoc(null);
      return;
    }
    const full = await api.getHarness(id, sc);
    setOpenKey(key);
    setDoc(full.yaml);
  }
  async function del(id: string, sc: string) {
    await api.deleteHarness(id, sc);
    qc.invalidateQueries({ queryKey: ["harnesses"] });
  }
  async function newTeam() {
    const name = prompt("새 팀 이름");
    if (!name) return;
    await api.createTeam(name);
    qc.invalidateQueries({ queryKey: ["me"] });
  }
  async function invite(tid: string) {
    const handle = prompt("추가할 멤버 handle");
    if (!handle) return;
    await api.addMember(tid, handle);
    qc.invalidateQueries({ queryKey: ["me"] });
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title={`${me.data?.handle ?? "…"} 의 하네스`}
        subtitle="사용자별 격리 + 팀 공유 · 실시간 동기화(SSE) · VSCode 확장과 동일"
        actions={
          <button className="text-xs text-muted hover:text-fg" onClick={() => { auth.clear(); onLogout(); }}>
            로그아웃
          </button>
        }
      />

      {/* 저장 스코프 스위처 */}
      <Card className="mb-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">저장 스코프</span>
          <ScopeChip active={scope === "personal"} onClick={() => pickScope("personal")}>
            개인
          </ScopeChip>
          {teams.map((t) => (
            <ScopeChip key={t.id} active={scope === `team:${t.id}`} onClick={() => pickScope(`team:${t.id}`)}>
              👥 {t.name}
            </ScopeChip>
          ))}
          <button className="ml-1 text-xs text-muted hover:text-fg" onClick={newTeam}>
            + 새 팀
          </button>
        </div>
      </Card>

      {isError && (
        <Card className="mb-3 border-warn/40">
          <p className="text-sm text-muted">백엔드 연결/인증 확인 필요.</p>
        </Card>
      )}

      {list.length === 0 ? (
        <EmptyState title="저장된 하네스가 없습니다" hint="생성 흐름의 harness.yaml 단계에서 저장하면 여기에 나타납니다." />
      ) : (
        <div className="space-y-2.5">
          {list.map((h) => {
            const isTeam = h.scope.startsWith("team:");
            const key = `${h.scope}/${h.id}`;
            return (
              <Card key={key}>
                <div className="flex items-center justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-fg">{h.name || h.id}</span>
                      <Badge className={isTeam ? "bg-violet-500/15 text-violet-400" : "bg-surface-2 text-muted"}>
                        {isTeam ? `👥 ${h.scope.slice(5)}` : "개인"}
                      </Badge>
                    </div>
                    <div className="mt-1 text-xs text-muted">
                      <code className="rounded bg-surface-2 px-1.5 py-0.5">{h.id}</code>
                      {h.updated_at && <span className="ml-1.5">· {new Date(h.updated_at).toLocaleString("ko-KR")}</span>}
                      <span className="ml-1.5">· 소유 {h.owner_id}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button variant="ghost" onClick={() => openOne(h.id, h.scope)}>
                      {openKey === key ? "닫기" : "열기"}
                    </Button>
                    <button className="rounded-lg px-2 text-muted hover:text-err" onClick={() => del(h.id, h.scope)} title="삭제">
                      ✕
                    </button>
                  </div>
                </div>
                {openKey === key && doc && <pre className={`mt-3 ${codeBlock}`}>{doc}</pre>}
              </Card>
            );
          })}
        </div>
      )}

      {teams.length > 0 && (
        <div className="mt-6">
          <h3 className="mb-2 text-sm font-semibold text-fg">내 팀</h3>
          <div className="space-y-2">
            {teams.map((t) => (
              <Card key={t.id} className="flex items-center justify-between">
                <div className="text-sm">
                  <span className="font-medium text-fg">{t.name}</span>
                  <span className="ml-2 text-xs text-muted">team:{t.id} · 멤버 {t.members.length}명</span>
                </div>
                <Button variant="ghost" onClick={() => invite(t.id)}>
                  + 멤버 초대
                </Button>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ScopeChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
        active ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted hover:text-fg"
      }`}
    >
      {children}
    </button>
  );
}

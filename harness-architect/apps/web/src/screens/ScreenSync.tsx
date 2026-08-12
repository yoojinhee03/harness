import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, scopePref, subscribeHarnessEvents, type Team } from "../api/client";
import { Badge, Button, Card, codeBlock, EmptyState, Input, Modal, PageHeader } from "../lib/ui";
import { useToast } from "../lib/toast";

/**
 * 하네스 화면 — 내 personal + 내 팀들의 하네스(스코프 격리). 실시간 동기화(SSE).
 * 인증은 앱 진입 게이트에서 보장되므로 여기선 로그인 UI 가 없다.
 */
export default function ScreenSync() {
  const qc = useQueryClient();
  const toast = useToast();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const { data: list = [], isError } = useQuery({ queryKey: ["harnesses"], queryFn: api.listHarnesses });
  const [scope, setScope] = useState(() => scopePref.get());
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [doc, setDoc] = useState<string | null>(null);

  // 다이얼로그 상태(네이티브 prompt/confirm 대체)
  const [teamName, setTeamName] = useState<string | null>(null);
  const [inviteFor, setInviteFor] = useState<Team | null>(null);
  const [inviteHandle, setInviteHandle] = useState("");
  const [delFor, setDelFor] = useState<{ id: string; scope: string; name: string } | null>(null);

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
  async function confirmDelete() {
    if (!delFor) return;
    const target = delFor;
    setDelFor(null);
    try {
      await api.deleteHarness(target.id, target.scope);
      qc.invalidateQueries({ queryKey: ["harnesses"] });
      toast(`삭제됨: ${target.name}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "삭제 실패", "error");
    }
  }
  async function createTeam() {
    const name = (teamName ?? "").trim();
    if (!name) return;
    setTeamName(null);
    try {
      const t = await api.createTeam(name);
      qc.invalidateQueries({ queryKey: ["me"] });
      toast(`팀 생성됨: ${t.name}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "팀 생성 실패", "error");
    }
  }
  async function invite() {
    if (!inviteFor || !inviteHandle.trim()) return;
    const team = inviteFor;
    const handle = inviteHandle.trim();
    setInviteFor(null);
    setInviteHandle("");
    try {
      const t = await api.addMember(team.id, handle);
      qc.invalidateQueries({ queryKey: ["me"] });
      toast(`'${handle}' 추가됨 — ${t.name} 멤버 ${t.members.length}명`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "멤버 추가 실패", "error");
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="하네스" subtitle="내 하네스 · 팀 공유 · 실시간 동기화(SSE) · VSCode 확장과 동일" />

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
          <button className="ml-1 text-xs text-muted hover:text-fg" onClick={() => setTeamName("")}>
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
                    <button
                      className="rounded-lg px-2 text-muted hover:text-err"
                      onClick={() => setDelFor({ id: h.id, scope: h.scope, name: h.name || h.id })}
                      title="삭제"
                    >
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
                <Button variant="ghost" onClick={() => setInviteFor(t)}>
                  + 멤버 초대
                </Button>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* ── 다이얼로그 ── */}
      {teamName !== null && (
        <Modal title="새 팀 만들기" onClose={() => setTeamName(null)}>
          <Input
            autoFocus
            placeholder="팀 이름"
            value={teamName}
            onChange={(e) => setTeamName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && createTeam()}
          />
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setTeamName(null)}>
              취소
            </Button>
            <Button onClick={createTeam} disabled={!teamName.trim()}>
              만들기
            </Button>
          </div>
        </Modal>
      )}
      {inviteFor && (
        <Modal title={`${inviteFor.name} — 멤버 초대`} onClose={() => setInviteFor(null)}>
          <Input
            autoFocus
            placeholder="추가할 멤버 handle"
            value={inviteHandle}
            onChange={(e) => setInviteHandle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && invite()}
          />
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setInviteFor(null)}>
              취소
            </Button>
            <Button onClick={invite} disabled={!inviteHandle.trim()}>
              초대
            </Button>
          </div>
        </Modal>
      )}
      {delFor && (
        <Modal title="하네스 삭제" onClose={() => setDelFor(null)}>
          <p className="text-sm text-muted">
            <b className="text-fg">{delFor.name}</b> 를 삭제할까요? ({delFor.scope})
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDelFor(null)}>
              취소
            </Button>
            <Button variant="danger" onClick={confirmDelete}>
              삭제
            </Button>
          </div>
        </Modal>
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

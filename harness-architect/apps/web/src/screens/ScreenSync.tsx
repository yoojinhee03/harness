import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, subscribeHarnessEvents, type Team } from "../api/client";
import { diffLines } from "../lib/diff";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, codeBlock, EmptyState, Input, Modal, PageHeader, SeverityDot, SkeletonCards } from "../lib/ui";

/**
 * 하네스 화면 — 현재 워크스페이스(개인/팀)의 하네스. 워크스페이스 전환은 사이드바 스위처가,
 * 여기선 그 스코프의 하네스 목록·버전·팀 관리를 다룬다. 인증은 앱 게이트에서 보장.
 */
/** 풀 스코프("personal:<uid>" / "team:<tid>") → API 쿼리 스코프("personal" / "team:<tid>"). */
function scopeQuery(s: string): string {
  return s.startsWith("team:") ? s : "personal";
}

export default function ScreenSync({ onCreate, workspace }: { onCreate: () => void; workspace: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const { data: list = [], isError, isLoading } = useQuery({ queryKey: ["harnesses"], queryFn: api.listHarnesses });
  const [openKey, setOpenKey] = useState<string | null>(null);

  const [teamName, setTeamName] = useState<string | null>(null);
  const [inviteFor, setInviteFor] = useState<Team | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("editor");
  const [delFor, setDelFor] = useState<{ id: string; scope: string; name: string } | null>(null);

  useEffect(() => subscribeHarnessEvents(() => qc.invalidateQueries({ queryKey: ["harnesses"] })), [qc]);

  const teams: Team[] = me.data?.teams ?? [];
  const isTeamWs = workspace.startsWith("team:");
  const wsLabel = isTeamWs ? (teams.find((t) => `team:${t.id}` === workspace)?.name ?? workspace.slice(5)) : "개인";
  const shown = list.filter((h) => (isTeamWs ? h.scope === workspace : h.scope.startsWith("personal:")));

  function toggleOpen(key: string) {
    setOpenKey((k) => (k === key ? null : key));
  }
  async function confirmDelete() {
    if (!delFor) return;
    const t = delFor;
    setDelFor(null);
    try {
      await api.deleteHarness(t.id, scopeQuery(t.scope));
      qc.invalidateQueries({ queryKey: ["harnesses"] });
      toast(`삭제됨: ${t.name}`);
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
    if (!inviteFor || !inviteEmail.trim()) return;
    const team = inviteFor;
    const email = inviteEmail.trim();
    const role = inviteRole;
    setInviteFor(null);
    setInviteEmail("");
    setInviteRole("editor");
    try {
      const t = await api.addMember(team.id, email, role);
      qc.invalidateQueries({ queryKey: ["me"] });
      toast(`'${email}' (${role}) 추가됨 — ${t.name} 멤버 ${t.members.length}명`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "멤버 추가 실패", "error");
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="하네스"
        subtitle={
          <>
            <b className="text-fg">{wsLabel}</b> 워크스페이스 · 실시간 동기화(SSE) · VSCode 확장과 동일. 새 저장은 여기로.
          </>
        }
        actions={
          <Button variant="subtle" onClick={() => setTeamName("")}>
            + 새 팀
          </Button>
        }
      />

      {isError && (
        <Card className="mb-3 border-warn/40">
          <p className="text-sm text-muted">백엔드 연결/인증 확인 필요.</p>
        </Card>
      )}

      {isLoading ? (
        <SkeletonCards count={3} cols="grid-cols-1" />
      ) : shown.length === 0 ? (
        <EmptyState
          title={isTeamWs ? `${wsLabel} 팀에 아직 하네스가 없어요` : "아직 하네스가 없어요"}
          hint="프로젝트를 설명해 harness.yaml 을 만들고 저장하면 이 워크스페이스와 VSCode 확장에 실시간으로 나타납니다."
          action={<Button onClick={onCreate}>첫 하네스 만들기 →</Button>}
        />
      ) : (
        <div className="space-y-2.5">
          {shown.map((h) => {
            const key = `${h.scope}/${h.id}`;
            return (
              <Card key={key}>
                <div className="flex items-center justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-fg">{h.name || h.id}</span>
                      {h.version > 1 && <Badge className="bg-surface-2 text-muted">v{h.version}</Badge>}
                    </div>
                    <div className="mt-1 text-xs text-muted">
                      <code className="rounded bg-surface-2 px-1.5 py-0.5">{h.id}</code>
                      {h.updated_at && <span className="ml-1.5">· {new Date(h.updated_at).toLocaleString("ko-KR")}</span>}
                      <span className="ml-1.5">· 소유 {h.owner_id}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button variant="ghost" onClick={() => toggleOpen(key)}>
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
                {openKey === key && (
                  <>
                    <HistoryPanel id={h.id} scope={h.scope} />
                    <HarnessActions id={h.id} scope={h.scope} />
                  </>
                )}
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
              <Card key={t.id}>
                <div className="flex items-center justify-between">
                  <div className="text-sm">
                    <span className="font-medium text-fg">{t.name}</span>
                    <span className="ml-2 text-xs text-muted">team:{t.id} · 멤버 {t.members.length}명</span>
                  </div>
                  <Button variant="ghost" onClick={() => setInviteFor(t)}>
                    + 멤버 초대
                  </Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {t.members.map((m) => (
                    <span key={m.id} className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs">
                      <span className="text-fg/90" title={m.email}>{m.name || m.email}</span>
                      <RoleBadge role={m.role} />
                    </span>
                  ))}
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* 다이얼로그 */}
      {teamName !== null && (
        <Modal title="새 팀 만들기" onClose={() => setTeamName(null)}>
          <Input autoFocus placeholder="팀 이름" value={teamName} onChange={(e) => setTeamName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && createTeam()} />
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setTeamName(null)}>취소</Button>
            <Button onClick={createTeam} disabled={!teamName.trim()}>만들기</Button>
          </div>
        </Modal>
      )}
      {inviteFor && (
        <Modal title={`${inviteFor.name} — 멤버 초대`} onClose={() => setInviteFor(null)}>
          <Input autoFocus type="email" placeholder="추가할 멤버 이메일" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} onKeyDown={(e) => e.key === "Enter" && invite()} />
          <div className="mt-2.5">
            <label className="text-xs text-muted">역할</label>
            <div className="mt-1 flex gap-1.5">
              {["viewer", "editor", "owner"].map((r) => (
                <button
                  key={r}
                  onClick={() => setInviteRole(r)}
                  className={`flex-1 rounded-lg border px-2 py-1.5 text-xs font-medium transition-colors ${
                    inviteRole === r ? "border-accent bg-accent/10 text-fg" : "border-line text-muted hover:text-fg"
                  }`}
                >
                  {r === "viewer" ? "뷰어(읽기)" : r === "editor" ? "에디터(쓰기)" : "오너"}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setInviteFor(null)}>취소</Button>
            <Button onClick={invite} disabled={!inviteEmail.trim()}>초대</Button>
          </div>
        </Modal>
      )}
      {delFor && (
        <Modal title="하네스 삭제" onClose={() => setDelFor(null)}>
          <p className="text-sm text-muted">
            <b className="text-fg">{delFor.name}</b> 를 삭제할까요? ({delFor.scope})
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDelFor(null)}>취소</Button>
            <Button variant="danger" onClick={confirmDelete}>삭제</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const cls =
    role === "owner"
      ? "bg-violet-500/15 text-violet-400"
      : role === "viewer"
        ? "bg-surface-2 text-muted"
        : "bg-sky-500/15 text-sky-400";
  return <span className={`rounded px-1 py-0.5 text-[10px] font-medium ${cls}`}>{role}</span>;
}

function HistoryPanel({ id, scope }: { id: string; scope: string }) {
  const { data: versions = [], isLoading } = useQuery({
    queryKey: ["versions", scope, id],
    queryFn: () => api.harnessVersions(id, scopeQuery(scope)),
  });
  const [sel, setSel] = useState<number | null>(null);

  if (isLoading || versions.length === 0) return <pre className={`mt-3 ${codeBlock}`}> </pre>;
  const latest = versions[0];
  const older = sel != null ? versions.find((v) => v.version === sel) : null;

  return (
    <div className="mt-3">
      {versions.length > 1 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted">버전</span>
          {versions.map((v, idx) => {
            const active = idx === 0 ? sel == null : sel === v.version;
            return (
              <button
                key={v.version}
                onClick={() => setSel(idx === 0 ? null : v.version)}
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                  active ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted hover:text-fg"
                }`}
              >
                v{v.version}
                {idx === 0 ? " 최신" : ""}
              </button>
            );
          })}
          {older && (
            <span className="text-xs text-muted">
              v{older.version} → v{latest.version} 변경점
            </span>
          )}
        </div>
      )}
      {older ? <DiffView oldText={older.yaml} newText={latest.yaml} /> : <pre className={codeBlock}>{latest.yaml}</pre>}
    </div>
  );
}

/** 하네스 상세 액션 — 검증(gap/충돌 진단) + eject(런타임 파일 방출). 구 '생성' 위저드 C·D 대체. */
function HarnessActions({ id, scope }: { id: string; scope: string }) {
  const qs = scope.startsWith("team:") ? scope : "personal";
  const valM = useMutation({ mutationFn: () => api.validateHarness(id, qs) });
  const targetsQ = useQuery({ queryKey: ["eject-targets"], queryFn: api.ejectTargets });
  const targets = targetsQ.data ?? ["claude-code"];
  const [target, setTarget] = useState("claude-code");
  const ejM = useMutation({ mutationFn: () => api.ejectHarness(id, qs, target) });

  const diag = valM.data?.diagnostics.items ?? [];
  const errors = diag.filter((d) => d.severity === "error");
  const gaps = diag.filter((d) => d.severity === "gap");
  const warnings = diag.filter((d) => d.severity === "warning");
  const files = ejM.data?.ok ? ejM.data.files : null;

  return (
    <div className="mt-3 border-t border-line pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="subtle" onClick={() => valM.mutate()} disabled={valM.isPending}>
          {valM.isPending ? "검증 중…" : "검증"}
        </Button>
        {valM.data &&
          (errors.length ? (
            <Badge className="bg-err/15 text-err">오류 {errors.length}</Badge>
          ) : gaps.length ? (
            <Badge className="bg-warn/15 text-warn">gap {gaps.length}</Badge>
          ) : warnings.length ? (
            <Badge className="bg-warn/15 text-warn">경고 {warnings.length}</Badge>
          ) : (
            <Badge className="bg-ok/15 text-ok">통과</Badge>
          ))}
        <span className="ml-auto flex items-center gap-1.5">
          {targets.map((t) => (
            <button
              key={t}
              onClick={() => setTarget(t)}
              className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                t === target ? "bg-surface-2 text-fg ring-1 ring-line" : "text-muted hover:text-fg"
              }`}
            >
              {t}
            </button>
          ))}
          <Button size="sm" onClick={() => ejM.mutate()} disabled={ejM.isPending}>
            {ejM.isPending ? "방출 중…" : "Eject"}
          </Button>
        </span>
      </div>

      {valM.data && diag.length > 0 && (
        <ul className="mt-2 space-y-1">
          {diag.slice(0, 8).map((d, i) => (
            <li key={i} className="flex items-center gap-2 text-xs">
              <SeverityDot severity={d.severity} />
              <span className={d.severity === "error" ? "text-err" : "text-warn"}>{d.message}</span>
            </li>
          ))}
        </ul>
      )}
      {ejM.data && !ejM.data.ok && (
        <p className="mt-2 text-xs text-warn">resolve 실패(gap·오류) — 먼저 검증에서 해소하세요.</p>
      )}
      {files && (
        <div className="mt-2 space-y-2">
          {Object.entries(files).map(([path, content]) => (
            <div key={path}>
              <div className="mb-1 font-mono text-[11px] text-muted">{path}</div>
              <pre className={`max-h-40 ${codeBlock}`}>{content}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DiffView({ oldText, newText }: { oldText: string; newText: string }) {
  const lines = diffLines(oldText, newText);
  return (
    <pre className={`${codeBlock} whitespace-pre`}>
      {lines.map((l, i) => (
        <div key={i} className={l.type === "add" ? "bg-ok/10 text-ok" : l.type === "del" ? "bg-err/10 text-err" : ""}>
          {l.type === "add" ? "+ " : l.type === "del" ? "− " : "  "}
          {l.text || " "}
        </div>
      ))}
    </pre>
  );
}

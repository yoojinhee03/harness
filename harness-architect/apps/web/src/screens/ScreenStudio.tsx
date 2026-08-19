import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  api,
  streamStudioChat,
  subscribeConversationEvents,
  type AuthoredComponent,
  type CapabilityGap,
  type ComponentType,
  type Recommendation,
  type StudioConversation,
  type StudioConversationSummary,
  type StudioHarness,
  type StudioMessage,
} from "../api/client";
import { capLabel } from "../lib/catalog";
import { useToast } from "../lib/toast";
import {
  Badge,
  Button,
  Card,
  Chip,
  codeBlock,
  EmptyState,
  IconButton,
  PageHeader,
  Spinner,
  Textarea,
  TYPE_COLOR,
  TYPE_LABEL,
} from "../lib/ui";

// 진행 중인 한 턴(스트리밍) — 서버 영속 세트와 별개로 라이브 렌더.
interface LiveTurn {
  userText: string;
  phase: string; // status 라벨(도구 실행 알림)
  prose: string; // 누적 토큰
  recommendations?: Recommendation[];
  gaps?: CapabilityGap[]; // 카탈로그 공백 — 재사용 후보와 동등하게 렌더
  components?: AuthoredComponent[]; // 초안 세트(갱신되면 통째로 들어옴)
  harness?: StudioHarness;
}

function scopeQuery(fullScope: string): string {
  return fullScope.startsWith("team:") ? fullScope : "personal";
}

function lastMeta<T>(conv: StudioConversation | undefined, pick: (m: StudioMessage) => T | null | undefined): T | null {
  if (!conv) return null;
  for (let i = conv.messages.length - 1; i >= 0; i--) {
    const v = pick(conv.messages[i]);
    if (v) return v;
  }
  return null;
}

export default function ScreenStudio({ workspace }: { workspace: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [active, setActive] = useState<{ id: string; scope: string } | null>(null);
  const [input, setInput] = useState("");
  const [live, setLive] = useState<LiveTurn | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const streaming = live !== null;

  const convsQ = useQuery({ queryKey: ["studio-convs"], queryFn: () => api.listConversations() });
  const convs = convsQ.data ?? [];
  const convQ = useQuery({
    queryKey: ["studio-conv", active?.id],
    queryFn: () => api.getConversation(active!.id, active!.scope),
    enabled: !!active,
  });
  const conv = convQ.data;
  const llmQ = useQuery({ queryKey: ["llm-settings"], queryFn: api.getLlmSettings });
  const keySet = llmQ.data?.llm.set ?? false;

  useEffect(() => subscribeConversationEvents(() => qc.invalidateQueries({ queryKey: ["studio-convs"] })), [qc]);

  useEffect(() => {
    if (!active && convs.length) setActive({ id: convs[0].id, scope: scopeQuery(convs[0].scope) });
  }, [convs, active]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [conv?.messages.length, live?.prose, live?.phase]);

  const newConvMut = useMutation({
    mutationFn: () => api.createConversation(scopeQuery(workspace)),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["studio-convs"] });
      setActive({ id: c.id, scope: scopeQuery(c.scope) });
      setLive(null);
    },
  });

  const delConvMut = useMutation({
    mutationFn: (c: StudioConversationSummary) => api.deleteConversation(c.id, scopeQuery(c.scope)),
    onSuccess: (_r, c) => {
      qc.invalidateQueries({ queryKey: ["studio-convs"] });
      if (active?.id === c.id) setActive(null);
    },
    onError: (e: Error) => toast(e.message || "삭제 실패", "error"),
  });

  const commitMut = useMutation({
    mutationFn: () => api.commitConversation(active!.id, active!.scope, {}),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["studio-conv", active!.id] });
      qc.invalidateQueries({ queryKey: ["components"] });
      qc.invalidateQueries({ queryKey: ["studio-convs"] });
      const ok = r.saved.filter((s) => s.validation.ok).length;
      const h = r.harness ? ` + 에이전트 '${r.harness.name}'` : "";
      toast(`${r.saved.length}개 구성요소 저장(검증 ${ok})${h}`, ok === r.saved.length ? "success" : "info");
    },
    onError: (e: Error) => toast(e.message || "저장 실패", "error"),
  });

  const testMut = useMutation({
    mutationFn: () => api.testConversation(active!.id, active!.scope),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["studio-conv", active!.id] });
      qc.invalidateQueries({ queryKey: ["components"] });
      const passed = r.results.filter((x) => x.pass).length;
      toast(`테스트 ${passed}/${r.results.length} 통과`, passed === r.results.length ? "success" : "info");
    },
    onError: (e: Error) => toast(e.message || "테스트 실패", "error"),
  });

  async function send() {
    const text = input.trim();
    if (!text || streaming || !keySet) return;
    setInput("");
    let a = active;
    if (!a) {
      const c = await api.createConversation(scopeQuery(workspace));
      qc.invalidateQueries({ queryKey: ["studio-convs"] });
      a = { id: c.id, scope: scopeQuery(c.scope) };
      setActive(a);
    }
    setLive({ userText: text, phase: "생각 중…", prose: "" });
    try {
      await streamStudioChat(a.id, a.scope, text, null, (ev) => {
        setLive((prev) => {
          if (!prev) return prev;
          switch (ev.event) {
            case "status":
              return { ...prev, phase: ev.data.label };
            case "recommendations":
              return { ...prev, recommendations: ev.data.items, gaps: ev.data.gaps ?? [] };
            case "drafts":
              return { ...prev, components: ev.data.components };
            case "harness":
              return { ...prev, harness: ev.data.harness };
            case "token":
              return { ...prev, prose: prev.prose + ev.data.text };
            case "error":
              toast(ev.data.detail, "error");
              return prev;
            default:
              return prev;
          }
        });
      });
    } catch (e) {
      toast((e as Error).message || "대화 실패", "error");
    } finally {
      await qc.invalidateQueries({ queryKey: ["studio-conv", a.id] });
      qc.invalidateQueries({ queryKey: ["studio-convs"] });
      setLive(null);
    }
  }

  const messages = conv?.messages ?? [];
  const dset = conv?.draft_set ?? { components: [], harness: null };
  const components = live?.components ?? dset.components ?? [];
  const harness = live?.harness ?? dset.harness ?? null;
  const recs = live?.recommendations ?? lastMeta(conv, (m) => m.meta?.recommendations) ?? null;
  const gaps = live?.gaps ?? lastMeta(conv, (m) => m.meta?.gaps) ?? null;
  const hasResult = components.length > 0 || !!harness;
  const showRecs = !hasResult && ((!!recs && recs.length > 0) || (!!gaps && gaps.length > 0));
  const committed = !!conv?.component_id;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr_380px]">
      {/* ── 대화 리스트 ── */}
      <aside className="lg:sticky lg:top-2 lg:self-start">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-fg">대화</h3>
          <Button size="sm" variant="subtle" onClick={() => newConvMut.mutate()} disabled={newConvMut.isPending}>
            + 새 대화
          </Button>
        </div>
        <div className="space-y-1">
          {convs.length === 0 && <p className="px-1 text-xs text-muted">아직 대화가 없어요.</p>}
          {convs.map((c) => (
            <div
              key={`${c.scope}/${c.id}`}
              className={`group flex items-center gap-1 rounded-lg border px-2.5 py-2 text-sm transition-colors ${
                active?.id === c.id ? "border-accent bg-accent/10 text-fg" : "border-line text-muted hover:text-fg"
              }`}
            >
              <button
                className="min-w-0 flex-1 truncate text-left"
                onClick={() => setActive({ id: c.id, scope: scopeQuery(c.scope) })}
                title={c.title || "새 대화"}
              >
                {c.title || "새 대화"}
                {c.component_id && <span className="ml-1 text-ok">✓</span>}
              </button>
              <IconButton
                className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100"
                title="대화 삭제"
                onClick={() => delConvMut.mutate(c)}
              >
                ✕
              </IconButton>
            </div>
          ))}
        </div>
      </aside>

      {/* ── 채팅 스레드 ── */}
      <div className="flex min-h-[68vh] flex-col">
        <PageHeader
          title="스튜디오"
          subtitle="대화로 에이전트에 필요한 구성요소를 만들고, 하나의 에이전트로 조립합니다."
        />

        <div className="flex-1 space-y-3 overflow-y-auto pr-1">
          {!active || messages.length === 0 ? (
            <EmptyState
              title="어떤 에이전트를 만들까요?"
              hint={'예: "브이로그를 자동편집하는 에이전트" · "PR 올라오면 슬랙 알림 보내는 훅" · "GitHub 이슈 접근 도구 있어?"'}
            />
          ) : (
            messages.map((m) => <MessageBubble key={m.id} m={m} />)
          )}
          {live && <LiveBubble live={live} />}
          <div ref={bottomRef} />
        </div>

        {!keySet && (
          <div className="mt-3 rounded-md border border-warn/40 bg-warn/5 p-2.5 text-xs text-warn">
            LLM 키가 없어 대화가 잠겨 있어요 — 설정 → LLM 키에서 등록하세요.
          </div>
        )}

        <div className="mt-2 flex flex-wrap gap-1.5">
          {[
            { label: "추천만", text: "이미 비슷한 게 있으면 추천만 해줘: " },
            { label: "전부 만들기", text: "이 에이전트에 필요한 구성요소를 전부 만들고 하나로 조립해줘: " },
          ].map((q) => (
            <button
              key={q.label}
              className="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted hover:text-fg"
              onClick={() => setInput((v) => q.text + v)}
            >
              {q.label}
            </button>
          ))}
        </div>

        <div className="mt-2 flex items-end gap-2">
          <Textarea
            className="min-h-[52px]"
            placeholder="만들고 싶은 걸 설명하거나 고쳐달라고 하세요 (Enter 전송 · Shift+Enter 줄바꿈)"
            value={input}
            disabled={!keySet}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <Button onClick={() => void send()} disabled={streaming || !input.trim() || !keySet}>
            {streaming ? <Spinner /> : "전송"}
          </Button>
        </div>
      </div>

      {/* ── 작업 캔버스 ── */}
      <aside className="lg:sticky lg:top-2 lg:self-start">
        {hasResult ? (
          <ResultPanel
            components={components}
            harness={harness}
            committed={committed}
            onCommit={() => commitMut.mutate()}
            onTest={() => testMut.mutate()}
            committing={commitMut.isPending}
            testing={testMut.isPending}
            keySet={keySet}
          />
        ) : showRecs ? (
          <Card>
            <h3 className="text-sm font-semibold text-fg">카탈로그 조회</h3>
            <p className="mt-0.5 text-xs text-muted">
              재사용할 기존 구성요소와, 카탈로그에 <b className="text-fg">없는 능력(공백)</b>을 함께 보여줍니다.
            </p>
            {recs && recs.length > 0 && (
              <div className="mt-3 space-y-2">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted">재사용 후보</div>
                {recs.map((r) => (
                  <RecommendationCard key={r.id} r={r} />
                ))}
              </div>
            )}
            {gaps && gaps.length > 0 && (
              <div className="mt-3 space-y-2">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted">
                  카탈로그 공백 — 새로 만들 후보
                </div>
                {gaps.map((g) => (
                  <GapCard key={g.capability} g={g} />
                ))}
              </div>
            )}
          </Card>
        ) : (
          <Card>
            <h3 className="text-sm font-semibold text-fg">작업 캔버스</h3>
            <p className="mt-2 text-xs text-muted">
              대화하면 여기에 <b className="text-fg">구성요소 초안들</b>이 쌓이고, 필요하면 하나의{" "}
              <b className="text-fg">에이전트</b>로 조립됩니다. 타입은 자동으로 분류됩니다.
            </p>
          </Card>
        )}
      </aside>
    </div>
  );
}

function previewText(comp: AuthoredComponent): string | null {
  if (comp.type === "mcp") {
    const m = comp.mcp;
    if (!m) return null;
    if (m.url) return `${m.transport}  ${m.url}`;
    const env = Object.keys(m.env ?? {});
    return [`${m.command ?? ""} ${(m.args ?? []).join(" ")}`.trim(), env.length ? `env: ${env.join(", ")}` : ""]
      .filter(Boolean)
      .join("\n");
  }
  if (comp.type === "hook") return comp.emit_command || null;
  return comp.body || null;
}

function MessageBubble({ m }: { m: StudioMessage }) {
  if (m.role === "user") {
    return (
      <div className="ml-auto max-w-[80%] whitespace-pre-wrap rounded-2xl bg-surface-2 px-3.5 py-2 text-sm text-fg/90">
        {m.content}
      </div>
    );
  }
  if (m.meta?.kind === "commit" || m.meta?.kind === "test") {
    const icon = m.meta.kind === "commit" ? "✓" : "🧪";
    return (
      <div className="max-w-[85%] rounded-xl border border-ok/40 bg-ok/5 px-3 py-2 text-xs text-ok">
        <span className="mr-1">{icon}</span>
        {m.content}
      </div>
    );
  }
  const comps = m.meta?.components ?? [];
  return (
    <div className="max-w-[85%]">
      <div className="whitespace-pre-wrap rounded-2xl border border-line bg-surface px-3.5 py-2 text-sm text-fg/90">
        {m.content}
      </div>
      {(comps.length > 0 || m.meta?.harness) && (
        <div className="mt-1 flex flex-wrap items-center gap-1 pl-1">
          {comps.map((c, i) => (
            <Chip key={i} className={TYPE_COLOR[c.type as ComponentType] ?? "bg-surface-2 text-muted"}>
              {TYPE_LABEL[c.type as ComponentType] ?? c.type}
            </Chip>
          ))}
          {m.meta?.harness && <Chip className="bg-accent/15 text-accent">🧩 {m.meta.harness}</Chip>}
        </div>
      )}
    </div>
  );
}

function LiveBubble({ live }: { live: LiveTurn }) {
  return (
    <>
      <div className="ml-auto max-w-[80%] whitespace-pre-wrap rounded-2xl bg-surface-2 px-3.5 py-2 text-sm text-fg/90">
        {live.userText}
      </div>
      <div className="max-w-[85%]">
        {!live.prose ? (
          <div className="flex items-center gap-2 rounded-2xl border border-line bg-surface px-3.5 py-2 text-sm text-muted">
            <Spinner /> {live.phase}
          </div>
        ) : (
          <div className="whitespace-pre-wrap rounded-2xl border border-line bg-surface px-3.5 py-2 text-sm text-fg/90">
            {live.prose}
            <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-fg/40 align-middle" />
          </div>
        )}
      </div>
    </>
  );
}

function ResultPanel({
  components,
  harness,
  committed,
  onCommit,
  onTest,
  committing,
  testing,
  keySet,
}: {
  components: AuthoredComponent[];
  harness: StudioHarness | null;
  committed: boolean;
  onCommit: () => void;
  onTest: () => void;
  committing: boolean;
  testing: boolean;
  keySet: boolean;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-fg">구성요소 {components.length}개</h3>
        {committed && <Badge className="bg-ok/15 text-ok">저장됨</Badge>}
      </div>

      <div className="mt-3 space-y-2">
        {components.map((c) => (
          <ComponentDraftCard key={c.id} comp={c} />
        ))}
      </div>

      {harness && (
        <div className="mt-3 rounded-lg border border-accent/40 bg-accent/5 p-2.5">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-semibold text-fg">🧩 {harness.name}</span>
            <Chip className="bg-accent/15 text-accent">에이전트</Chip>
          </div>
          <p className="mt-0.5 text-xs text-muted">
            {(harness.component_ids?.length ?? components.length)}개 구성요소를 묶은 harness.yaml
          </p>
          {harness.errors && harness.errors.length > 0 && (
            <div className="mt-2 rounded-md border border-err/40 bg-err/10 p-2 text-[11px] text-err">
              검증 에러: {harness.errors.join("; ")}
            </div>
          )}
          {harness.gaps && harness.gaps.length > 0 && (
            <div className="mt-2 rounded-md border border-warn/40 bg-warn/10 p-2 text-[11px] text-warn">
              ⚠️ 미충족 능력(gap): {harness.gaps.join(", ")} — 이 능력을 제공하는 <b>실존 MCP</b>를 추가해야 실제로
              동작합니다(지어내지 않음).
            </div>
          )}
          <pre className={`mt-2 max-h-48 ${codeBlock}`}>{harness.yaml}</pre>
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <Button size="sm" onClick={onCommit} disabled={committing} className="flex-1">
          {committed ? "다시 저장" : harness ? "에이전트 저장" : "모두 저장"}
        </Button>
        {committed && (
          <Button
            size="sm"
            variant="subtle"
            onClick={onTest}
            disabled={testing || !keySet}
            title={!keySet ? "LLM 키를 먼저 등록하세요" : "저장된 구성요소를 적합성·안전 테스트"}
          >
            전체 테스트
          </Button>
        )}
      </div>
      <p className="mt-1.5 text-[11px] text-muted">
        저장하면 각 구성요소는 카탈로그에, 에이전트는 하네스 저장소에 들어갑니다. 테스트를 통과하면 사용가능(ready)이 됩니다.
      </p>
    </Card>
  );
}

function ComponentDraftCard({ comp }: { comp: AuthoredComponent }) {
  const preview = previewText(comp);
  return (
    <div className="rounded-lg border border-line p-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-fg">{comp.name}</span>
        <Chip className={TYPE_COLOR[comp.type]}>{TYPE_LABEL[comp.type]}</Chip>
      </div>
      <p className="mt-1 text-xs text-muted">{comp.summary}</p>
      {comp.provides.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {comp.provides.map((c) => (
            <Badge key={c} className="bg-ok/15 text-ok">
              {capLabel(c)}
            </Badge>
          ))}
        </div>
      )}
      {preview && <pre className={`mt-2 max-h-32 ${codeBlock}`}>{preview}</pre>}
    </div>
  );
}

function RecommendationCard({ r }: { r: Recommendation }) {
  return (
    <div className="rounded-lg border border-line p-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-fg">{r.name}</span>
        <Chip className={TYPE_COLOR[r.type]}>{TYPE_LABEL[r.type]}</Chip>
      </div>
      <p className="mt-1 text-xs text-muted">{r.summary}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <Badge className="bg-surface-2 text-muted">일치도 {r.score.toFixed(2)}</Badge>
        {r.matched_capabilities.slice(0, 3).map((c) => (
          <Badge key={c} className="bg-ok/15 text-ok">
            {capLabel(c)}
          </Badge>
        ))}
      </div>
      {r.reason && <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{r.reason}</p>}
    </div>
  );
}

/** 카탈로그가 못 채운 요구 능력 — 추천 카드와 동등한 비중으로 렌더(발명 대신 정직한 결핍). */
function GapCard({ g }: { g: CapabilityGap }) {
  return (
    <div className="rounded-lg border border-dashed border-warn/50 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-fg">{capLabel(g.capability)}</span>
        <Chip className={TYPE_COLOR[g.suggested_type]}>{TYPE_LABEL[g.suggested_type]} 필요</Chip>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <Badge className="bg-warn/15 text-warn">카탈로그 공백</Badge>
        <Badge className="bg-surface-2 text-muted">{g.capability}</Badge>
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{g.reason}</p>
    </div>
  );
}

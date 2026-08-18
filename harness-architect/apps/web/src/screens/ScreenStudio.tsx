import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  api,
  streamStudioChat,
  subscribeConversationEvents,
  type AuthoredComponent,
  type ComponentType,
  type Recommendation,
  type StudioConversation,
  type StudioConversationSummary,
  type StudioMessage,
} from "../api/client";
import { capLabel, TYPE_MEANING } from "../lib/catalog";
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

const TYPES: ComponentType[] = ["context", "skill", "mcp", "hook"];

// 진행 중인 한 턴(스트리밍) — 서버 영속 메시지와 별개로 라이브 렌더.
interface LiveTurn {
  userText: string;
  phase: string; // status 라벨(분류/검색/저작…)
  intent?: string;
  type?: string | null;
  rationale?: string;
  prose: string; // 누적 토큰
  recommendations?: Recommendation[];
  reused?: boolean;
  draft?: AuthoredComponent;
}

function scopeQuery(fullScope: string): string {
  return fullScope.startsWith("team:") ? fullScope : "personal";
}

/** 조건에 맞는 마지막 메시지의 meta 를 찾는다(캔버스가 '현재 산출물'을 잡을 때). */
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
  const [overrideType, setOverrideType] = useState<ComponentType | "">("");
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

  // 사이드바 실시간 갱신(생성/삭제/제목/최신순). 진행 중 턴 중엔 상세는 done 후 직접 무효화한다.
  useEffect(() => subscribeConversationEvents(() => qc.invalidateQueries({ queryKey: ["studio-convs"] })), [qc]);

  // 첫 로드 시 최신 대화 자동 선택.
  useEffect(() => {
    if (!active && convs.length) setActive({ id: convs[0].id, scope: scopeQuery(convs[0].scope) });
  }, [convs, active]);

  // 대화 전환 시 오버라이드 초기화 + 스크롤 하단.
  useEffect(() => setOverrideType(""), [active?.id]);
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
    mutationFn: () => api.commitConversation(active!.id, active!.scope, { type: overrideType || null }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["studio-conv", active!.id] });
      qc.invalidateQueries({ queryKey: ["components"] });
      qc.invalidateQueries({ queryKey: ["studio-convs"] });
      if (r.component.validation.ok) toast(`저장·검증 완료: ${r.component.name}`, "success");
      else toast(`저장(초안) — ${r.component.validation.errors[0] ?? "검증 필요"}`, "error");
    },
    onError: (e: Error) => toast(e.message || "저장 실패", "error"),
  });

  const testMut = useMutation({
    mutationFn: () => api.testConversation(active!.id, active!.scope),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["studio-conv", active!.id] });
      qc.invalidateQueries({ queryKey: ["components"] });
      if (r.result.skipped) toast("테스트 건너뜀", "info");
      else if (r.result.pass) toast("테스트 통과 — 사용가능(ready)", "success");
      else toast(`테스트 보류: ${r.result.reasons[0] ?? ""}`, "error");
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
    const forced = overrideType || null;
    setLive({ userText: text, phase: "전송 중…", prose: "" });
    try {
      await streamStudioChat(a.id, a.scope, text, forced, (ev) => {
        setLive((prev) => {
          if (!prev) return prev;
          switch (ev.event) {
            case "status":
              return { ...prev, phase: ev.data.label };
            case "router":
              return { ...prev, intent: ev.data.intent, type: ev.data.type, rationale: ev.data.rationale };
            case "recommendations":
              return { ...prev, recommendations: ev.data.items, reused: ev.data.reused };
            case "draft":
              return { ...prev, draft: ev.data.component, type: ev.data.type };
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
      setOverrideType("");
    }
  }

  const messages = conv?.messages ?? [];
  const draft = live?.draft ?? conv?.draft_component ?? null;
  const recs = live?.recommendations ?? lastMeta(conv, (m) => m.meta?.recommendations) ?? null;
  const showRecs = !draft && !!recs && recs.length > 0;
  const committed = !!conv?.component_id;
  const draftType = (draft?.type as ComponentType | undefined) ?? undefined;
  const rationale = live?.rationale ?? lastMeta(conv, (m) => m.meta?.rationale) ?? "";

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr_360px]">
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
          subtitle="채팅으로 카탈로그를 만들어요 — 타입은 자동 분류하고, 이미 있으면 추천합니다."
        />

        <div className="flex-1 space-y-3 overflow-y-auto pr-1">
          {!active || messages.length === 0 ? (
            <EmptyState
              title="무엇을 만들까요?"
              hint={'예: "PR 올라오면 슬랙으로 알림 보내는 훅" · "우리 팀 파이썬 컨벤션을 항상 지키게" · "GitHub 이슈에 접근하는 도구 있어?"'}
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

        {/* 퀵칩 */}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {[
            { label: "추천만", text: "이미 비슷한 게 있으면 추천만 해줘: " },
            { label: "새로 만들기", text: "새로 만들어줘: " },
          ].map((q) => (
            <button
              key={q.label}
              className="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted hover:text-fg"
              onClick={() => setInput((v) => q.text + v.replace(/^(이미 비슷한 게 있으면 추천만 해줘: |새로 만들어줘: )/, ""))}
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
        {draft ? (
          <DraftPanel
            draft={draft}
            draftType={draftType}
            rationale={rationale}
            overrideType={overrideType}
            setOverrideType={setOverrideType}
            committed={committed}
            onCommit={() => commitMut.mutate()}
            onTest={() => testMut.mutate()}
            committing={commitMut.isPending}
            testing={testMut.isPending}
            keySet={keySet}
          />
        ) : showRecs ? (
          <Card>
            <h3 className="text-sm font-semibold text-fg">이미 있는 구성요소</h3>
            <p className="mt-0.5 text-xs text-muted">새로 만들기 전에 재사용을 확인하세요.</p>
            <div className="mt-3 space-y-2">
              {recs!.map((r) => (
                <RecommendationCard key={r.id} r={r} />
              ))}
            </div>
          </Card>
        ) : (
          <Card>
            <h3 className="text-sm font-semibold text-fg">작업 캔버스</h3>
            <p className="mt-2 text-xs text-muted">
              대화하면 여기에 <b className="text-fg">초안</b>이나 <b className="text-fg">추천</b>이 실시간으로 나타나요.
              타입(Context·Skill·MCP·Hook)은 자동으로 분류됩니다.
            </p>
          </Card>
        )}
      </aside>
    </div>
  );
}

/** 타입별 미리보기 텍스트 — context/skill=본문, mcp=실행 스펙, hook=명령. */
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
  // 커밋/테스트 인라인 시스템 노트
  if (m.meta?.kind === "commit" || m.meta?.kind === "test") {
    const icon = m.meta.kind === "commit" ? "✓" : "🧪";
    const ok = m.meta.kind === "commit" ? m.meta.validation?.ok : m.meta.result?.pass;
    return (
      <div className={`max-w-[85%] rounded-xl border px-3 py-2 text-xs ${ok ? "border-ok/40 bg-ok/5 text-ok" : "border-line bg-surface-2 text-muted"}`}>
        <span className="mr-1">{icon}</span>
        {m.content}
      </div>
    );
  }
  const t = m.meta?.type as ComponentType | undefined;
  return (
    <div className="max-w-[85%]">
      <div className="whitespace-pre-wrap rounded-2xl border border-line bg-surface px-3.5 py-2 text-sm text-fg/90">
        {m.content}
      </div>
      {t && (m.meta?.intent === "author" || m.meta?.intent === "refine") && (
        <div className="mt-1 flex items-center gap-1.5 pl-1">
          <Chip className={TYPE_COLOR[t]}>{TYPE_LABEL[t]} 자동분류</Chip>
          {m.meta?.rationale && <span className="text-[11px] text-muted">· {m.meta.rationale}</span>}
        </div>
      )}
    </div>
  );
}

function LiveBubble({ live }: { live: LiveTurn }) {
  const t = live.type as ComponentType | undefined;
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
        {t && (live.intent === "author" || live.intent === "refine") && (
          <div className="mt-1 flex items-center gap-1.5 pl-1">
            <Chip className={TYPE_COLOR[t]}>{TYPE_LABEL[t]} 자동분류</Chip>
          </div>
        )}
      </div>
    </>
  );
}

function DraftPanel({
  draft,
  draftType,
  rationale,
  overrideType,
  setOverrideType,
  committed,
  onCommit,
  onTest,
  committing,
  testing,
  keySet,
}: {
  draft: AuthoredComponent;
  draftType: ComponentType | undefined;
  rationale: string;
  overrideType: ComponentType | "";
  setOverrideType: (t: ComponentType | "") => void;
  committed: boolean;
  onCommit: () => void;
  onTest: () => void;
  committing: boolean;
  testing: boolean;
  keySet: boolean;
}) {
  const preview = previewText(draft);
  const effType = overrideType || draftType || draft.type;
  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-fg">{draft.name}</span>
        {committed && <Badge className="bg-ok/15 text-ok">저장됨</Badge>}
      </div>
      <p className="mt-1 text-xs text-muted">{draft.summary}</p>

      {/* 자동 분류 타입 + 근거 + 오버라이드(탈출구) */}
      <div className="mt-3 rounded-lg border border-line bg-surface-2 p-2.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <Chip className={TYPE_COLOR[effType]}>{TYPE_LABEL[effType]}</Chip>
            <span className="text-xs text-muted">{overrideType ? "직접 지정" : "자동 분류"}</span>
          </div>
          <select
            className="h-7 rounded-md border border-line bg-surface px-2 text-xs text-fg focus:border-accent/60 focus:outline-none"
            value={overrideType || draft.type}
            onChange={(e) => setOverrideType(e.target.value === draft.type ? "" : (e.target.value as ComponentType))}
            title="자동 분류가 틀리면 직접 바꾸세요"
          >
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABEL[t]}
              </option>
            ))}
          </select>
        </div>
        <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
          {rationale || TYPE_MEANING[effType].blurb}
        </p>
      </div>

      {draft.provides.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {draft.provides.map((c) => (
            <Badge key={c} className="bg-ok/15 text-ok">
              {capLabel(c)}
            </Badge>
          ))}
        </div>
      )}
      {draft.type === "hook" && (draft.events?.length ?? 0) > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {(draft.events ?? []).map((e) => (
            <Badge key={e} className="bg-surface-2 text-muted">
              {e}
            </Badge>
          ))}
        </div>
      )}
      {preview && <pre className={`mt-2 max-h-56 ${codeBlock}`}>{preview}</pre>}

      <div className="mt-3 flex gap-2">
        <Button size="sm" onClick={onCommit} disabled={committing} className="flex-1">
          {committed ? "다시 저장" : "이 구성요소 저장"}
        </Button>
        {committed && (
          <Button
            size="sm"
            variant="subtle"
            onClick={onTest}
            disabled={testing || !keySet}
            title={!keySet ? "LLM 키를 먼저 등록하세요" : "적합성·안전 테스트(통과 시 사용가능)"}
          >
            테스트
          </Button>
        )}
      </div>
      <p className="mt-1.5 text-[11px] text-muted">저장하면 검증하고, 테스트를 통과하면 생성 위저드에서 쓸 수 있어요.</p>
    </Card>
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

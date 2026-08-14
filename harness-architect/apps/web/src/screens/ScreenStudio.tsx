import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  api,
  subscribeComponentEvents,
  type AuthoredComponent,
  type ComponentStatus,
  type ComponentSummary,
  type ComponentType,
} from "../api/client";
import { capLabel } from "../lib/catalog";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, Chip, codeBlock, EmptyState, PageHeader, Spinner, Textarea, TYPE_COLOR, TYPE_LABEL } from "../lib/ui";

type ChatMsg = { role: "user"; text: string } | { role: "assistant"; component: AuthoredComponent };

const STATUS_META: Record<ComponentStatus, { label: string; cls: string }> = {
  draft: { label: "초안", cls: "bg-surface-2 text-muted" },
  valid: { label: "검증됨", cls: "bg-sky-500/15 text-sky-400" },
  ready: { label: "사용가능", cls: "bg-ok/15 text-ok" },
};

// 타입별 한 줄 안내(빌더 상단) + 예시 프롬프트.
const TYPE_HINT: Record<ComponentType, { blurb: string; example: string }> = {
  context: { blurb: "시스템 프롬프트에 항상 주입될 배경지식·규칙", example: "팀 파이썬 코딩 컨벤션(타입힌트 필수, 함수는 짧게)을 항상 지키게" },
  skill: { blurb: "에이전트가 따를 작업 절차(접근은 MCP에 위임)", example: "PR diff를 정확성·가독성·컨벤션 순으로 리뷰하는 절차" },
  mcp: { blurb: "실존하는 MCP 서버의 카탈로그 항목(실행 스펙 기술)", example: "npx @modelcontextprotocol/server-github 로 GitHub 저장소·이슈·PR 접근" },
  hook: { blurb: "요청 전후 자동 실행되는 검사·차단 스펙", example: "도구 호출 전에 비밀키·PII 노출을 스캔해 차단" },
};

const TYPES: ComponentType[] = ["context", "skill", "mcp", "hook"];

function scopeQuery(fullScope: string): string {
  return fullScope.startsWith("team:") ? fullScope : "personal";
}

export default function ScreenStudio({ workspace }: { workspace: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [type, setType] = useState<ComponentType>("context");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");

  useEffect(() => subscribeComponentEvents(() => qc.invalidateQueries({ queryKey: ["components"] })), [qc]);

  const listQ = useQuery({ queryKey: ["components"], queryFn: () => api.listComponents() });
  const items = listQ.data ?? [];
  const llmQ = useQuery({ queryKey: ["llm-settings"], queryFn: api.getLlmSettings });
  const keySet = llmQ.data?.llm.set ?? false;

  const authorMut = useMutation({
    mutationFn: (prompt: string) => api.authorComponent(prompt, type),
    onSuccess: (res, prompt) => {
      setMessages((m) => [...m, { role: "user", text: prompt }, { role: "assistant", component: res.component }]);
      setInput("");
    },
    onError: (e: Error) => toast(e.message || "생성 실패", "error"),
  });

  const saveMut = useMutation({
    mutationFn: (comp: AuthoredComponent) =>
      api.putComponent(comp.id, workspace, { name: comp.name, description: comp.summary, data: comp }),
    onSuccess: (doc) => {
      qc.invalidateQueries({ queryKey: ["components"] });
      if (doc.validation.ok) toast(`저장·검증 완료: ${doc.name}`, "success");
      else toast(`저장(초안) — ${doc.validation.errors[0] ?? "검증 실패"}`, "error");
    },
    onError: (e: Error) => toast(e.message || "저장 실패", "error"),
  });

  const testMut = useMutation({
    mutationFn: (item: ComponentSummary) => api.testComponent(item.id, scopeQuery(item.scope)),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["components"] });
      if (res.result.skipped) toast("테스트 건너뜀", "info");
      else if (res.result.pass) toast("테스트 통과 — 사용가능", "success");
      else toast(`테스트 실패: ${res.result.reasons[0] ?? ""}`, "error");
    },
    onError: (e: Error) => toast(e.message || "테스트 실패", "error"),
  });

  const delMut = useMutation({
    mutationFn: (item: ComponentSummary) => api.deleteComponent(item.id, scopeQuery(item.scope)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["components"] });
      toast("삭제됨", "success");
    },
    onError: (e: Error) => toast(e.message || "삭제 실패", "error"),
  });

  function submit() {
    const p = input.trim();
    if (p && !authorMut.isPending && keySet) authorMut.mutate(p);
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_360px]">
      <div className="flex min-h-[60vh] flex-col">
        <PageHeader title="카탈로그 빌더" subtitle="타입을 고르고 설명하면 구성요소를 만들어 검증·테스트합니다." />

        {/* 타입 선택 — 빌더의 기본 축 */}
        <div className="mb-1 flex gap-1.5">
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setType(t)}
              className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
                type === t ? "border-accent bg-accent/10 text-fg" : "border-line text-muted hover:text-fg"
              }`}
            >
              {TYPE_LABEL[t]}
            </button>
          ))}
        </div>
        <p className="mb-3 text-xs text-muted">{TYPE_HINT[type].blurb}</p>

        <div className="flex-1 space-y-3">
          {messages.length === 0 && (
            <EmptyState title={`${TYPE_LABEL[type]} 만들기`} hint={`예: "${TYPE_HINT[type].example}"`} />
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="ml-auto max-w-[80%] rounded-md bg-surface-2 px-3 py-2 text-sm text-fg/90">
                {m.text}
              </div>
            ) : (
              <GeneratedCard
                key={i}
                comp={m.component}
                onSave={() => saveMut.mutate(m.component)}
                saving={saveMut.isPending}
              />
            ),
          )}
          {authorMut.isPending && (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Spinner /> 생성 중…
            </div>
          )}
        </div>

        {!keySet && (
          <div className="mt-3 rounded-md border border-warn/40 bg-warn/5 p-2.5 text-xs text-warn">
            LLM 키가 없어 생성·테스트가 잠겨 있어요 — 설정 → LLM 키에서 등록하세요.
          </div>
        )}
        <div className="mt-2 flex items-end gap-2">
          <Textarea
            className="min-h-[52px]"
            placeholder={`만들 ${TYPE_LABEL[type]}을(를) 설명하세요 (Enter 전송 · Shift+Enter 줄바꿈)`}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <Button onClick={submit} disabled={authorMut.isPending || !input.trim() || !keySet}>
            생성
          </Button>
        </div>
      </div>

      {/* 내 구성요소 */}
      <aside className="lg:sticky lg:top-2 lg:self-start">
        <Card>
          <h3 className="text-sm font-semibold text-fg">내 구성요소</h3>
          <p className="mt-0.5 text-xs text-muted">검증·테스트를 통과(사용가능)하면 생성 위저드에서 씁니다.</p>
          <div className="mt-3 space-y-2">
            {items.length === 0 && <p className="text-xs text-muted">아직 저장한 구성요소가 없습니다.</p>}
            {items.map((it) => (
              <div key={`${it.scope}/${it.id}`} className="rounded-md border border-line p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-fg">{it.name}</span>
                  <Badge className={STATUS_META[it.status].cls}>{STATUS_META[it.status].label}</Badge>
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-xs text-muted">
                  <Chip className={TYPE_COLOR[it.type]}>{TYPE_LABEL[it.type]}</Chip>
                  <span>{it.scope.startsWith("team:") ? "팀" : "개인"}</span>
                  <span>· v{it.version}</span>
                </div>
                <div className="mt-2 flex gap-1.5">
                  <Button
                    size="sm"
                    variant="subtle"
                    disabled={it.status !== "valid" || testMut.isPending || !keySet}
                    onClick={() => testMut.mutate(it)}
                    title={!keySet ? "LLM 키를 먼저 등록하세요" : it.status === "draft" ? "검증을 먼저 통과해야 합니다" : it.status === "ready" ? "이미 사용가능" : "적합성·안전 테스트"}
                  >
                    테스트
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => delMut.mutate(it)}>
                    삭제
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
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

function GeneratedCard({ comp, onSave, saving }: { comp: AuthoredComponent; onSave: () => void; saving: boolean }) {
  const preview = previewText(comp);
  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-fg">{comp.name}</span>
        <Chip className={TYPE_COLOR[comp.type]}>{TYPE_LABEL[comp.type]}</Chip>
      </div>
      <p className="mt-1 text-xs text-muted">{comp.summary}</p>
      {(comp.provides.length > 0 || (comp.type === "hook" && (comp.events?.length ?? 0) > 0)) && (
        <div className="mt-2 flex flex-wrap gap-1">
          {comp.provides.map((c) => (
            <Badge key={c} className="bg-ok/15 text-ok">
              {capLabel(c)}
            </Badge>
          ))}
          {comp.type === "hook" &&
            (comp.events ?? []).map((e) => (
              <Badge key={e} className="bg-surface-2 text-muted">
                {e}
              </Badge>
            ))}
        </div>
      )}
      {preview && <pre className={`mt-2 max-h-56 ${codeBlock}`}>{preview}</pre>}
      <div className="mt-3 flex justify-end">
        <Button size="sm" onClick={onSave} disabled={saving}>
          저장
        </Button>
      </div>
    </Card>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  api,
  subscribeComponentEvents,
  type AuthoredComponent,
  type ComponentStatus,
  type ComponentSummary,
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

/** 전체 스코프 키(personal:<uid> / team:<tid>) → API 쿼리 scope 값. */
function scopeQuery(fullScope: string): string {
  return fullScope.startsWith("team:") ? fullScope : "personal";
}

export default function ScreenStudio({ workspace }: { workspace: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");

  // 컴포넌트 변경(가시 스코프)을 SSE 로 구독 → 목록 실시간 갱신.
  useEffect(() => subscribeComponentEvents(() => qc.invalidateQueries({ queryKey: ["components"] })), [qc]);

  const listQ = useQuery({ queryKey: ["components"], queryFn: () => api.listComponents() });
  const items = listQ.data ?? [];
  const llmQ = useQuery({ queryKey: ["llm-settings"], queryFn: api.getLlmSettings });
  const keySet = llmQ.data?.llm.set ?? false; // LLM 키 없으면 생성·테스트 잠금

  const authorMut = useMutation({
    mutationFn: (prompt: string) => api.authorComponent(prompt),
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
      else toast(`저장(초안) — 검증 실패: ${doc.validation.errors[0] ?? ""}`, "error");
    },
    onError: (e: Error) => toast(e.message || "저장 실패", "error"),
  });

  const testMut = useMutation({
    mutationFn: (item: ComponentSummary) => api.testComponent(item.id, scopeQuery(item.scope)),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["components"] });
      if (res.result.skipped) toast("테스트 건너뜀", "info");
      else if (res.result.pass) toast("테스트 통과 — 사용가능(ready)", "success");
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
      {/* 좌: 채팅 저작 */}
      <div className="flex min-h-[60vh] flex-col">
        <PageHeader
          title="구성요소 스튜디오"
          subtitle="자연어로 context 구성요소를 만들고, 검증·테스트를 거쳐 사용하세요."
        />
        <div className="flex-1 space-y-3">
          {messages.length === 0 && (
            <EmptyState
              title="무엇을 만들까요?"
              hint="예: '팀 파이썬 코딩 컨벤션(타입힌트 필수, 함수는 짧게)을 항상 지키게 하는 컨텍스트를 만들어줘'"
            />
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="ml-auto max-w-[80%] rounded-xl bg-accent/10 px-3 py-2 text-sm text-fg">
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
          <div className="mt-3 rounded-lg border border-warn/40 bg-warn/5 p-2.5 text-xs text-warn">
            LLM 키가 없어 생성·테스트가 잠겨 있어요 — <b>설정 → ① LLM 키</b>에서 등록하세요.
          </div>
        )}
        <div className="mt-2 flex items-end gap-2">
          <Textarea
            className="min-h-[52px]"
            placeholder="만들고 싶은 구성요소를 설명하세요… (Enter 전송 · Shift+Enter 줄바꿈)"
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

      {/* 우: 내 구성요소 */}
      <aside className="lg:sticky lg:top-2 lg:self-start">
        <Card>
          <h3 className="text-sm font-semibold text-fg">내 구성요소</h3>
          <p className="mt-0.5 text-xs text-muted">검증→테스트를 통과(사용가능)하면 생성 위저드에서 쓸 수 있어요.</p>
          <div className="mt-3 space-y-2">
            {items.length === 0 && <p className="text-xs text-muted">아직 저장한 구성요소가 없습니다.</p>}
            {items.map((it) => (
              <div key={`${it.scope}/${it.id}`} className="rounded-lg border border-line p-2.5">
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
                    title={!keySet ? "LLM 키를 먼저 등록하세요" : it.status === "draft" ? "검증을 먼저 통과해야 테스트할 수 있어요" : it.status === "ready" ? "이미 사용가능" : "적합성·안전 테스트"}
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

function GeneratedCard({ comp, onSave, saving }: { comp: AuthoredComponent; onSave: () => void; saving: boolean }) {
  return (
    <Card className="max-w-[85%]">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-fg">{comp.name}</span>
        <Chip className={TYPE_COLOR[comp.type]}>{TYPE_LABEL[comp.type]}</Chip>
      </div>
      <p className="mt-1 text-xs text-muted">{comp.summary}</p>
      {comp.provides.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {comp.provides.map((c) => (
            <Badge key={c} className="bg-ok/15 text-ok">
              {capLabel(c)}
            </Badge>
          ))}
        </div>
      )}
      {comp.body && <pre className={`mt-2 max-h-56 ${codeBlock}`}>{comp.body}</pre>}
      <div className="mt-3 flex justify-end">
        <Button size="sm" onClick={onSave} disabled={saving}>
          저장
        </Button>
      </div>
    </Card>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type PolicyDoc } from "../api/client";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, Input, Spinner } from "../lib/ui";

/**
 * 조직 정책 편집 (Phase 8) — 팀 가드레일을 화면에서 정한다.
 *
 * **저장하면 서버가 항상 적용한다.** 그 전에는 정책이 요청 본문에서만 와서, 클라이언트가 그냥
 * 안 보내면 아무 강제도 없었다(= 정책이 없는 것과 같다). 저장된 정책은 클라이언트가 낮출 수
 * 없고 더 엄격해질 때만 합쳐진다.
 *
 * 팀은 owner 만 바꿀 수 있다 — editor 가 가드레일을 풀 수 있으면 가드레일이 아니다(서버가 403).
 */

/** 쉼표·줄바꿈 구분 입력 → 문자열 배열(빈 항목 제거). 정책은 읽고 감사할 수 있어야 하므로 단순하게. */
function parseList(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function toText(items: string[] | undefined): string {
  return (items ?? []).join(", ");
}

/** 빈 문자열은 "제약 없음"(null)이다 — 0 으로 보내면 전부 차단된다. */
function parseLimit(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

export function PolicyEditor({ scope, canEdit }: { scope: string; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["policy", scope], queryFn: () => api.getPolicy(scope) });

  const [requireCaps, setRequireCaps] = useState("");
  const [requireComps, setRequireComps] = useState("");
  const [forbidComps, setForbidComps] = useState("");
  const [forbidCaps, setForbidCaps] = useState("");
  const [noUnsandboxed, setNoUnsandboxed] = useState(false);
  const [maxTokens, setMaxTokens] = useState("");
  const [maxTools, setMaxTools] = useState("");
  const [requireNarrowed, setRequireNarrowed] = useState(false);

  // 서버 값이 오면 폼을 채운다(로컬 편집 중 덮어쓰지 않도록 정책 문서 변화에만 반응).
  const doc = q.data?.policy ?? null;
  useEffect(() => {
    setRequireCaps(toText(doc?.require?.capabilities));
    setRequireComps(toText(doc?.require?.components));
    setForbidComps(toText(doc?.forbid?.components));
    setForbidCaps(toText(doc?.forbid?.capabilities));
    setNoUnsandboxed(Boolean(doc?.forbid?.unsandboxed_hooks));
    setMaxTokens(doc?.budget?.context_tokens != null ? String(doc.budget.context_tokens) : "");
    setMaxTools(doc?.budget?.added_tools != null ? String(doc.budget.added_tools) : "");
    setRequireNarrowed(Boolean(doc?.auth?.require_narrowed));
  }, [doc]);

  const build = (): PolicyDoc => ({
    version: 1,
    require: { capabilities: parseList(requireCaps), components: parseList(requireComps) },
    forbid: {
      components: parseList(forbidComps),
      capabilities: parseList(forbidCaps),
      unsandboxed_hooks: noUnsandboxed,
    },
    budget: { context_tokens: parseLimit(maxTokens), added_tools: parseLimit(maxTools) },
    auth: { allowed_scopes: null, require_narrowed: requireNarrowed },
  });

  const save = useMutation({
    mutationFn: () => api.putPolicy(scope, build()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policy", scope] });
      toast("정책을 저장했습니다 — 이 워크스페이스의 검증·실행에 즉시 적용됩니다", "success");
    },
    onError: (e: Error) => toast(e.message || "저장에 실패했습니다", "error"),
  });

  const remove = useMutation({
    mutationFn: () => api.deletePolicy(scope),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policy", scope] });
      toast("정책을 해제했습니다", "success");
    },
    onError: (e: Error) => toast(e.message || "해제에 실패했습니다", "error"),
  });

  if (q.isLoading) {
    return (
      <Card className="mt-3">
        <div className="flex justify-center py-3">
          <Spinner />
        </div>
      </Card>
    );
  }

  return (
    <Card className="mt-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-fg">조직 정책</div>
        {doc ? (
          <Badge className="bg-ok/15 text-ok">적용 중</Badge>
        ) : (
          <Badge className="bg-surface-2 text-muted">미설정</Badge>
        )}
      </div>
      <p className="mt-1 text-xs text-muted">
        저장하면 이 워크스페이스의 <b className="text-fg">모든 검증·실행 경로</b>에 서버가 항상 적용합니다.
        클라이언트가 낮출 수 없고, 더 엄격하게만 덮어쓸 수 있습니다.
      </p>
      {doc && q.data?.updated_at && (
        <p className="mt-0.5 text-[11px] text-muted">
          마지막 변경 {new Date(q.data.updated_at).toLocaleString("ko-KR")}
        </p>
      )}
      {!canEdit && (
        <p className="mt-1.5 text-xs text-warn">
          팀 정책은 owner 만 바꿀 수 있습니다 — editor 가 가드레일을 풀 수 있으면 가드레일이 아니기 때문입니다.
        </p>
      )}

      <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
        <Field label="필수 능력" hint="쉼표 구분 · 예: lifecycle.guardrail">
          <Input value={requireCaps} onChange={(e) => setRequireCaps(e.target.value)} disabled={!canEdit} />
        </Field>
        <Field label="필수 컴포넌트" hint="예: secret-scan-hook">
          <Input value={requireComps} onChange={(e) => setRequireComps(e.target.value)} disabled={!canEdit} />
        </Field>
        <Field label="금지 컴포넌트" hint="정확 일치 또는 접두 glob · 예: io.github.randomdev/*">
          <Input value={forbidComps} onChange={(e) => setForbidComps(e.target.value)} disabled={!canEdit} />
        </Field>
        <Field label="금지 능력" hint="예: web.browse">
          <Input value={forbidCaps} onChange={(e) => setForbidCaps(e.target.value)} disabled={!canEdit} />
        </Field>
        <Field label="컨텍스트 토큰 상한" hint="비우면 제약 없음">
          <Input value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} disabled={!canEdit} />
        </Field>
        <Field label="추가 도구 상한" hint="비우면 제약 없음">
          <Input value={maxTools} onChange={(e) => setMaxTools(e.target.value)} disabled={!canEdit} />
        </Field>
      </div>

      <div className="mt-2.5 space-y-1.5">
        <Toggle
          checked={noUnsandboxed}
          onChange={setNoUnsandboxed}
          disabled={!canEdit}
          label="격리 없는 훅 금지"
          hint="훅은 라이프사이클 시점에 임의 로직을 실행하므로 공급망 위험이 가장 큽니다."
        />
        <Toggle
          checked={requireNarrowed}
          onChange={setRequireNarrowed}
          disabled={!canEdit}
          label="인증 scope 축소 강제"
          hint="인증이 필요한 컴포넌트는 permissions 로 축소된 scope 를 반드시 선언해야 합니다."
        />
      </div>

      {canEdit && (
        <div className="mt-3 flex justify-end gap-2">
          {doc && (
            <Button variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
              {remove.isPending ? <Spinner /> : "정책 해제"}
            </Button>
          )}
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? <Spinner /> : "정책 저장"}
          </Button>
        </div>
      )}
    </Card>
  );
}

function Field({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-fg">{label}</span>
      <span className="mb-1 block text-[11px] text-muted">{hint}</span>
      {children}
    </label>
  );
}

function Toggle({
  checked,
  onChange,
  disabled,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled: boolean;
  label: string;
  hint: string;
}) {
  return (
    <label className="flex items-start gap-2">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5"
      />
      <span>
        <span className="block text-xs font-medium text-fg">{label}</span>
        <span className="block text-[11px] text-muted">{hint}</span>
      </span>
    </label>
  );
}

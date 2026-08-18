import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type ApiToken, type LlmProvider, type LlmSettingsInput, type LlmVerifyResult, type ProviderStatus } from "../api/client";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, EmptyState, Input, Modal, PageHeader } from "../lib/ui";

export default function ScreenSettings({ onLogout }: { onLogout: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const meQ = useQuery({ queryKey: ["me"], queryFn: api.me });
  const tokensQ = useQuery({ queryKey: ["tokens"], queryFn: api.listTokens });

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

      {/* LLM·임베딩 키 등록 (앱 레벨, 화면 등록) */}
      <LlmSettingsSection />

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

function LlmSettingsSection() {
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["llm-settings"], queryFn: api.getLlmSettings });
  const s = q.data;
  const [provider, setProvider] = useState<LlmProvider>("anthropic");
  const [llmKey, setLlmKey] = useState("");
  const [embKey, setEmbKey] = useState("");
  const [searchKey, setSearchKey] = useState("");
  const [initd, setInitd] = useState(false);

  useEffect(() => {
    if (s && !initd) {
      setProvider(s.provider);
      setInitd(true);
    }
  }, [s, initd]);

  const saveM = useMutation({
    mutationFn: (body: LlmSettingsInput) => api.putLlmSettings(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm-settings"] });
      setLlmKey("");
      setEmbKey("");
      setSearchKey("");
      toast("저장됨");
    },
    onError: (e: Error) => toast(e.message || "저장 실패", "error"),
  });

  const [verify, setVerify] = useState<LlmVerifyResult | null>(null);
  const verifyM = useMutation({
    mutationFn: () => api.verifyLlmSettings(),
    onSuccess: setVerify,
    onError: (e: Error) => toast(e.message || "연결 테스트 실패", "error"),
  });

  return (
    <div className="space-y-6">
      {/* ① LLM 키 */}
      <div>
        <h2 className="text-sm font-semibold text-fg">① LLM 키</h2>
        <p className="mb-3 mt-0.5 text-sm text-muted">
          스튜디오 <b className="text-fg">생성·테스트</b>에 쓰는 provider·키. 서버에서 <b className="text-fg">암호화 저장</b>·마스킹.{" "}
          <b className="text-fg">키가 없으면 LLM 기능이 잠깁니다.</b>
        </p>
        <Card className="space-y-4">
          <div>
            <div className="mb-1.5 text-xs font-medium text-muted">Provider</div>
            <div className="flex gap-1.5">
              {(["anthropic", "openai"] as LlmProvider[]).map((p) => (
                <button
                  key={p}
                  onClick={() => setProvider(p)}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                    provider === p ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted hover:text-fg"
                  }`}
                >
                  {p === "anthropic" ? "Claude (Anthropic)" : "OpenAI"}
                </button>
              ))}
            </div>
          </div>
          <KeyField
            label={`${provider === "anthropic" ? "Anthropic" : "OpenAI"} API 키`}
            current={s?.llm}
            value={llmKey}
            onChange={setLlmKey}
            onClear={() => saveM.mutate({ llm_key: "" })}
          />
          <div className="flex items-center justify-end gap-2">
            <VerifyBadge r={verify?.llm} />
            <Button
              variant="subtle"
              onClick={() => verifyM.mutate()}
              disabled={verifyM.isPending || !s?.llm.set}
              title={s?.llm.set ? "저장된 키로 최소 호출을 시도해 연동 확인" : "먼저 키를 저장하세요"}
            >
              {verifyM.isPending ? "확인 중…" : "연결 테스트"}
            </Button>
            <Button
              onClick={() => saveM.mutate({ provider, llm_key: llmKey.trim() ? llmKey.trim() : null })}
              disabled={saveM.isPending}
            >
              저장
            </Button>
          </div>
        </Card>
      </div>

      {/* ② 임베딩 키 */}
      <div>
        <h2 className="text-sm font-semibold text-fg">② 임베딩 키 (OpenAI)</h2>
        <p className="mb-3 mt-0.5 text-sm text-muted">
          카탈로그 의미 검색(추천)용 OpenAI 임베딩 키. 없으면 로컬(저품질) 폴백. <b className="text-fg">변경은 API 재시작 후 인덱스에 반영</b>됩니다.
        </p>
        <Card className="space-y-4">
          <KeyField
            label="OpenAI 임베딩 키"
            current={s?.embedding}
            value={embKey}
            onChange={setEmbKey}
            onClear={() => saveM.mutate({ embedding_key: "" })}
          />
          <div className="flex items-center justify-end gap-2">
            <VerifyBadge r={verify?.embedding} />
            <Button
              variant="subtle"
              onClick={() => verifyM.mutate()}
              disabled={verifyM.isPending || !s?.embedding.set}
              title={s?.embedding.set ? "저장된 키로 최소 호출을 시도해 연동 확인" : "먼저 키를 저장하세요"}
            >
              {verifyM.isPending ? "확인 중…" : "연결 테스트"}
            </Button>
            <Button
              onClick={() => saveM.mutate({ embedding_key: embKey.trim() ? embKey.trim() : null })}
              disabled={saveM.isPending}
            >
              저장
            </Button>
          </div>
        </Card>
      </div>

      {/* ③ 웹검색 키 */}
      <div>
        <h2 className="text-sm font-semibold text-fg">③ 웹검색 키 (Tavily)</h2>
        <p className="mb-3 mt-0.5 text-sm text-muted">
          스튜디오 에이전트가 <b className="text-fg">실존하는 도구·API·리소스</b>를 근거로 구성요소를 만들도록
          하는 웹검색 키(Tavily). 없으면 검색 없이 아는 선에서 만듭니다.{" "}
          <a href="https://tavily.com" target="_blank" rel="noreferrer" className="text-accent hover:underline">
            tavily.com
          </a>{" "}
          에서 발급.
        </p>
        <Card className="space-y-4">
          <KeyField
            label="Tavily API 키"
            current={s?.search}
            value={searchKey}
            onChange={setSearchKey}
            onClear={() => saveM.mutate({ search_key: "" })}
          />
          <div className="flex items-center justify-end gap-2">
            <VerifyBadge r={verify?.search} />
            <Button
              variant="subtle"
              onClick={() => verifyM.mutate()}
              disabled={verifyM.isPending || !s?.search.set}
              title={s?.search.set ? "저장된 키로 최소 검색을 시도해 연동 확인" : "먼저 키를 저장하세요"}
            >
              {verifyM.isPending ? "확인 중…" : "연결 테스트"}
            </Button>
            <Button
              onClick={() => saveM.mutate({ search_key: searchKey.trim() ? searchKey.trim() : null })}
              disabled={saveM.isPending}
            >
              저장
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

function VerifyBadge({ r }: { r?: string }) {
  if (!r) return null;
  if (r === "ok") return <Badge className="bg-ok/15 text-ok">연동 확인됨</Badge>;
  if (r === "unset") return <Badge className="bg-surface-2 text-muted">미설정</Badge>;
  return <Badge className="bg-err/15 text-err">{r}</Badge>;
}

function KeyField({
  label,
  current,
  value,
  onChange,
  onClear,
}: {
  label: string;
  current?: ProviderStatus;
  value: string;
  onChange: (v: string) => void;
  onClear: () => void;
}) {
  return (
    <label className="block text-xs font-medium text-muted">
      <span className="flex items-center gap-2">
        {label}
        {current?.set ? (
          <Badge className="bg-ok/15 text-ok">설정됨 {current.masked}</Badge>
        ) : (
          <span className="text-muted/70">미설정</span>
        )}
        {current?.set && (
          <button type="button" className="text-muted hover:text-err" onClick={onClear}>
            지우기
          </button>
        )}
      </span>
      <Input
        type="password"
        className="mt-1.5 font-mono"
        placeholder={current?.set ? "변경하려면 새 키 입력(비우면 유지)" : "키 입력"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
      />
    </label>
  );
}

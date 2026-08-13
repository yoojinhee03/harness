// API 클라이언트 — FastAPI 백엔드 계약. 개발 중 /api 는 Vite 프록시가 :8000 으로 전달.

const BASE = "/api";

export type ComponentType = "skill" | "mcp" | "context" | "hook";

export interface CatalogItem {
  id: string;
  type: ComponentType;
  name: string;
  version: string;
  status: string;
  summary: string;
  capability_tags: string[];
  provides: string[];
  requires: string[];
  conflicts_with: string[];
  exclusive_group: string | null;
  context_tokens: number;
  added_tools: number;
  auth_required: boolean;
}

export interface Recommendation {
  id: string;
  type: ComponentType;
  name: string;
  version: string;
  summary: string;
  score: number;
  reason: string;
  provides: string[];
  requires: string[];
  matched_capabilities: string[];
  context_tokens: number;
  added_tools: number;
  exclusive_group: string | null;
  conflicts_with: string[];
  auth_required: boolean;
}

export interface RecommendResult {
  description: string;
  requirements: string[];
  extraction_mode: string;
  ranking_mode: string;
  recommendations: Recommendation[];
  groups: Record<string, string[]>;
}

export type Severity = "error" | "warning" | "gap";

export interface Diagnostic {
  severity: Severity;
  code: string;
  message: string;
  detail: Record<string, unknown>;
  component_id: string | null;
  capability: string | null;
}

export interface ResolvedHarness {
  provided: Record<string, string[]>;
  hook_plan: Record<string, { id: string; blocking: boolean }[]>;
  auth_needs: { component_id: string; type: string | null; scopes: string[]; granted_scope: string | null }[];
  cost: { context_tokens: number; added_tools: number };
  components: { id: string; type: ComponentType; version: string; name: string }[];
}

export interface ResolveResult {
  ok: boolean;
  resolved: ResolvedHarness | null;
  diagnostics: { items: Diagnostic[] };
}

export interface GenerateResponse {
  yaml: string;
  ok: boolean;
  gaps: number;
  warnings: number;
  errors: number;
}

export interface EjectResult {
  ok: boolean;
  target: string;
  files: Record<string, string> | null;
}

export interface HarnessSummary {
  id: string;
  scope: string; // "personal:<uid>" | "team:<tid>"
  owner_id: string;
  name: string;
  description: string;
  version: number;
  updated_at: string;
}

export interface HarnessDoc extends HarnessSummary {
  yaml: string;
}

export interface HarnessVersion {
  version: number;
  updated_at: string;
  yaml: string;
}

export interface TeamMember {
  id: string;
  email: string;
  name: string;
  role: string; // owner | editor | viewer
}

export interface Team {
  id: string;
  name: string;
  owner_id: string;
  members: TeamMember[];
}

export interface Me {
  id: string;
  email: string;
  name: string;
  avatar_url: string;
  teams: Team[];
}

export interface AuthConfig {
  providers: string[]; // 예: ["github"]
  dev_auth: boolean;
}

export interface ApiToken {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

// ── 로컬 자격/선호(브라우저) ──
const TOKEN_KEY = "harness.token";
const SCOPE_KEY = "harness.scope";

export const auth = {
  token: () => localStorage.getItem(TOKEN_KEY) ?? "",
  setToken: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export const scopePref = {
  get: () => localStorage.getItem(SCOPE_KEY) ?? "personal",
  set: (s: string) => localStorage.setItem(SCOPE_KEY, s),
};

export interface SelectionInput {
  ref: string;
  config?: Record<string, unknown>;
}

export interface HarnessInput {
  metadata?: { id: string; name?: string; version?: string; description?: string };
  extends?: string | null;
  permissions?: Record<string, string>;
  components: SelectionInput[];
  budget?: { context_tokens: number; added_tools: number };
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const t = auth.token();
  if (t) headers.authorization = `Bearer ${t}`;
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) throw new Error("인증 필요 — 로그인하세요");
  if (!res.ok) throw new Error(`${path} 실패: ${res.status}`);
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) => send<T>("POST", path, body);

export interface ProviderStatus {
  set: boolean;
  masked: string | null;
}

export interface KeyStatus {
  anthropic: ProviderStatus;
  voyage: ProviderStatus;
  quality_mode: { embedder: string; ranker: string };
}

export const api = {
  health: () => fetch(`${BASE}/health`).then((r) => r.json()),
  catalog: () => fetch(`${BASE}/catalog`).then((r) => r.json() as Promise<CatalogItem[]>),
  // 페이지네이션 — type·capability·q 필터/검색 + limit/offset. 총계는 X-Total-Count 헤더.
  catalogPage: (params: { type?: string | null; capability?: string | null; q?: string; limit?: number; offset?: number } = {}) => {
    const sp = new URLSearchParams();
    if (params.type) sp.set("type", params.type);
    if (params.capability) sp.set("capability", params.capability);
    if (params.q) sp.set("q", params.q);
    if (params.limit != null) sp.set("limit", String(params.limit));
    if (params.offset != null) sp.set("offset", String(params.offset));
    return fetch(`${BASE}/catalog?${sp.toString()}`).then(async (r) => ({
      items: (await r.json()) as CatalogItem[],
      total: Number(r.headers.get("X-Total-Count") ?? 0),
    }));
  },
  catalogItem: (id: string) =>
    fetch(`${BASE}/catalog/${id}`).then((r) => r.json() as Promise<Record<string, unknown>>),
  recommend: (description: string, top_k = 6) =>
    post<RecommendResult>("/recommend", { description, top_k }),
  resolve: (harness: HarnessInput) => post<ResolveResult>("/resolve", harness),
  generate: (harness: HarnessInput) => post<GenerateResponse>("/generate", harness),
  ejectTargets: () => fetch(`${BASE}/eject/targets`).then((r) => r.json() as Promise<string[]>),
  eject: (harness: HarnessInput, target: string) =>
    post<EjectResult>(`/eject?target=${encodeURIComponent(target)}`, harness),
  // LLM 키는 배포 env 로만 설정 — 상태(읽기전용)만 조회/검증.
  getKeys: () => send<KeyStatus>("GET", "/settings/keys"),
  verifyKeys: () => send<Record<string, string>>("POST", "/settings/keys/verify"),

  // ── 인증 (OAuth 로그인 + PAT 발급) ──
  authConfig: () => fetch(`${BASE}/auth/config`).then((r) => r.json() as Promise<AuthConfig>),
  // OAuth 시작 — 브라우저를 이 URL 로 이동시키면 공급자 로그인 후 ?session= 으로 돌아온다.
  oauthStartUrl: (provider: string) => `${BASE}/auth/oauth/${encodeURIComponent(provider)}/start`,
  devLogin: (email: string) => post<{ token: string; user: Me }>("/auth/dev-login", { email }),
  logout: () => send<{ ok: boolean }>("POST", "/auth/logout"),
  me: () => send<Me>("GET", "/me"),
  // PAT — VSCode·기계 연결용 개인 토큰(설정 화면).
  listTokens: () => send<ApiToken[]>("GET", "/auth/tokens"),
  createToken: (name: string) => send<{ id: string; token: string; name: string }>("POST", "/auth/tokens", { name }),
  revokeToken: (id: string) => send<{ ok: boolean }>("DELETE", `/auth/tokens/${encodeURIComponent(id)}`),

  // ── 팀 (멀티테넌시) ──
  listTeams: () => send<Team[]>("GET", "/teams"),
  createTeam: (name: string) => send<Team>("POST", "/teams", { name }),
  addMember: (tid: string, email: string, role = "editor") =>
    send<Team>("POST", `/teams/${encodeURIComponent(tid)}/members`, { email, role }),

  // ── 공유 하네스 저장소 (VSCode 확장과 동일 백엔드 — 스코프 격리 · 양방향 동기화) ──
  listHarnesses: () => send<HarnessSummary[]>("GET", "/harnesses"),
  getHarness: (id: string, scope = "personal") =>
    send<HarnessDoc>("GET", `/harnesses/${encodeURIComponent(id)}?scope=${encodeURIComponent(scope)}`),
  harnessVersions: (id: string, scope = "personal") =>
    send<HarnessVersion[]>("GET", `/harnesses/${encodeURIComponent(id)}/versions?scope=${encodeURIComponent(scope)}`),
  putHarness: (id: string, scope: string, body: { name: string; description: string; yaml: string }) =>
    send<HarnessDoc>("PUT", `/harnesses/${encodeURIComponent(id)}?scope=${encodeURIComponent(scope)}`, body),
  deleteHarness: (id: string, scope = "personal") =>
    send<{ ok: boolean }>("DELETE", `/harnesses/${encodeURIComponent(id)}?scope=${encodeURIComponent(scope)}`),
};

/** 저장소 변경(가시 스코프)을 SSE 로 실시간 구독. 토큰은 EventSource 제약상 쿼리로 전달. */
export function subscribeHarnessEvents(onEvent: (type: string) => void): () => void {
  const t = auth.token();
  if (!t) return () => undefined; // 로그인 전엔 구독 안 함
  const es = new EventSource(`${BASE}/harnesses/events?token=${encodeURIComponent(t)}`);
  for (const ev of ["ready", "upsert", "delete"]) {
    es.addEventListener(ev, () => onEvent(ev));
  }
  return () => es.close();
}

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
  name: string;
  description: string;
  updated_at: string;
}

export interface HarnessDoc extends HarnessSummary {
  yaml: string;
}

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
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
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
  catalogItem: (id: string) =>
    fetch(`${BASE}/catalog/${id}`).then((r) => r.json() as Promise<Record<string, unknown>>),
  recommend: (description: string, top_k = 6) =>
    post<RecommendResult>("/recommend", { description, top_k }),
  resolve: (harness: HarnessInput) => post<ResolveResult>("/resolve", harness),
  generate: (harness: HarnessInput) => post<GenerateResponse>("/generate", harness),
  ejectTargets: () => fetch(`${BASE}/eject/targets`).then((r) => r.json() as Promise<string[]>),
  eject: (harness: HarnessInput, target: string) =>
    post<EjectResult>(`/eject?target=${encodeURIComponent(target)}`, harness),
  getKeys: () => send<KeyStatus>("GET", "/settings/keys"),
  putKeys: (body: { anthropic_api_key?: string; voyage_api_key?: string }) =>
    send<KeyStatus>("PUT", "/settings/keys", body),
  deleteKey: (provider: string) => send<KeyStatus>("DELETE", `/settings/keys/${provider}`),
  verifyKeys: () => send<Record<string, string>>("POST", "/settings/keys/verify"),

  // ── 공유 하네스 저장소 (VSCode 확장과 동일 백엔드 — 양방향 동기화) ──
  listHarnesses: () =>
    fetch(`${BASE}/harnesses`).then((r) => r.json() as Promise<HarnessSummary[]>),
  getHarness: (id: string) =>
    fetch(`${BASE}/harnesses/${encodeURIComponent(id)}`).then((r) => r.json() as Promise<HarnessDoc>),
  putHarness: (id: string, body: { name: string; description: string; yaml: string }) =>
    send<HarnessDoc>("PUT", `/harnesses/${encodeURIComponent(id)}`, body),
  deleteHarness: (id: string) => send<{ ok: boolean }>("DELETE", `/harnesses/${encodeURIComponent(id)}`),
};

/** 저장소 변경(upsert/delete)을 SSE 로 실시간 구독. 언구독 함수를 반환. 브라우저가 자동 재연결. */
export function subscribeHarnessEvents(onEvent: (type: string) => void): () => void {
  const es = new EventSource(`${BASE}/harnesses/events`);
  for (const t of ["ready", "upsert", "delete"]) {
    es.addEventListener(t, () => onEvent(t));
  }
  return () => es.close();
}

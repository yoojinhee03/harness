// 카탈로그 표시 헬퍼 — 리졸버 전문용어(capability id·cost·auth)를 고르는 사람이 읽는 말로 옮긴다.
// 데이터는 이미 /catalog 로 다 내려온다(백엔드 변경 없음); 여기선 "쉽게 설명"만 담당.
import type { ComponentType } from "../api/client";

export type Facet = "access" | "task" | "knowledge" | "lifecycle" | "prompt";

interface CapMeta {
  label: string;
  facet: Facet;
}

// capability id → 사람이 읽는 라벨. 원본 어휘: packages/catalog/.../vocabulary.py (CAPABILITY_VOCAB).
// 백엔드가 표시 라벨을 내려주지 않으므로 프런트에서 매핑한다 — 어휘가 바뀌면 여기도 갱신.
const CAP: Record<string, CapMeta> = {
  // access — 외부 시스템·데이터 접근 (주로 MCP)
  "vcs.code-hosting": { label: "저장소 접근", facet: "access" },
  "vcs.issue-tracking": { label: "이슈 트래킹", facet: "access" },
  "vcs.code-review": { label: "PR·코드 리뷰 접근", facet: "access" },
  "vcs.ci-cd": { label: "CI·CD 파이프라인", facet: "access" },
  "comms.messaging": { label: "메신저(슬랙 등)", facet: "access" },
  "comms.email": { label: "이메일", facet: "access" },
  "knowledge.wiki": { label: "위키·문서(노션 등)", facet: "access" },
  "knowledge.file-storage": { label: "파일 스토리지", facet: "access" },
  "data.relational": { label: "관계형 DB", facet: "access" },
  "data.spreadsheet": { label: "스프레드시트", facet: "access" },
  "data.vector": { label: "벡터 검색(RAG)", facet: "access" },
  "web.search": { label: "웹 검색", facet: "access" },
  "web.fetch": { label: "웹 페이지 가져오기", facet: "access" },
  "web.browse": { label: "브라우저 자동화", facet: "access" },
  "pm.task-tracking": { label: "작업 트래킹(지라 등)", facet: "access" },
  // task — 절차·워크플로 (주로 Skill)
  "author.document": { label: "문서 작성", facet: "task" },
  "author.slides": { label: "슬라이드 작성", facet: "task" },
  "author.spreadsheet": { label: "표 작성", facet: "task" },
  "review.code": { label: "코드 리뷰", facet: "task" },
  "analyze.data": { label: "데이터 분석", facet: "task" },
  "transform.extract": { label: "추출·파싱", facet: "task" },
  "transform.classify": { label: "분류·트리아지", facet: "task" },
  // knowledge — 배경 지식 (주로 Context)
  "convention.coding": { label: "코딩 컨벤션", facet: "knowledge" },
  "convention.process": { label: "팀 프로세스 규칙", facet: "knowledge" },
  "domain.knowledge": { label: "도메인 지식", facet: "knowledge" },
  // lifecycle — 요청 전후 동작 (주로 Hook)
  "lifecycle.logging": { label: "로깅·감사", facet: "lifecycle" },
  "lifecycle.validation": { label: "입출력 검증", facet: "lifecycle" },
  "lifecycle.guardrail": { label: "보안 가드레일", facet: "lifecycle" },
  "lifecycle.approval": { label: "승인 게이트", facet: "lifecycle" },
  "lifecycle.transform": { label: "요청·응답 변형", facet: "lifecycle" },
  // prompt — 시스템 프롬프트 조각 (Context facet)
  "prompt.role": { label: "역할·페르소나", facet: "prompt" },
  "prompt.format": { label: "출력 형식 지침", facet: "prompt" },
  "prompt.safety": { label: "안전 지침", facet: "prompt" },
};

/** capability id → 사람이 읽는 라벨(미등록이면 원본 id 그대로). */
export function capLabel(cap: string): string {
  return CAP[cap]?.label ?? cap;
}

/** capability id 의 facet(access|task|knowledge|lifecycle|prompt) — 미등록이면 null. */
export function capFacet(cap: string): Facet | null {
  return CAP[cap]?.facet ?? null;
}

/** 타입이 "무엇을 하는 부품인지" 한 줄 설명 — 상세 헤더에 곁들인다. */
export const TYPE_MEANING: Record<ComponentType, { noun: string; blurb: string }> = {
  skill: { noun: "절차·노하우", blurb: "작업을 '어떻게' 하는지 아는 절차를 에이전트에 더합니다." },
  mcp: { noun: "외부 연결", blurb: "외부 서비스에 연결해 실제로 접근·실행할 도구를 더합니다." },
  context: { noun: "배경 지식", blurb: "에이전트가 항상 참고하는 배경 지식을 주입합니다." },
  hook: { noun: "자동 동작", blurb: "요청 전후에 자동으로 실행되는 검사·차단 장치입니다." },
};

// /catalog/{id} 응답(리졸버 Component 모델 model_dump)의 표시에 쓰는 부분만 추린 타입.
export interface CatalogDetail {
  id: string;
  type: ComponentType;
  name: string;
  version: string;
  status: string;
  summary?: string;
  description?: string;
  use_when?: string[];
  examples?: string[];
  usage_note?: string | null;
  provides?: string[];
  requires?: string[];
  conflicts_with?: string[];
  constraints?: { exclusive_group?: string | null } | null;
  cost?: { context_tokens?: number; added_tools?: number; latency?: string };
  auth?: { required?: boolean; type?: string; scopes?: string[] } | null;
  events?: string[];
  config_schema?: unknown;
  trust?: "curated" | "official" | "community"; // 프로비넌스 신뢰 등급
  source?: string | null; // 출처 URL/경로
}

// 타입별 효과 서술 — "{이 항목이 주는 능력} — {타입이 그걸 어떻게 쓰는지}" 구조.
// 앞부분(능력)은 항목마다 다르고, 뒷부분(서술)만 타입으로 갈려 같은 타입이라도 항목별로 달리 읽힌다.
// '—' 구조라 능력 라벨에 조사(을/를)를 붙이지 않아 어색함이 없다.
const EFFECT_FRAME: Record<ComponentType, string> = {
  mcp: "에이전트가 직접 쓸 수 있게 됩니다",
  skill: "정해진 절차대로 수행합니다",
  context: "에이전트가 항상 참고하게 합니다", // knowledge 계열 기본(prompt 계열은 아래에서 갈아끼움)
  hook: "요청 처리 시 자동으로 적용합니다",
};

const EFFECT_FALLBACK_HEAD: Record<ComponentType, string> = {
  mcp: "외부 서비스 연결",
  skill: "이 작업",
  context: "이 배경 지식",
  hook: "자동 검사·차단",
};

/** "이걸 넣으면" 한 줄 효과 — 항목의 provides(능력)로 시작해 항목마다 달라진다. 비용 숫자는 넣지 않는다(아래 '부담' 줄 담당). */
export function effectLine(d: CatalogDetail): string {
  const rawCaps = d.provides ?? [];
  // 능력이 여럿이면 최대 3개까지만(길이 억제). 없으면 타입 기본 문구로.
  const head = rawCaps.length ? rawCaps.slice(0, 3).map(capLabel).join(" · ") : EFFECT_FALLBACK_HEAD[d.type];
  let frame = EFFECT_FRAME[d.type];
  if (!frame) return d.summary ?? ""; // 예상 밖 타입 방어
  // context 는 배경지식(knowledge)과 프롬프트 조각(prompt)을 한 타입에 담는 잡화 타입 —
  // prompt 계열은 '참고'가 아니라 시스템 프롬프트에 지침으로 주입되므로 서술을 달리한다.
  if (d.type === "context" && rawCaps.some((c) => capFacet(c) === "prompt")) {
    frame = "시스템 프롬프트에 지침으로 얹습니다";
  }
  return `${head} — ${frame}.`;
}

/** 도구 추가 비용 — 숫자 대신 "얼마나 부담인지"로. */
export function toolsCost(added: number): string {
  if (!added) return "도구 추가 없음";
  if (added <= 5) return `도구 ${added}개 추가`;
  return `도구 ${added}개 추가 · 많음(에이전트가 헷갈릴 수 있음)`;
}

/** 상시 컨텍스트 비용 — 정성 등급 + 대략치. */
export function contextCost(tokens: number): string {
  if (!tokens) return "상시 컨텍스트 없음";
  if (tokens < 1000) return `컨텍스트 조금 · ~${tokens}토큰`;
  const k = (tokens / 1000).toFixed(1);
  if (tokens < 4000) return `컨텍스트 보통 · ~${k}k토큰`;
  return `컨텍스트 많음 · ~${k}k토큰`;
}

/** 함께 못 쓰는 것(충돌 id + 배타 그룹)을 한 배열로. */
export function conflictLabels(d: CatalogDetail): string[] {
  const out = [...(d.conflicts_with ?? [])];
  const group = d.constraints?.exclusive_group;
  if (group) out.push(`'${group}' 그룹 택1`);
  return out;
}

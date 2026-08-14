import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type CatalogItem, type ComponentType } from "../api/client";
import {
  type CatalogDetail,
  capLabel,
  conflictLabels,
  contextCost,
  effectLine,
  toolsCost,
  TYPE_MEANING,
} from "../lib/catalog";
import { Badge, Button, Card, Chip, codeBlock, EmptyState, Input, PageHeader, SkeletonCards, TrustBadge, TYPE_COLOR, TYPE_LABEL } from "../lib/ui";

const TYPES: ComponentType[] = ["mcp", "skill", "context", "hook"];
const PAGE = 24;

export default function ScreenE({ onColdStart }: { onColdStart: () => void }) {
  const [q, setQ] = useState("");
  const [dq, setDq] = useState(""); // 디바운스된 검색어(서버 검색)
  const [type, setType] = useState<ComponentType | null>(null);
  const [cap, setCap] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<CatalogItem | null>(null);

  // 검색어 디바운스(300ms) — 매 타이핑마다 요청하지 않도록.
  useEffect(() => {
    const t = setTimeout(() => setDq(q), 300);
    return () => clearTimeout(t);
  }, [q]);
  // 필터·검색이 바뀌면 첫 페이지로.
  useEffect(() => {
    setOffset(0);
  }, [dq, type, cap]);

  // 서버 페이지네이션 — 필터·검색·정렬·슬라이스는 서버가. 페이지 전환 시 이전 데이터 유지(부드럽게).
  const { data, isPending } = useQuery({
    // excludeCurated — 카탈로그 브라우즈는 외부 수확분만 보여준다(우리 시드 제외). 추천/검증은 시드 유지.
    queryKey: ["catalog", { type, cap, dq, offset }],
    queryFn: () => api.catalogPage({ type, capability: cap, q: dq, limit: PAGE, offset, excludeCurated: true }),
    placeholderData: keepPreviousData,
  });
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = offset + items.length;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
      <div>
        <PageHeader
          title="카탈로그"
          subtitle="추천 대상 구성요소 저장소 — 탐색·검색·필터."
          actions={
            <Button variant="subtle" onClick={onColdStart}>
              + 신규 저작
            </Button>
          }
        />

        <Input className="mb-3" placeholder="이름·요약·능력 검색…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="mb-4 flex flex-wrap items-center gap-1.5">
          <FilterChip active={type === null} onClick={() => setType(null)}>
            전체
          </FilterChip>
          {TYPES.map((t) => (
            <FilterChip key={t} active={type === t} onClick={() => setType(type === t ? null : t)}>
              {TYPE_LABEL[t]}
            </FilterChip>
          ))}
          {cap && (
            <>
              <span className="mx-1 text-line">|</span>
              <FilterChip active onClick={() => setCap(null)}>
                {capLabel(cap)} ✕
              </FilterChip>
            </>
          )}
        </div>

        {isPending ? (
          <SkeletonCards count={6} />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              {items.map((i) => (
                <button
                  key={i.id}
                  onClick={() => setSelected(i)}
                  className={`rounded-xl border p-4 text-left transition-colors ${
                    selected?.id === i.id ? "border-accent ring-1 ring-accent/40" : "border-line hover:border-muted/40"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-fg">{i.name}</span>
                    <div className="flex shrink-0 items-center gap-1">
                      <TrustBadge trust={i.trust} />
                      <Chip className={TYPE_COLOR[i.type]}>{TYPE_LABEL[i.type]}</Chip>
                    </div>
                  </div>
                  <p className="mt-1 text-xs text-muted">{i.summary}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {i.capability_tags.map((c) => (
                      <button
                        key={c}
                        onClick={(e) => {
                          e.stopPropagation();
                          setCap(c);
                        }}
                        className="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted transition-colors hover:text-fg"
                      >
                        {capLabel(c)}
                      </button>
                    ))}
                  </div>
                </button>
              ))}
              {items.length === 0 && <EmptyState title="결과 없음" />}
            </div>

            {total > 0 && (
              <div className="mt-4 flex items-center justify-between text-xs text-muted">
                <span>
                  {from}–{to} / 총 {total.toLocaleString()}개
                </span>
                <div className="flex gap-2">
                  <Button size="sm" variant="subtle" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                    이전
                  </Button>
                  <Button size="sm" variant="subtle" disabled={to >= total} onClick={() => setOffset(offset + PAGE)}>
                    다음
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <aside className="lg:sticky lg:top-2 lg:self-start">
        {selected ? (
          <Detail id={selected.id} />
        ) : (
          <Card>
            <p className="text-sm text-muted">컴포넌트를 선택하면 무엇인지·넣으면 어떻게 되는지 설명이 표시됩니다.</p>
          </Card>
        )}
      </aside>
    </div>
  );
}

function FilterChip({ children, active, onClick }: { children: React.ReactNode; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
        active ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted hover:text-fg"
      }`}
    >
      {children}
    </button>
  );
}

function Detail({ id }: { id: string }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["catalog", id],
    queryFn: () => api.catalogItem(id),
    retry: false, // 404(연합 항목 만료 등)면 재시도 무의미.
  });
  if (isPending) return <Card>불러오는 중…</Card>;
  if (isError || !data) {
    return (
      <Card>
        <p className="text-sm text-muted">상세를 불러오지 못했습니다. 목록에서 다른 항목을 선택해 보세요.</p>
      </Card>
    );
  }
  const d = data as unknown as CatalogDetail;
  // type 이 예상 밖(손상된 응답 등)이어도 렌더는 안 죽게 폴백.
  const meaning = TYPE_MEANING[d.type] ?? { noun: "구성요소", blurb: "" };
  const provides = d.provides ?? [];
  const requires = d.requires ?? [];
  const conflicts = conflictLabels(d);
  const useWhen = d.use_when ?? [];
  const examples = d.examples ?? [];
  const authRequired = !!d.auth?.required;

  return (
    <Card>
      {/* 헤더 — 이름 + 타입이 무슨 부품인지 */}
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-fg">{d.name}</h3>
        <div className="flex shrink-0 items-center gap-1">
          <TrustBadge trust={d.trust} />
          <Chip className={TYPE_COLOR[d.type]}>{TYPE_LABEL[d.type]}</Chip>
        </div>
      </div>
      <p className="text-xs text-muted">
        {meaning.noun} · {d.id}@{d.version} · {d.status}
      </p>

      {/* 효과 — 한 줄 + 자세한 설명 */}
      <div className="mt-3 border-l-2 border-accent/50 pl-3">
        <p className="text-sm text-fg/90">{effectLine(d)}</p>
        {(d.description || d.summary) && (
          <p className="mt-1.5 text-xs leading-relaxed text-muted">{d.description || d.summary}</p>
        )}
      </div>

      {/* 쓰임새 — use_when + examples */}
      {(useWhen.length > 0 || examples.length > 0) && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-muted">쓰임새</p>
          {useWhen.length > 0 && (
            <ul className="mt-1 space-y-0.5">
              {useWhen.map((w) => (
                <li key={w} className="text-xs text-muted">
                  · {w}
                </li>
              ))}
            </ul>
          )}
          {examples.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {examples.map((ex) => (
                <Badge key={ex} className="bg-surface-2 text-muted">
                  {ex}
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ③ 넣으면 뭐가 달라지고 뭐가 드나 */}
      <div className="mt-3 space-y-2 border-t border-line pt-3">
        <FactRow label="생기는 능력">
          {provides.length ? (
            <BadgeList values={provides.map(capLabel)} className="bg-ok/15 text-ok" />
          ) : (
            <span className="text-muted/70">—</span>
          )}
        </FactRow>
        {requires.length > 0 && (
          <FactRow label="함께 필요" hint="없으면 추천이 자동으로 채웁니다">
            <BadgeList values={requires.map(capLabel)} className="bg-surface-2 text-fg/80" />
          </FactRow>
        )}
        {conflicts.length > 0 && (
          <FactRow label="함께 못 씀">
            <BadgeList values={conflicts} className="bg-err/15 text-err" />
          </FactRow>
        )}
        <FactRow label="부담">
          <span className="text-fg/80">
            {toolsCost(d.cost?.added_tools ?? 0)} · {contextCost(d.cost?.context_tokens ?? 0)}
          </span>
        </FactRow>
        <FactRow label="연결">
          {authRequired ? (
            <span className="text-warn">
              필요 — {d.auth?.type ?? "인증"}
              {(d.auth?.scopes ?? []).length > 0 && ` (${(d.auth?.scopes ?? []).join(", ")})`}
            </span>
          ) : (
            <span className="text-fg/80">불필요</span>
          )}
        </FactRow>
        <FactRow
          label="출처"
          hint={d.trust === "community" ? "외부 커뮤니티 발행 — 개별 안전성 미검증. 추가 전 확인 권장" : undefined}
        >
          {d.trust === "curated" && <span className="text-ok">검증됨 · 손큐레이션</span>}
          {d.trust === "official" && <span className="text-sky-400">공식 소스</span>}
          {(d.trust === undefined || d.trust === "community") && <span className="text-warn">미검증 · 외부 커뮤니티</span>}
          {d.source && <span className="ml-1 break-all text-muted">({d.source})</span>}
        </FactRow>
      </div>

      {/* 사용 팁(주로 MCP) */}
      {d.usage_note && (
        <div className="mt-3 rounded-lg bg-surface-2 p-3">
          <p className="text-xs font-semibold text-fg/80">사용 팁</p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{d.usage_note}</p>
        </div>
      )}

      {/* 고급 설정 — 기본은 접어둠 */}
      {d.config_schema != null && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-muted hover:text-fg">고급 설정 (config schema)</summary>
          <pre className={`mt-2 ${codeBlock}`}>{JSON.stringify(d.config_schema, null, 2)}</pre>
        </details>
      )}
    </Card>
  );
}

function FactRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="w-16 shrink-0 text-muted">{label}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1">{children}</div>
        {hint && <p className="mt-0.5 text-muted/60">{hint}</p>}
      </div>
    </div>
  );
}

function BadgeList({ values, className }: { values: string[]; className: string }) {
  return (
    <>
      {values.map((v) => (
        <Badge key={v} className={className}>
          {v}
        </Badge>
      ))}
    </>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type CatalogItem, type ComponentType } from "../api/client";
import { Badge, Button, Card, Chip, codeBlock, EmptyState, Input, PageHeader, TYPE_COLOR, TYPE_LABEL } from "../lib/ui";

const TYPES: ComponentType[] = ["mcp", "skill", "context", "hook"];

export default function ScreenE({ onColdStart }: { onColdStart: () => void }) {
  const { data: items = [], isPending } = useQuery({ queryKey: ["catalog"], queryFn: api.catalog });
  const [q, setQ] = useState("");
  const [type, setType] = useState<ComponentType | null>(null);
  const [cap, setCap] = useState<string | null>(null);
  const [selected, setSelected] = useState<CatalogItem | null>(null);

  const filtered = items.filter((i) => {
    if (type && i.type !== type) return false;
    if (cap && !i.capability_tags.includes(cap) && !i.provides.includes(cap)) return false;
    if (q) {
      const hay = `${i.id} ${i.name} ${i.summary} ${i.capability_tags.join(" ")}`.toLowerCase();
      if (!hay.includes(q.toLowerCase())) return false;
    }
    return true;
  });

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
                {cap} ✕
              </FilterChip>
            </>
          )}
        </div>

        {isPending ? (
          <p className="text-sm text-muted">불러오는 중…</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {filtered.map((i) => (
              <button
                key={i.id}
                onClick={() => setSelected(i)}
                className={`rounded-xl border p-4 text-left transition-colors ${
                  selected?.id === i.id ? "border-accent ring-1 ring-accent/40" : "border-line hover:border-muted/40"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-fg">{i.name}</span>
                  <Chip className={TYPE_COLOR[i.type]}>{TYPE_LABEL[i.type]}</Chip>
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
                      {c}
                    </button>
                  ))}
                </div>
              </button>
            ))}
            {filtered.length === 0 && <EmptyState title="결과 없음" />}
          </div>
        )}
      </div>

      <aside className="lg:sticky lg:top-2 lg:self-start">
        {selected ? (
          <Detail id={selected.id} />
        ) : (
          <Card>
            <p className="text-sm text-muted">컴포넌트를 선택하면 상세가 표시됩니다.</p>
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
  const { data, isPending } = useQuery({ queryKey: ["catalog", id], queryFn: () => api.catalogItem(id) });
  if (isPending || !data) return <Card>불러오는 중…</Card>;
  const d = data as Record<string, any>;
  return (
    <Card>
      <h3 className="text-sm font-semibold text-fg">{d.name}</h3>
      <p className="text-xs text-muted">
        {d.id}@{d.version} · {d.status}
      </p>
      <p className="mt-2 text-sm text-fg/90">{d.summary}</p>
      <DetailRow label="provides" values={d.provides} />
      <DetailRow label="requires" values={d.requires} />
      <DetailRow label="capability_tags" values={d.capability_tags} />
      <div className="mt-3 text-xs text-muted">
        비용: 컨텍스트 {d.cost?.context_tokens ?? 0}토큰 · 도구 +{d.cost?.added_tools ?? 0}
      </div>
      {d.auth?.required && (
        <div className="mt-1 text-xs text-warn">
          인증 필요: {d.auth.type} {(d.auth.scopes ?? []).join(", ")}
        </div>
      )}
      {d.config_schema && (
        <pre className={`mt-3 ${codeBlock}`}>{JSON.stringify(d.config_schema, null, 2)}</pre>
      )}
    </Card>
  );
}

function DetailRow({ label, values }: { label: string; values?: string[] }) {
  if (!values?.length) return null;
  return (
    <div className="mt-2 text-xs">
      <span className="text-muted">{label}: </span>
      {values.map((v) => (
        <Badge key={v} className="mr-1 bg-surface-2 text-fg/80">
          {v}
        </Badge>
      ))}
    </div>
  );
}

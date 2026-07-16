import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type CatalogItem, type ComponentType } from "../api/client";
import { Button, Card, Chip, TYPE_COLOR, TYPE_LABEL } from "../lib/ui";

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
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">카탈로그</h2>
            <p className="text-sm text-slate-500">추천 대상 구성요소 저장소 — 탐색·검색·필터.</p>
          </div>
          <Button variant="ghost" onClick={onColdStart}>
            + 신규 저작
          </Button>
        </div>

        <input
          className="mb-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          placeholder="이름·요약·능력 검색…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="mb-4 flex flex-wrap gap-1.5">
          <FilterChip active={type === null} onClick={() => setType(null)}>
            전체 타입
          </FilterChip>
          {TYPES.map((t) => (
            <FilterChip key={t} active={type === t} onClick={() => setType(type === t ? null : t)}>
              {TYPE_LABEL[t]}
            </FilterChip>
          ))}
          <span className="mx-1 text-slate-300">|</span>
          {cap && (
            <FilterChip active onClick={() => setCap(null)}>
              {cap} ✕
            </FilterChip>
          )}
        </div>

        {isPending ? (
          <p className="text-sm text-slate-400">불러오는 중…</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {filtered.map((i) => (
              <button
                key={i.id}
                onClick={() => setSelected(i)}
                className={`rounded-xl border p-4 text-left transition ${
                  selected?.id === i.id ? "border-slate-900 ring-1 ring-slate-900" : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-900">{i.name}</span>
                  <Chip className={TYPE_COLOR[i.type]}>{TYPE_LABEL[i.type]}</Chip>
                </div>
                <p className="mt-1 text-xs text-slate-500">{i.summary}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {i.capability_tags.map((c) => (
                    <button
                      key={c}
                      onClick={(e) => {
                        e.stopPropagation();
                        setCap(c);
                      }}
                      className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 hover:bg-slate-200"
                    >
                      {c}
                    </button>
                  ))}
                </div>
              </button>
            ))}
            {filtered.length === 0 && <p className="text-sm text-slate-400">결과 없음.</p>}
          </div>
        )}
      </div>

      <aside className="lg:sticky lg:top-6 lg:self-start">
        {selected ? <Detail id={selected.id} /> : <Card><p className="text-sm text-slate-400">컴포넌트를 선택하면 상세가 표시됩니다.</p></Card>}
      </aside>
    </div>
  );
}

function FilterChip({ children, active, onClick }: { children: React.ReactNode; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-medium ${active ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
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
      <h3 className="font-semibold text-slate-900">{d.name}</h3>
      <p className="text-xs text-slate-400">{d.id}@{d.version} · {d.status}</p>
      <p className="mt-2 text-sm text-slate-600">{d.summary}</p>
      <DetailRow label="provides" values={d.provides} />
      <DetailRow label="requires" values={d.requires} />
      <DetailRow label="capability_tags" values={d.capability_tags} />
      <div className="mt-3 text-xs text-slate-500">
        비용: 컨텍스트 {d.cost?.context_tokens ?? 0}토큰 · 도구 +{d.cost?.added_tools ?? 0}
      </div>
      {d.auth?.required && (
        <div className="mt-1 text-xs text-warn">인증 필요: {d.auth.type} {(d.auth.scopes ?? []).join(", ")}</div>
      )}
      {d.config_schema && (
        <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-900 p-3 text-[11px] text-slate-100">
          {JSON.stringify(d.config_schema, null, 2)}
        </pre>
      )}
    </Card>
  );
}

function DetailRow({ label, values }: { label: string; values?: string[] }) {
  if (!values?.length) return null;
  return (
    <div className="mt-2 text-xs">
      <span className="text-slate-400">{label}: </span>
      {values.map((v) => (
        <span key={v} className="mr-1 rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">
          {v}
        </span>
      ))}
    </div>
  );
}

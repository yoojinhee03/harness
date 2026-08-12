import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { useTheme } from "../lib/theme";
import { Kbd } from "../lib/ui";
import type { View } from "./AppShell";

interface Cmd {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

/** ⌘K 커맨드 팔레트 — 섹션 이동 · 새 하네스 · 테마 전환. */
export function CommandPalette({
  open,
  onClose,
  setView,
  onNewHarness,
}: {
  open: boolean;
  onClose: () => void;
  setView: (v: View) => void;
  onNewHarness: () => void;
}) {
  const [, toggleTheme] = useTheme();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // 열려 있을 때만 카탈로그·하네스를 가져와 검색 대상으로.
  const catalogQ = useQuery({ queryKey: ["catalog"], queryFn: api.catalog, enabled: open });
  const harnessQ = useQuery({ queryKey: ["harnesses"], queryFn: api.listHarnesses, enabled: open });

  const staticCmds = useMemo<Cmd[]>(
    () => [
      { id: "new", label: "새 하네스 만들기", hint: "생성", run: () => { onNewHarness(); onClose(); } },
      { id: "go-create", label: "이동: 생성", hint: "이동", run: () => { setView("create"); onClose(); } },
      { id: "go-catalog", label: "이동: 카탈로그", hint: "이동", run: () => { setView("catalog"); onClose(); } },
      { id: "go-harnesses", label: "이동: 하네스", hint: "이동", run: () => { setView("harnesses"); onClose(); } },
      { id: "go-settings", label: "이동: 설정", hint: "이동", run: () => { setView("settings"); onClose(); } },
      { id: "theme", label: "테마 전환 (다크/라이트)", hint: "설정", run: () => { toggleTheme(); onClose(); } },
    ],
    [setView, onNewHarness, onClose, toggleTheme],
  );

  // 검색어가 있을 때만 카탈로그·하네스 항목을 결과에 편입(빈 상태에선 커맨드만).
  const searchCmds = useMemo<Cmd[]>(() => {
    if (!q.trim()) return [];
    const cat = (catalogQ.data ?? []).map((c) => ({
      id: `cat-${c.id}`,
      label: c.name,
      hint: "카탈로그",
      run: () => { setView("catalog"); onClose(); },
    }));
    const har = (harnessQ.data ?? []).map((h) => ({
      id: `har-${h.scope}/${h.id}`,
      label: h.name || h.id,
      hint: "하네스",
      run: () => { setView("harnesses"); onClose(); },
    }));
    return [...cat, ...har];
  }, [q, catalogQ.data, harnessQ.data, setView, onClose]);

  const results = [...staticCmds, ...searchCmds]
    .filter((c) => c.label.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 20);

  useEffect(() => {
    if (open) {
      setQ("");
      setI(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(x + 1, results.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(x - 1, 0)); }
      else if (e.key === "Enter") { e.preventDefault(); results[i]?.run(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, results, i, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[18vh]" onClick={onClose}>
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-line bg-surface shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-line px-3">
          <span className="text-muted">⌘</span>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => { setQ(e.target.value); setI(0); }}
            placeholder="명령 검색…"
            className="h-11 flex-1 bg-transparent text-sm text-fg placeholder:text-muted focus:outline-none"
          />
          <Kbd>esc</Kbd>
        </div>
        <div className="max-h-72 overflow-y-auto p-1.5">
          {results.length === 0 && <div className="px-3 py-6 text-center text-sm text-muted">결과 없음</div>}
          {results.map((c, idx) => (
            <button
              key={c.id}
              onMouseEnter={() => setI(idx)}
              onClick={c.run}
              className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm ${
                idx === i ? "bg-surface-2 text-fg" : "text-fg/80"
              }`}
            >
              <span>{c.label}</span>
              {c.hint && <span className="text-xs text-muted">{c.hint}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

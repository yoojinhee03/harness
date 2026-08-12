import { useState, type ReactNode } from "react";
import { useTheme } from "../lib/theme";
import { IconButton, Kbd } from "../lib/ui";

export type View = "create" | "catalog" | "harnesses" | "settings";

const NAV: { key: View; label: string; icon: ReactNode }[] = [
  { key: "create", label: "생성", icon: <IconSparkle /> },
  { key: "catalog", label: "카탈로그", icon: <IconGrid /> },
  { key: "harnesses", label: "하네스", icon: <IconLayers /> },
  { key: "settings", label: "설정", icon: <IconGear /> },
];

const TITLE: Record<View, { title: string; sub: string }> = {
  create: { title: "생성", sub: "설명 → 추천 → 검증 → harness.yaml" },
  catalog: { title: "카탈로그", sub: "추천 대상 구성요소" },
  harnesses: { title: "하네스", sub: "내 하네스 · 팀 공유 (실시간 동기화)" },
  settings: { title: "설정", sub: "API 키 · 품질 모드" },
};

interface WsTeam {
  id: string;
  name: string;
}

export function AppShell({
  view,
  setView,
  onCmdK,
  account,
  onLogout,
  workspace,
  setWorkspace,
  teams = [],
  headerRight,
  children,
}: {
  view: View;
  setView: (v: View) => void;
  onCmdK: () => void;
  account?: string;
  onLogout?: () => void;
  workspace?: string;
  setWorkspace?: (s: string) => void;
  teams?: WsTeam[];
  headerRight?: ReactNode;
  children: ReactNode;
}) {
  const [theme, toggleTheme] = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const [wsOpen, setWsOpen] = useState(false);
  const t = TITLE[view];

  const wsLabel =
    !workspace || workspace === "personal"
      ? "개인"
      : (teams.find((x) => `team:${x.id}` === workspace)?.name ?? workspace.slice(5));

  return (
    <div className="flex h-full">
      {/* 사이드바 */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-surface/40">
        <div className="flex h-14 items-center gap-2 px-4">
          <div className="grid h-6 w-6 place-items-center rounded-md bg-accent text-accent-fg">
            <IconLogo />
          </div>
          <span className="text-sm font-semibold tracking-tight">Harness</span>
        </div>

        {/* 워크스페이스 스위처 — 개인/팀 전역 컨텍스트 */}
        {setWorkspace && (
          <div className="relative px-3 pb-2">
            <button
              onClick={() => setWsOpen((o) => !o)}
              className="flex w-full items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-sm transition-colors hover:border-muted/40"
            >
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded bg-accent/20 text-[10px] font-semibold text-accent">
                {wsLabel.slice(0, 1).toUpperCase()}
              </span>
              <span className="truncate text-fg">{wsLabel}</span>
              <IconChevronDown />
            </button>
            {wsOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setWsOpen(false)} />
                <div className="absolute left-3 right-3 z-50 mt-1 rounded-lg border border-line bg-surface p-1 shadow-panel">
                  <div className="px-2.5 py-1 text-[10px] uppercase tracking-wide text-muted">워크스페이스</div>
                  <MenuItem onClick={() => { setWorkspace("personal"); setWsOpen(false); }}>
                    <span className={workspace === "personal" || !workspace ? "text-fg" : ""}>개인</span>
                  </MenuItem>
                  {teams.map((tm) => (
                    <MenuItem key={tm.id} onClick={() => { setWorkspace(`team:${tm.id}`); setWsOpen(false); }}>
                      👥 {tm.name}
                    </MenuItem>
                  ))}
                  <div className="my-1 border-t border-line" />
                  <MenuItem onClick={() => { setView("harnesses"); setWsOpen(false); }}>팀 관리 →</MenuItem>
                </div>
              </>
            )}
          </div>
        )}

        <button
          onClick={onCmdK}
          className="mx-3 mb-2 flex h-8 items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 text-xs text-muted transition-colors hover:text-fg"
        >
          <IconSearch />
          <span className="flex-1 text-left">검색 · 이동</span>
          <Kbd>⌘K</Kbd>
        </button>

        <nav className="flex-1 space-y-0.5 px-3 py-1">
          {NAV.map((n) => {
            const active = view === n.key;
            return (
              <button
                key={n.key}
                onClick={() => setView(n.key)}
                className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition-colors ${
                  active ? "bg-surface-2 text-fg" : "text-muted hover:bg-surface-2/60 hover:text-fg"
                }`}
              >
                <span className={active ? "text-accent" : "text-muted"}>{n.icon}</span>
                {n.label}
              </button>
            );
          })}
        </nav>

        <div className="relative flex items-center justify-between gap-2 border-t border-line px-3 py-2.5">
          <button
            onClick={() => setMenuOpen((o) => !o)}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-surface-2"
          >
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent/20 text-[11px] font-semibold text-accent">
              {(account ?? "?").slice(0, 1).toUpperCase()}
            </span>
            <span className="truncate text-xs font-medium text-fg">{account ?? "…"}</span>
            <IconChevron />
          </button>
          <IconButton onClick={toggleTheme} title="테마 전환" aria-label="테마 전환">
            {theme === "dark" ? <IconSun /> : <IconMoon />}
          </IconButton>

          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div className="absolute bottom-full left-3 z-50 mb-1.5 w-48 rounded-lg border border-line bg-surface p-1 shadow-panel">
                <div className="px-2.5 py-1.5 text-xs text-muted">
                  <span className="font-medium text-fg">{account ?? "…"}</span> 계정
                </div>
                <MenuItem onClick={() => { setView("settings"); setMenuOpen(false); }}>설정</MenuItem>
                <MenuItem onClick={() => { setView("settings"); setMenuOpen(false); }}>토큰 관리</MenuItem>
                {onLogout && (
                  <MenuItem danger onClick={() => { onLogout(); setMenuOpen(false); }}>
                    로그아웃
                  </MenuItem>
                )}
              </div>
            </>
          )}
        </div>
      </aside>

      {/* 메인 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-line px-6">
          <div>
            <div className="text-sm font-semibold">{t.title}</div>
            <div className="text-xs text-muted">{t.sub}</div>
          </div>
          <div className="flex items-center gap-2">{headerRight}</div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto px-6 py-6">{children}</main>
      </div>
    </div>
  );
}

/* ── 인라인 아이콘(외부 의존 없음, currentColor) ── */
const S = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
function IconSparkle() { return <svg {...S}><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" /></svg>; }
function IconGrid() { return <svg {...S}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg>; }
function IconLayers() { return <svg {...S}><path d="M12 3l9 5-9 5-9-5 9-5z" /><path d="M3 13l9 5 9-5" /></svg>; }
function IconGear() { return <svg {...S}><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 00-2-1.2L14 2h-4l-.5 2.6a7 7 0 00-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 005 12a7 7 0 00.1 1.2l-2 1.6 2 3.4 2.4-1a7 7 0 002 1.2L10 22h4l.5-2.6a7 7 0 002-1.2l2.4 1 2-3.4-2-1.6A7 7 0 0019 12z" /></svg>; }
function IconSearch() { return <svg {...S} width={13} height={13}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></svg>; }
function IconSun() { return <svg {...S}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" /></svg>; }
function IconMoon() { return <svg {...S}><path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z" /></svg>; }
function IconChevron() { return <svg {...S} width={14} height={14} className="ml-auto text-muted"><path d="M6 15l6-6 6 6" /></svg>; }
function IconChevronDown() { return <svg {...S} width={14} height={14} className="ml-auto text-muted"><path d="M6 9l6 6 6-6" /></svg>; }

function MenuItem({ children, onClick, danger }: { children: ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center rounded-md px-2.5 py-1.5 text-left text-sm transition-colors hover:bg-surface-2 ${
        danger ? "text-err" : "text-fg/90"
      }`}
    >
      {children}
    </button>
  );
}
function IconLogo() { return <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" /><path d="M8 10h8M8 13.5h8" strokeWidth={1.6} /></svg>; }

import { useState } from "react";
import { api, auth } from "../api/client";
import { useTheme } from "../lib/theme";
import { Button, IconButton, Input } from "../lib/ui";

/** 앱 진입 게이트 — 로그인/가입. 인증 후 콘솔로 진입한다. */
export function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const [theme, toggleTheme] = useTheme();
  const [mode, setMode] = useState<"register" | "token">("register");
  const [handle, setHandle] = useState("");
  const [token, setToken] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ handle: string; token: string } | null>(null);

  async function submit() {
    setErr(null);
    if (mode === "register") {
      if (!handle.trim()) return;
      setBusy(true);
      try {
        const acct = await api.register(handle.trim());
        auth.setToken(acct.token); // 세션에 저장(이 브라우저)
        setCreated({ handle: acct.handle, token: acct.token }); // 토큰 1회 공개 후 진입
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    } else {
      if (!token.trim()) return;
      auth.setToken(token.trim());
      onLogin();
    }
  }

  if (created) {
    return (
      <div className="relative flex h-full items-center justify-center bg-bg px-6">
        <div className="absolute right-4 top-4">
          <IconButton onClick={toggleTheme} title="테마 전환" aria-label="테마 전환">
            {theme === "dark" ? <Sun /> : <Moon />}
          </IconButton>
        </div>
        <div className="w-full max-w-[420px]">
          <div className="mb-6 flex flex-col items-center text-center">
            <div className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-ok/20 text-ok">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 6L9 17l-5-5" />
              </svg>
            </div>
            <h1 className="text-lg font-semibold tracking-tight">
              <b className="text-accent">{created.handle}</b> 계정이 생성됐어요
            </h1>
            <p className="mt-1 text-sm text-muted">
              아래 토큰으로 <b>VSCode 확장</b>·다른 브라우저에서도 같은 계정에 로그인합니다.
              <br />
              지금만 표시되니 안전한 곳에 복사해 두세요.
            </p>
          </div>
          <div className="rounded-2xl border border-line bg-surface p-5">
            <label className="text-xs font-medium text-muted">API 토큰</label>
            <div className="mt-1.5 flex gap-2">
              <Input readOnly value={created.token} className="font-mono text-xs" onFocus={(e) => e.currentTarget.select()} />
              <Button variant="subtle" onClick={() => navigator.clipboard?.writeText(created.token)}>
                복사
              </Button>
            </div>
            <p className="mt-2 text-xs text-muted">
              확장에서는 <code>Harness Architect: 로그인 → 토큰 붙여넣기</code> 에 이 값을 넣으세요.
            </p>
            <Button className="mt-4 w-full" onClick={onLogin}>
              콘솔로 들어가기 →
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full items-center justify-center bg-bg px-6">
      <div className="absolute right-4 top-4">
        <IconButton onClick={toggleTheme} title="테마 전환" aria-label="테마 전환">
          {theme === "dark" ? <Sun /> : <Moon />}
        </IconButton>
      </div>

      <div className="w-full max-w-[360px]">
        <div className="mb-7 flex flex-col items-center text-center">
          <div className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-accent text-accent-fg">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinejoin="round">
              <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" />
              <path d="M8 10h8M8 13.5h8" strokeWidth={1.6} />
            </svg>
          </div>
          <h1 className="text-lg font-semibold tracking-tight">Harness Architect</h1>
          <p className="mt-1 text-sm text-muted">로그인하면 내 하네스와 팀 워크스페이스로 들어갑니다.</p>
        </div>

        <div className="rounded-2xl border border-line bg-surface p-5">
          <div className="mb-4 flex rounded-lg bg-surface-2 p-0.5 text-sm">
            <button
              onClick={() => setMode("register")}
              className={`flex-1 rounded-md py-1.5 font-medium transition-colors ${mode === "register" ? "bg-bg text-fg shadow-sm" : "text-muted"}`}
            >
              계정 만들기
            </button>
            <button
              onClick={() => setMode("token")}
              className={`flex-1 rounded-md py-1.5 font-medium transition-colors ${mode === "token" ? "bg-bg text-fg shadow-sm" : "text-muted"}`}
            >
              토큰으로 로그인
            </button>
          </div>

          {mode === "register" ? (
            <label className="block text-xs font-medium text-muted">
              handle (사용자 이름)
              <Input
                className="mt-1.5"
                placeholder="예: alice"
                value={handle}
                autoFocus
                onChange={(e) => setHandle(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
            </label>
          ) : (
            <label className="block text-xs font-medium text-muted">
              API 토큰
              <Input
                className="mt-1.5"
                type="password"
                placeholder="발급받은 토큰"
                value={token}
                autoFocus
                onChange={(e) => setToken(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
            </label>
          )}

          {err && <p className="mt-3 text-sm text-err">{err}</p>}

          <Button className="mt-4 w-full" onClick={submit} disabled={busy}>
            {busy ? "생성 중…" : mode === "register" ? "가입하고 시작하기" : "로그인"}
          </Button>
        </div>

        <p className="mt-4 text-center text-xs text-muted">
          토큰은 이 브라우저에만 저장됩니다 · 백엔드는 <code>{"harness.apiUrl"}</code>(기본 :8000)
        </p>
      </div>
    </div>
  );
}

function Sun() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" />
    </svg>
  );
}
function Moon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z" />
    </svg>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, auth } from "../api/client";
import { useTheme } from "../lib/theme";
import { Button, IconButton, Input, Spinner } from "../lib/ui";

const AUTH_ERRORS: Record<string, string> = {
  invalid_state: "로그인 세션이 만료됐어요. 다시 시도해 주세요.",
  token_exchange: "GitHub 토큰 교환에 실패했어요.",
  no_email: "GitHub 계정에서 확인된 이메일을 찾지 못했어요.",
  provider_unreachable: "GitHub에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.",
};

/** 앱 진입 게이트 — OAuth 로그인. 사람은 이메일(OAuth)로, 기계(VSCode)는 설정에서 발급한 토큰으로. */
export function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const [theme, toggleTheme] = useTheme();
  const cfgQ = useQuery({ queryKey: ["auth-config"], queryFn: api.authConfig });
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(() => {
    const code = new URLSearchParams(window.location.search).get("auth_error");
    if (code) window.history.replaceState({}, "", window.location.pathname); // URL 정리
    return code ? (AUTH_ERRORS[code] ?? "로그인에 실패했어요.") : null;
  });

  const cfg = cfgQ.data;
  const hasGithub = cfg?.providers.includes("github") ?? false;
  const devAuth = cfg?.dev_auth ?? false;

  function loginWithGithub() {
    window.location.href = api.oauthStartUrl("github");
  }

  async function loginDev() {
    if (!email.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.devLogin(email.trim());
      auth.setToken(r.token);
      onLogin();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
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
          {cfgQ.isPending ? (
            <div className="flex items-center justify-center gap-2 py-4 text-sm text-muted">
              <Spinner /> 불러오는 중…
            </div>
          ) : (
            <>
              {hasGithub && (
                <Button className="w-full" variant="subtle" onClick={loginWithGithub}>
                  <GithubMark /> GitHub로 계속하기
                </Button>
              )}

              {hasGithub && devAuth && (
                <div className="my-4 flex items-center gap-3 text-[11px] text-muted">
                  <span className="h-px flex-1 bg-line" /> 또는 <span className="h-px flex-1 bg-line" />
                </div>
              )}

              {devAuth && (
                <div>
                  <label className="block text-xs font-medium text-muted">
                    개발 로그인 (이메일)
                    <Input
                      className="mt-1.5"
                      type="email"
                      placeholder="you@example.com"
                      value={email}
                      autoFocus={!hasGithub}
                      onChange={(e) => setEmail(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && loginDev()}
                    />
                  </label>
                  <Button className="mt-3 w-full" onClick={loginDev} disabled={busy || !email.trim()}>
                    {busy ? "로그인 중…" : "개발 로그인"}
                  </Button>
                  <p className="mt-2 text-[11px] text-muted">
                    개발 환경 전용(<code>HARNESS_DEV_AUTH=on</code>) — 실제 OAuth 앱 없이 로그인합니다.
                  </p>
                </div>
              )}

              {!hasGithub && !devAuth && (
                <p className="text-sm text-muted">
                  로그인 방법이 구성되지 않았어요. 배포 환경에 <code>GITHUB_OAUTH_CLIENT_ID</code> 를 설정하거나, 개발
                  환경이면 <code>HARNESS_DEV_AUTH=on</code> 으로 실행하세요.
                </p>
              )}

              {err && <p className="mt-3 text-sm text-err">{err}</p>}
            </>
          )}
        </div>

        <p className="mt-4 text-center text-xs text-muted">
          VSCode 확장은 <b className="text-fg">설정 → API 토큰</b> 에서 발급한 토큰으로 연결합니다.
        </p>
      </div>
    </div>
  );
}

function GithubMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 2C6.48 2 2 6.58 2 12.26c0 4.5 2.87 8.32 6.84 9.67.5.1.68-.22.68-.48v-1.7c-2.78.62-3.37-1.2-3.37-1.2-.46-1.18-1.11-1.5-1.11-1.5-.9-.63.07-.62.07-.62 1 .07 1.53 1.05 1.53 1.05.9 1.56 2.34 1.11 2.91.85.09-.66.35-1.11.63-1.37-2.22-.26-4.56-1.14-4.56-5.06 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.7 0 0 .84-.28 2.75 1.05a9.36 9.36 0 015 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.4.2 2.44.1 2.7.64.72 1.03 1.63 1.03 2.75 0 3.93-2.35 4.8-4.58 5.05.36.32.68.94.68 1.9v2.82c0 .27.18.59.69.48A10.02 10.02 0 0022 12.26C22 6.58 17.52 2 12 2z" />
    </svg>
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

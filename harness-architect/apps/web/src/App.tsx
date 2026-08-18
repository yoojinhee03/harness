import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, auth, scopePref } from "./api/client";
import { AppShell, type View } from "./components/AppShell";
import { CommandPalette } from "./components/CommandPalette";
import { LoginScreen } from "./components/LoginScreen";
import ScreenE from "./screens/ScreenE";
import ScreenGuide from "./screens/ScreenGuide";
import ScreenSettings from "./screens/ScreenSettings";
import ScreenStudio from "./screens/ScreenStudio";
import ScreenSync from "./screens/ScreenSync";

export default function App() {
  const [authed, setAuthed] = useState(() => auth.token().length > 0);
  const [view, setView] = useState<View>("studio");
  const [cmdOpen, setCmdOpen] = useState(false);
  const [workspace, setWorkspaceState] = useState(() => scopePref.get()); // 전역 워크스페이스(개인/팀)
  const setWorkspace = (s: string) => {
    scopePref.set(s);
    setWorkspaceState(s);
  };

  // OAuth 콜백 착지 — 백엔드가 ?session=<토큰> 으로 리다이렉트. 저장 후 URL 정리하고 진입.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const session = params.get("session");
    if (session) {
      auth.setToken(session);
      window.history.replaceState({}, "", window.location.pathname);
      setAuthed(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const queryClient = useQueryClient();
  const meQ = useQuery({ queryKey: ["me"], queryFn: api.me, enabled: authed, retry: false });
  useEffect(() => {
    if (meQ.isError) logout();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meQ.isError]);

  // 로그아웃 = 이 브라우저의 이전 사용자 흔적 제거(계정 간 데이터 누출 방지): 캐시·워크스페이스·토큰.
  function logout() {
    api.logout().catch(() => undefined); // 서버 세션 토큰 폐기(best-effort). 토큰 지우기 전에 호출.
    queryClient.clear();
    localStorage.removeItem("harness.saved"); // 구 대시보드 잔재
    scopePref.set("personal");
    setWorkspaceState("personal");
    auth.clear();
    setAuthed(false);
    setView("studio");
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // 빌드 진입점은 이제 스튜디오(대화) 하나 — 구 '생성' 위저드는 스튜디오로 통합됨.
  const goBuild = () => setView("studio");

  // 앱 진입 게이트 — 미로그인이면 콘솔 대신 로그인 화면.
  if (!authed) {
    return <LoginScreen onLogin={() => setAuthed(true)} />;
  }

  return (
    <>
      <AppShell
        view={view}
        setView={setView}
        onCmdK={() => setCmdOpen(true)}
        account={meQ.data?.name || meQ.data?.email}
        onLogout={logout}
        workspace={workspace}
        setWorkspace={setWorkspace}
        teams={meQ.data?.teams ?? []}
      >
        {view === "studio" && <ScreenStudio workspace={workspace} />}
        {view === "catalog" && <ScreenE onColdStart={goBuild} />}
        {view === "harnesses" && <ScreenSync onCreate={goBuild} workspace={workspace} />}
        {view === "settings" && <ScreenSettings onLogout={logout} />}
        {view === "guide" && <ScreenGuide setView={setView} onNewHarness={goBuild} />}
      </AppShell>

      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} setView={setView} onNewHarness={goBuild} />
    </>
  );
}

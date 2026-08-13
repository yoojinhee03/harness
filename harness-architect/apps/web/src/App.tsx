import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, auth, scopePref, type HarnessInput, type Recommendation } from "./api/client";
import { AppShell, type View } from "./components/AppShell";
import { CommandPalette } from "./components/CommandPalette";
import { LoginScreen } from "./components/LoginScreen";
import { clearDraft, loadDraft, saveDraft } from "./lib/draft";

interface Draft {
  step: Step;
  description: string;
  requirements: string[];
  recommendations: Recommendation[];
  groups: Record<string, string[]>;
  selection: Selection;
  metadataId: string;
}
import ScreenA from "./screens/ScreenA";
import ScreenB from "./screens/ScreenB";
import ScreenC from "./screens/ScreenC";
import ScreenD from "./screens/ScreenD";
import ScreenE from "./screens/ScreenE";
import ScreenGuide from "./screens/ScreenGuide";
import ScreenSettings from "./screens/ScreenSettings";
import ScreenSync from "./screens/ScreenSync";

export type Step = "A" | "B" | "C" | "D";
export type Selection = Record<string, Recommendation>;

const STEPS: { key: Step; label: string }[] = [
  { key: "A", label: "설명" },
  { key: "B", label: "추천" },
  { key: "C", label: "검증" },
  { key: "D", label: "yaml" },
];

export default function App() {
  const [authed, setAuthed] = useState(() => auth.token().length > 0);
  const draft0 = useRef(loadDraft<Draft>()).current; // 새로고침 후 드래프트 복원(1회)
  const [view, setView] = useState<View>("create");
  const [step, setStep] = useState<Step>(draft0?.step ?? "A");
  const [cmdOpen, setCmdOpen] = useState(false);
  const [workspace, setWorkspaceState] = useState(() => scopePref.get()); // 전역 워크스페이스(개인/팀)
  const setWorkspace = (s: string) => {
    scopePref.set(s);
    setWorkspaceState(s);
  };

  // 로그인 후 계정 정보(사이드바 표시). 토큰이 만료/무효면 401 → 자동 로그아웃.
  const queryClient = useQueryClient();
  const meQ = useQuery({ queryKey: ["me"], queryFn: api.me, enabled: authed, retry: false });
  useEffect(() => {
    if (meQ.isError) {
      logout();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meQ.isError]);

  // 로그아웃 = 이 브라우저의 이전 사용자 흔적을 전부 제거(계정 간 데이터 누출 방지):
  // react-query 캐시(하네스·me·versions)·생성 드래프트·인메모리 상태·워크스페이스.
  function logout() {
    queryClient.clear();
    clearDraft();
    localStorage.removeItem("harness.saved"); // 구 대시보드 잔재
    scopePref.set("personal");
    setWorkspaceState("personal");
    setSelection({});
    setDescription("");
    setRequirements([]);
    setRecommendations([]);
    setGroups({});
    setMetadataId("untitled-harness");
    setStep("A");
    auth.clear();
    setAuthed(false);
    setView("create");
  }

  const [description, setDescription] = useState(draft0?.description ?? "");
  const [requirements, setRequirements] = useState<string[]>(draft0?.requirements ?? []);
  const [recommendations, setRecommendations] = useState<Recommendation[]>(draft0?.recommendations ?? []);
  const [groups, setGroups] = useState<Record<string, string[]>>(draft0?.groups ?? {});
  const [selection, setSelection] = useState<Selection>(draft0?.selection ?? {});
  const [metadataId, setMetadataId] = useState(draft0?.metadataId ?? "untitled-harness");

  // 드래프트 영속 — 탭 이동·새로고침에도 마법사 상태 보존.
  useEffect(() => {
    saveDraft({ step, description, requirements, recommendations, groups, selection, metadataId });
  }, [step, description, requirements, recommendations, groups, selection, metadataId]);

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

  const harnessInput = useMemo<HarnessInput>(() => {
    const permissions: Record<string, string> = {};
    if (Object.values(selection).some((r) => r.provides.includes("vcs.code-hosting"))) {
      permissions["vcs.code-hosting"] = "read-only";
    }
    return {
      metadata: { id: metadataId, name: description.slice(0, 40) || metadataId },
      permissions,
      components: Object.values(selection).map((r) => ({ ref: `${r.id}@${r.version}` })),
    };
  }, [selection, metadataId, description]);

  function handleSaved(yaml: string) {
    // 저장은 백엔드가 단일 원본(스코프 격리). 예전 localStorage 저장은 전역이라 계정 간 누출 위험 → 제거.
    api
      .putHarness(metadataId, workspace, {
        name: harnessInput.metadata?.name || metadataId,
        description: description.slice(0, 120),
        yaml,
      })
      .catch(() => undefined);
  }

  function newHarness() {
    clearDraft();
    setSelection({});
    setDescription("");
    setRequirements([]);
    setRecommendations([]);
    setGroups({});
    setMetadataId("untitled-harness");
    setStep("A");
    setView("create");
  }

  const maxStep = STEPS.findIndex((s) => s.key === step);

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
        account={meQ.data?.handle}
        onLogout={logout}
        workspace={workspace}
        setWorkspace={setWorkspace}
        teams={meQ.data?.teams ?? []}
        headerRight={view === "create" ? <StepNav step={step} setStep={setStep} maxStep={maxStep} /> : undefined}
      >
        {view === "create" && step === "A" && (
          <ScreenA
            description={description}
            setDescription={setDescription}
            onResult={(r) => {
              setRequirements(r.requirements);
              setRecommendations(r.recommendations);
              setGroups(r.groups);
              setMetadataId(slugify(description));
              setStep("B");
            }}
          />
        )}
        {view === "create" && step === "B" && (
          <ScreenB
            requirements={requirements}
            recommendations={recommendations}
            groups={groups}
            selection={selection}
            setSelection={setSelection}
            onBack={() => setStep("A")}
            onValidate={() => setStep("C")}
          />
        )}
        {view === "create" && step === "C" && (
          <ScreenC harness={harnessInput} onBackToRecommend={() => setStep("B")} onConfirm={() => setStep("D")} />
        )}
        {view === "create" && step === "D" && (
          <ScreenD harness={harnessInput} onRevalidate={() => setStep("C")} onSaved={handleSaved} />
        )}

        {view === "catalog" && <ScreenE onColdStart={newHarness} />}
        {view === "harnesses" && <ScreenSync onCreate={newHarness} workspace={workspace} />}
        {view === "settings" && <ScreenSettings onLogout={logout} />}
        {view === "guide" && <ScreenGuide setView={setView} onNewHarness={newHarness} />}
      </AppShell>

      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} setView={setView} onNewHarness={newHarness} />
    </>
  );
}

function StepNav({ step, setStep, maxStep }: { step: Step; setStep: (s: Step) => void; maxStep: number }) {
  return (
    <div className="flex items-center gap-1">
      {STEPS.map((s, i) => {
        const active = s.key === step;
        const done = i < maxStep;
        return (
          <button
            key={s.key}
            disabled={i > maxStep}
            onClick={() => setStep(s.key)}
            className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
              active ? "bg-surface-2 text-fg" : done ? "text-muted hover:text-fg" : "text-muted/50"
            }`}
          >
            <span
              className={`grid h-4 w-4 place-items-center rounded-full text-[10px] ${
                active ? "bg-accent text-accent-fg" : "border border-line"
              }`}
            >
              {i + 1}
            </span>
            {s.label}
          </button>
        );
      })}
    </div>
  );
}

function slugify(text: string): string {
  const base = text
    .toLowerCase()
    .replace(/[^a-z0-9가-힣]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return base || "untitled-harness";
}

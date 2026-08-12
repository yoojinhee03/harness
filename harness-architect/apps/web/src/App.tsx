import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, auth, scopePref, type HarnessInput, type Recommendation } from "./api/client";
import { AppShell, type View } from "./components/AppShell";
import { CommandPalette } from "./components/CommandPalette";
import { LoginScreen } from "./components/LoginScreen";
import { saveHarness } from "./lib/store";
import ScreenA from "./screens/ScreenA";
import ScreenB from "./screens/ScreenB";
import ScreenC from "./screens/ScreenC";
import ScreenD from "./screens/ScreenD";
import ScreenE from "./screens/ScreenE";
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
  const [view, setView] = useState<View>("create");
  const [step, setStep] = useState<Step>("A");
  const [cmdOpen, setCmdOpen] = useState(false);

  // 로그인 후 계정 정보(사이드바 표시). 토큰이 만료/무효면 401 → 자동 로그아웃.
  const meQ = useQuery({ queryKey: ["me"], queryFn: api.me, enabled: authed, retry: false });
  useEffect(() => {
    if (meQ.isError) {
      auth.clear();
      setAuthed(false);
    }
  }, [meQ.isError]);

  function logout() {
    auth.clear();
    setAuthed(false);
    setView("create");
  }

  const [description, setDescription] = useState("");
  const [requirements, setRequirements] = useState<string[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [groups, setGroups] = useState<Record<string, string[]>>({});
  const [selection, setSelection] = useState<Selection>({});
  const [metadataId, setMetadataId] = useState("untitled-harness");

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
    saveHarness({
      id: metadataId,
      name: harnessInput.metadata?.name || metadataId,
      createdAt: Date.now(),
      yaml,
      components: Object.values(selection),
      permissions: harnessInput.permissions ?? {},
    });
    api
      .putHarness(metadataId, scopePref.get(), {
        name: harnessInput.metadata?.name || metadataId,
        description: description.slice(0, 120),
        yaml,
      })
      .catch(() => undefined);
  }

  function newHarness() {
    setSelection({});
    setDescription("");
    setRequirements([]);
    setRecommendations([]);
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
        {view === "harnesses" && <ScreenSync />}
        {view === "settings" && <ScreenSettings />}
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

import { useMemo, useState } from "react";
import { api, scopePref, type HarnessInput, type Recommendation } from "./api/client";
import { saveHarness, type SavedHarness } from "./lib/store";
import ScreenA from "./screens/ScreenA";
import ScreenB from "./screens/ScreenB";
import ScreenC from "./screens/ScreenC";
import ScreenD from "./screens/ScreenD";
import ScreenE from "./screens/ScreenE";
import ScreenF from "./screens/ScreenF";
import ScreenSettings from "./screens/ScreenSettings";
import ScreenSync from "./screens/ScreenSync";

export type Step = "A" | "B" | "C" | "D";
export type View = "create" | "catalog" | "dashboard" | "sync" | "settings";

const STEPS: { key: Step; label: string }[] = [
  { key: "A", label: "설명" },
  { key: "B", label: "추천·선택" },
  { key: "C", label: "검증" },
  { key: "D", label: "harness.yaml" },
];

const NAV: { key: View; label: string }[] = [
  { key: "create", label: "생성" },
  { key: "catalog", label: "카탈로그" },
  { key: "dashboard", label: "대시보드" },
  { key: "sync", label: "동기화" },
  { key: "settings", label: "설정" },
];

export type Selection = Record<string, Recommendation>;

export default function App() {
  const [view, setView] = useState<View>("create");
  const [step, setStep] = useState<Step>("A");
  const [description, setDescription] = useState("");
  const [requirements, setRequirements] = useState<string[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [groups, setGroups] = useState<Record<string, string[]>>({});
  const [selection, setSelection] = useState<Selection>({});
  const [metadataId, setMetadataId] = useState("untitled-harness");

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
    // 공유 백엔드에도 저장(선택한 스코프) → 확장·다른 웹에 실시간 동기화. 미로그인/백엔드다운이면 무시.
    api
      .putHarness(metadataId, scopePref.get(), {
        name: harnessInput.metadata?.name || metadataId,
        description: description.slice(0, 120),
        yaml,
      })
      .catch(() => undefined);
  }

  function reopen(h: SavedHarness) {
    setSelection(Object.fromEntries(h.components.map((c) => [c.id, c])));
    setMetadataId(h.id);
    setDescription(h.name);
    setView("create");
    setStep("D");
  }

  function newHarness() {
    setSelection({});
    setDescription("");
    setRequirements([]);
    setRecommendations([]);
    setMetadataId("untitled-harness");
    setView("create");
    setStep("A");
  }

  const maxStep = STEPS.findIndex((s) => s.key === step);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">AI 하네스 아키텍트</h1>
            <p className="mt-1 text-sm text-slate-500">
              프로젝트를 설명하면 하네스 구성요소를 추천 → 검증 → 실행 가능한 harness.yaml 생성.
            </p>
          </div>
          <nav className="flex gap-1 rounded-lg bg-slate-100 p-1 text-sm">
            {NAV.map((n) => (
              <button
                key={n.key}
                onClick={() => setView(n.key)}
                className={`rounded-md px-3 py-1.5 font-medium transition ${
                  view === n.key ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
                }`}
              >
                {n.label}
              </button>
            ))}
          </nav>
        </div>

        {view === "create" && (
          <nav className="mt-5 flex items-center gap-2 text-sm">
            {STEPS.map((s, i) => {
              const done = i < maxStep;
              const active = s.key === step;
              return (
                <div key={s.key} className="flex items-center gap-2">
                  <button
                    disabled={i > maxStep}
                    onClick={() => setStep(s.key)}
                    className={`flex items-center gap-2 rounded-full px-3 py-1 font-medium transition ${
                      active ? "bg-slate-900 text-white" : done ? "bg-slate-200 text-slate-700 hover:bg-slate-300" : "text-slate-400"
                    }`}
                  >
                    <span className="grid h-5 w-5 place-items-center rounded-full border text-xs">{i + 1}</span>
                    {s.label}
                  </button>
                  {i < STEPS.length - 1 && <span className="text-slate-300">→</span>}
                </div>
              );
            })}
          </nav>
        )}
      </header>

      {view === "catalog" && <ScreenE onColdStart={newHarness} />}
      {view === "dashboard" && <ScreenF onNew={newHarness} onReopen={reopen} />}
      {view === "sync" && <ScreenSync />}
      {view === "settings" && <ScreenSettings />}

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

import * as path from "node:path";
import * as vscode from "vscode";
import { workspaceRoot } from "./config";
import type { HarnessServer } from "./mcp";

interface Diag {
  severity: "error" | "warning" | "gap";
  code: string;
  message: string;
  component_id?: string | null;
  capability?: string | null;
}

interface ResolveResult {
  ok: boolean;
  diagnostics: { errors: Diag[]; gaps: Diag[]; warnings: Diag[] };
  resolved?: {
    components: string[];
    context_tokens: number;
    added_tools: number;
    prompt_hash?: string | null;
  };
}

const TARGETS = ["claude-code", "cursor"];

/** 활성 에디터가 harness.yaml 인지 확인하고 문서를 돌려준다. */
function activeHarnessDoc(): vscode.TextDocument | undefined {
  const doc = vscode.window.activeTextEditor?.document;
  if (doc && /harness\.ya?ml$/.test(doc.fileName)) {
    return doc;
  }
  return undefined;
}

async function docFrom(uri?: vscode.Uri): Promise<vscode.TextDocument | undefined> {
  if (uri) {
    return vscode.workspace.openTextDocument(uri);
  }
  return activeHarnessDoc();
}

/** gap/에러가 가리키는 component_id 가 문서에 있으면 그 줄을, 없으면 첫 줄을 범위로 잡는다. */
function rangeFor(doc: vscode.TextDocument, d: Diag): vscode.Range {
  const needle = d.component_id;
  if (needle) {
    for (let i = 0; i < doc.lineCount; i++) {
      const text = doc.lineAt(i).text;
      if (text.includes(needle)) {
        const col = text.indexOf(needle);
        return new vscode.Range(i, col, i, col + needle.length);
      }
    }
  }
  return new vscode.Range(0, 0, 0, Math.max(1, doc.lineAt(0).text.length));
}

export async function runResolve(
  server: HarnessServer,
  collection: vscode.DiagnosticCollection,
  uri?: vscode.Uri,
): Promise<void> {
  const doc = await docFrom(uri);
  if (!doc) {
    vscode.window.showWarningMessage("harness.yaml 파일을 열거나 선택한 뒤 실행하세요.");
    return;
  }
  const result = (await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: "harness resolve…" },
    () => server.call("resolve_harness", { harness_yaml: doc.getText() }),
  )) as ResolveResult;

  const items: vscode.Diagnostic[] = [];
  const push = (d: Diag, sev: vscode.DiagnosticSeverity) => {
    const label = d.capability ? `${d.message} (능력: ${d.capability})` : d.message;
    const diag = new vscode.Diagnostic(rangeFor(doc, d), `[${d.code}] ${label}`, sev);
    diag.source = "harness";
    items.push(diag);
  };
  result.diagnostics.errors.forEach((d) => push(d, vscode.DiagnosticSeverity.Error));
  result.diagnostics.gaps.forEach((d) => push(d, vscode.DiagnosticSeverity.Warning));
  result.diagnostics.warnings.forEach((d) => push(d, vscode.DiagnosticSeverity.Information));
  collection.set(doc.uri, items);

  if (result.ok && result.resolved) {
    const r = result.resolved;
    vscode.window.showInformationMessage(
      `✓ resolve ok — 컴포넌트 ${r.components.length}개 · 컨텍스트 ${r.context_tokens}토큰 · 도구 +${r.added_tools}`,
    );
  } else {
    const nGap = result.diagnostics.gaps.length;
    const actions = nGap > 0 ? ["추천으로 gap 메우기"] : [];
    vscode.window
      .showWarningMessage(
        `resolve 실패 — 에러 ${result.diagnostics.errors.length} · gap ${nGap}. Problems 패널 참조.`,
        ...actions,
      )
      .then((choice) => {
        if (choice) {
          vscode.commands.executeCommand("harness.recommend");
        }
      });
  }
}

export async function runEject(server: HarnessServer, defaultTarget: string, uri?: vscode.Uri): Promise<void> {
  const doc = await docFrom(uri);
  if (!doc) {
    vscode.window.showWarningMessage("harness.yaml 파일을 열거나 선택한 뒤 실행하세요.");
    return;
  }
  const target = await vscode.window.showQuickPick(
    TARGETS.map((t) => ({ label: t, picked: t === defaultTarget })),
    { title: "eject 타깃 런타임", placeHolder: defaultTarget },
  );
  if (!target) {
    return;
  }

  const root = workspaceRoot();
  const preview = await vscode.window.showQuickPick(
    [
      { label: "$(export) 워크스페이스에 쓰기", detail: root ?? "(워크스페이스 없음)", value: "write" as const },
      { label: "$(eye) 미리보기(파일 트리만)", detail: "디스크에 쓰지 않음", value: "preview" as const },
    ],
    { title: `eject → ${target.label}` },
  );
  if (!preview) {
    return;
  }

  const outDir = preview.value === "write" ? root : undefined;
  if (preview.value === "write" && !outDir) {
    vscode.window.showErrorMessage("워크스페이스 폴더가 없어 쓸 수 없습니다.");
    return;
  }

  const res = (await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `eject → ${target.label}…` },
    () =>
      server.call("eject_harness", {
        harness_yaml: doc.getText(),
        target: target.label,
        ...(outDir ? { out_dir: outDir } : {}),
      }),
  )) as {
    ok: boolean;
    diagnostics?: ResolveResult["diagnostics"];
    files?: Record<string, string>;
    written?: string[];
  };

  if (!res.ok) {
    const n = res.diagnostics?.errors.length ?? 0;
    vscode.window
      .showErrorMessage(`eject 중단 — resolve 실패(에러 ${n}). 먼저 검증하세요.`, "resolve 실행")
      .then((c) => c && vscode.commands.executeCommand("harness.resolve", doc.uri));
    return;
  }

  if (res.written) {
    const rels = res.written.map((w) => (root ? path.relative(root, w) : w));
    vscode.window
      .showInformationMessage(`✓ eject → ${target.label}: ${res.written.length}개 파일`, "파일 탐색기에서 보기")
      .then((c) => {
        if (c && res.written?.[0]) {
          vscode.commands.executeCommand("revealInExplorer", vscode.Uri.file(res.written[0]));
        }
      });
    vscode.window.setStatusBarMessage(`harness eject: ${rels.join(", ")}`, 5000);
  } else if (res.files) {
    // 미리보기 — 각 파일을 읽기전용 문서로 연다.
    const entries = Object.entries(res.files).sort(([a], [b]) => a.localeCompare(b));
    for (const [name, content] of entries) {
      const d = await vscode.workspace.openTextDocument({
        content: `# ===== ${name} (${target.label} eject 미리보기) =====\n\n${content}`,
        language: name.endsWith(".json") ? "json" : name.endsWith(".md") ? "markdown" : "plaintext",
      });
      await vscode.window.showTextDocument(d, { preview: false });
    }
  }
}

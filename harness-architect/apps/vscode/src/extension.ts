import * as vscode from "vscode";
import { CatalogProvider } from "./catalog";
import { readConfig } from "./config";
import { runEject, runResolve } from "./harnessOps";
import { HarnessServer } from "./mcp";
import { runRecommend } from "./recommend";

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("Harness");
  const diagnostics = vscode.languages.createDiagnosticCollection("harness");
  const extPath = context.extensionUri.fsPath;

  const boot = readConfig(extPath);
  output.appendLine(`[harness] 서버 출처: ${boot.source} — ${boot.spec.command}`);
  let server = new HarnessServer(boot.spec, output);
  const catalog = new CatalogProvider(server);

  context.subscriptions.push(
    output,
    diagnostics,
    { dispose: () => server.dispose() },
    vscode.window.registerTreeDataProvider("harnessCatalog", catalog),
  );

  const withServer = (fn: (s: HarnessServer) => Promise<void> | void) => async () => {
    try {
      await fn(server);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      output.appendLine(`[harness] 오류: ${msg}`);
      vscode.window
        .showErrorMessage(`Harness: ${msg}`, "로그 보기", "서버 재시작")
        .then((c) => {
          if (c === "로그 보기") {
            output.show();
          } else if (c === "서버 재시작") {
            vscode.commands.executeCommand("harness.restartServer");
          }
        });
    }
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "harness.recommend",
      withServer((s) => runRecommend(s, context.extensionUri)),
    ),
    vscode.commands.registerCommand(
      "harness.resolve",
      (uri?: vscode.Uri) => withServer((s) => runResolve(s, diagnostics, uri))(),
    ),
    vscode.commands.registerCommand(
      "harness.eject",
      (uri?: vscode.Uri) => withServer((s) => runEject(s, readConfig(extPath).defaultTarget, uri))(),
    ),
    vscode.commands.registerCommand("harness.refreshCatalog", () => catalog.refresh()),
    vscode.commands.registerCommand("harness.restartServer", () => {
      server.dispose();
      const next = readConfig(extPath);
      output.appendLine(`[harness] 서버 재시작 — 출처: ${next.source} — ${next.spec.command}`);
      server = new HarnessServer(next.spec, output);
      catalog.setServer(server);
      vscode.window.setStatusBarMessage(`Harness: 서버 재시작됨 (${next.source})`, 3000);
    }),
    vscode.commands.registerCommand("harness.copyRef", async (ref: string) => {
      if (ref) {
        await vscode.env.clipboard.writeText(ref);
        vscode.window.setStatusBarMessage(`복사됨: ${ref}`, 3000);
      }
    }),
  );

  // 설정 변경 → 서버 재생성.
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (
        e.affectsConfiguration("harness.serverCommand") ||
        e.affectsConfiguration("harness.serverArgs") ||
        e.affectsConfiguration("harness.catalogDir")
      ) {
        vscode.commands.executeCommand("harness.restartServer");
      }
    }),
  );

  // harness.yaml 상단에 resolve / eject 코드렌즈.
  context.subscriptions.push(
    vscode.languages.registerCodeLensProvider(
      [
        { language: "yaml", pattern: "**/*.harness.yaml" },
        { language: "yaml", pattern: "**/harness.yaml" },
      ],
      {
        provideCodeLenses(doc) {
          const top = new vscode.Range(0, 0, 0, 0);
          return [
            new vscode.CodeLens(top, { title: "$(check-all) resolve", command: "harness.resolve", arguments: [doc.uri] }),
            new vscode.CodeLens(top, { title: "$(export) eject", command: "harness.eject", arguments: [doc.uri] }),
          ];
        },
      },
    ),
  );

  // 저장 시 진단 갱신(이미 진단이 있던 파일만).
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (diagnostics.has(doc.uri) && /harness\.ya?ml$/.test(doc.fileName)) {
        withServer((s) => runResolve(s, diagnostics, doc.uri))();
      }
    }),
  );
}

export function deactivate(): void {
  // subscriptions 의 dispose 로 서버가 정리된다.
}

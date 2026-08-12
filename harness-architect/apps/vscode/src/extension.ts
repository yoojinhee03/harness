import * as vscode from "vscode";
import { CatalogProvider } from "./catalog";
import { registerChat } from "./chat";
import { getApiUrl, readConfig } from "./config";
import { runEject, runResolve } from "./harnessOps";
import { connectEvents, HarnessStoreClient } from "./harnessStore";
import { HarnessServer } from "./mcp";
import { runRecommend } from "./recommend";
import { openStarter, type StarterComponent } from "./starter";
import { deleteFromStore, openFromStore, saveActiveToStore, StoreProvider } from "./storeView";

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("Harness");
  const diagnostics = vscode.languages.createDiagnosticCollection("harness");
  const extPath = context.extensionUri.fsPath;
  const devMode = context.extensionMode === vscode.ExtensionMode.Development;

  const boot = readConfig(extPath, devMode);
  output.appendLine(`[harness] 서버 출처: ${boot.source} — ${boot.spec.command}`);
  let server = new HarnessServer(boot.spec, output);
  const catalog = new CatalogProvider(server);

  // 공유 하네스 저장소(웹↔확장 동기화) — 백엔드 HTTP + SSE 라이브.
  let storeClient = new HarnessStoreClient(getApiUrl());
  const store = new StoreProvider(storeClient);
  let sse = connectEvents(getApiUrl(), () => store.refresh(), output);

  context.subscriptions.push(
    output,
    diagnostics,
    { dispose: () => server.dispose() },
    { dispose: () => sse.dispose() },
    vscode.window.registerTreeDataProvider("harnessCatalog", catalog),
    vscode.window.registerTreeDataProvider("harnessStore", store),
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
      const next = readConfig(extPath, devMode);
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
    // 챗 참가자의 "스타터 생성" 버튼이 호출 — 추천 컴포넌트로 harness.yaml 초안을 연다.
    vscode.commands.registerCommand(
      "harness.createStarter",
      (description: string, comps: StarterComponent[]) => openStarter(description ?? "", comps ?? []),
    ),
    // 공유 저장소 커맨드 (웹↔확장 동기화)
    vscode.commands.registerCommand("harness.saveToStore", () => saveActiveToStore(storeClient)),
    vscode.commands.registerCommand("harness.openFromStore", (h) => openFromStore(storeClient, h)),
    vscode.commands.registerCommand("harness.deleteFromStore", (h) => deleteFromStore(storeClient, h)),
    vscode.commands.registerCommand("harness.refreshStore", () => store.refresh()),
  );

  // 챗 참가자 @harness — Copilot Chat 패널에서 자연어로 추천.
  registerChat(context, () => server);

  // 설정 변경 → 서버 재생성 / 저장소 재연결.
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (
        e.affectsConfiguration("harness.serverCommand") ||
        e.affectsConfiguration("harness.serverArgs") ||
        e.affectsConfiguration("harness.catalogDir")
      ) {
        vscode.commands.executeCommand("harness.restartServer");
      }
      if (e.affectsConfiguration("harness.apiUrl")) {
        sse.dispose();
        storeClient = new HarnessStoreClient(getApiUrl());
        store.setClient(storeClient);
        sse = connectEvents(getApiUrl(), () => store.refresh(), output);
        output.appendLine(`[store] apiUrl 변경 — 재연결: ${getApiUrl()}`);
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

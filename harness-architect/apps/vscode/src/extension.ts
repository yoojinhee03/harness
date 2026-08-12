import * as vscode from "vscode";
import { CatalogProvider } from "./catalog";
import { registerChat } from "./chat";
import { getApiToken, getApiUrl, readConfig } from "./config";
import { runEject, runResolve } from "./harnessOps";
import { connectEvents, HarnessStoreClient } from "./harnessStore";
import { HarnessServer } from "./mcp";
import { runRecommend } from "./recommend";
import { openStarter, type StarterComponent } from "./starter";
import { deleteFromStore, login, openFromStore, saveActiveToStore, StoreProvider } from "./storeView";

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("Harness");
  const diagnostics = vscode.languages.createDiagnosticCollection("harness");
  const extPath = context.extensionUri.fsPath;
  const devMode = context.extensionMode === vscode.ExtensionMode.Development;

  const boot = readConfig(extPath, devMode);
  output.appendLine(`[harness] 서버 출처: ${boot.source} — ${boot.spec.command}`);
  let server = new HarnessServer(boot.spec, output);
  const catalog = new CatalogProvider(server);

  // 공유 하네스 저장소(웹↔확장 동기화, 사용자·팀 스코프) — 백엔드 HTTP(Bearer) + SSE 라이브.
  let storeClient = new HarnessStoreClient(getApiUrl(), getApiToken());
  const store = new StoreProvider(storeClient);
  let sse = connectEvents(getApiUrl(), getApiToken(), () => store.refresh(), output);
  const reconnectStore = (): void => {
    sse.dispose();
    storeClient = new HarnessStoreClient(getApiUrl(), getApiToken());
    store.setClient(storeClient);
    sse = connectEvents(getApiUrl(), getApiToken(), () => store.refresh(), output);
  };

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
    // 공유 저장소 커맨드 (웹↔확장 동기화, 사용자·팀 스코프)
    vscode.commands.registerCommand("harness.saveToStore", () => saveActiveToStore(storeClient)),
    vscode.commands.registerCommand("harness.openFromStore", (h) => openFromStore(storeClient, h)),
    vscode.commands.registerCommand("harness.deleteFromStore", (h) => deleteFromStore(storeClient, h)),
    vscode.commands.registerCommand("harness.refreshStore", () => store.refresh()),
    vscode.commands.registerCommand("harness.login", async () => {
      if (await login(storeClient)) {
        reconnectStore();
      }
    }),
    vscode.commands.registerCommand("harness.createTeam", async () => {
      if (!storeClient.hasToken()) {
        vscode.commands.executeCommand("harness.login");
        return;
      }
      const name = await vscode.window.showInputBox({ title: "새 팀 이름", ignoreFocusOut: true });
      if (!name) {
        return;
      }
      try {
        const t = await storeClient.createTeam(name);
        vscode.window.showInformationMessage(`팀 생성: ${t.name} (team:${t.id}) — 저장 시 이 팀을 고르면 팀원과 공유됩니다.`);
      } catch (e) {
        vscode.window.showErrorMessage(`팀 생성 실패: ${e instanceof Error ? e.message : String(e)}`);
      }
    }),
    vscode.commands.registerCommand("harness.addTeamMember", async () => {
      if (!storeClient.hasToken()) {
        vscode.commands.executeCommand("harness.login");
        return;
      }
      try {
        const teams = await storeClient.teams();
        if (teams.length === 0) {
          vscode.window.showInformationMessage("먼저 팀을 만드세요 (Harness Architect: 새 팀 만들기).");
          return;
        }
        const pick = await vscode.window.showQuickPick(
          teams.map((t) => ({ label: t.name, description: `team:${t.id}`, id: t.id })),
          { title: "멤버를 추가할 팀" },
        );
        if (!pick) {
          return;
        }
        const handle = await vscode.window.showInputBox({ title: "추가할 멤버 handle", ignoreFocusOut: true });
        if (!handle) {
          return;
        }
        const rolePick = await vscode.window.showQuickPick(
          [
            { label: "에디터 (쓰기)", value: "editor" as const },
            { label: "뷰어 (읽기 전용)", value: "viewer" as const },
            { label: "오너", value: "owner" as const },
          ],
          { title: `${pick.label} — 역할` },
        );
        if (!rolePick) {
          return;
        }
        const t = await storeClient.addMember(pick.id, handle, rolePick.value);
        vscode.window.showInformationMessage(`'${handle}' (${rolePick.value}) 추가됨 — ${t.name} 멤버 ${t.members.length}명`);
      } catch (e) {
        vscode.window.showErrorMessage(`멤버 추가 실패: ${e instanceof Error ? e.message : String(e)}`);
      }
    }),
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
      if (e.affectsConfiguration("harness.apiUrl") || e.affectsConfiguration("harness.apiToken")) {
        reconnectStore();
        output.appendLine(`[store] 설정 변경 — 재연결: ${getApiUrl()} (토큰 ${getApiToken() ? "있음" : "없음"})`);
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

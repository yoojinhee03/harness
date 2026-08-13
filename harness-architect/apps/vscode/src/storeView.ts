import * as vscode from "vscode";
import { getApiUrl, setApiToken } from "./config";
import { HarnessStoreClient, type HarnessSummary } from "./harnessStore";

/** "내 하네스" 사이드바 — 내 가시 스코프(personal + 팀)의 하네스. SSE 이벤트마다 refresh(). */
export class StoreProvider implements vscode.TreeDataProvider<HarnessSummary> {
  private readonly _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  constructor(private client: HarnessStoreClient) {}

  setClient(client: HarnessStoreClient): void {
    this.client = client;
    this.refresh();
  }

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(h: HarnessSummary): vscode.TreeItem {
    const item = new vscode.TreeItem(h.name || h.id, vscode.TreeItemCollapsibleState.None);
    const isTeam = h.scope.startsWith("team:");
    item.description = isTeam ? `${h.id} · 👥 ${h.scope.slice(5)}` : h.id;
    item.iconPath = new vscode.ThemeIcon(isTeam ? "organization" : "person");
    item.contextValue = "harnessStoreItem";
    item.tooltip = new vscode.MarkdownString(
      [
        `**${h.name || h.id}**  \`${h.id}\``,
        "",
        h.description || "(설명 없음)",
        "",
        `- 스코프: \`${h.scope}\``,
        `- 소유: ${h.owner_id}`,
        `- 수정: ${h.updated_at ?? "-"}`,
      ]
        .filter(Boolean)
        .join("\n"),
    );
    item.command = { command: "harness.openFromStore", title: "열기", arguments: [h] };
    return item;
  }

  async getChildren(el?: HarnessSummary): Promise<HarnessSummary[]> {
    if (el) {
      return [];
    }
    if (!this.client.hasToken()) {
      return []; // 로그인 전 — viewsWelcome 안내.
    }
    try {
      return await this.client.list();
    } catch {
      return [];
    }
  }
}

/** 로그인 — 웹(설정 → API 토큰)에서 발급한 토큰을 붙여넣어 저장한다. 계정 로그인은 웹에서 OAuth 로. */
export async function login(): Promise<boolean> {
  const token = await vscode.window.showInputBox({
    title: "Harness 로그인 — API 토큰 붙여넣기",
    prompt: "웹에서 로그인 후 설정 → API 토큰 → '새 토큰 발급'으로 받은 토큰을 붙여넣으세요.",
    placeHolder: "발급받은 API 토큰",
    password: true,
    ignoreFocusOut: true,
  });
  if (!token) {
    return false;
  }
  const trimmed = token.trim();
  // 저장 전에 토큰 유효성 확인(잘못 붙여넣으면 즉시 알림).
  try {
    await new HarnessStoreClient(getApiUrl(), trimmed).list();
  } catch (e) {
    vscode.window.showErrorMessage(`토큰 확인 실패: ${e instanceof Error ? e.message : String(e)}`);
    return false;
  }
  await setApiToken(trimmed);
  vscode.window.showInformationMessage("토큰이 설정에 저장되었습니다.");
  return true;
}

/** 활성 harness.yaml 을 공유 저장소에 저장(upsert). 스코프(personal|팀)를 고른다. */
export async function saveActiveToStore(client: HarnessStoreClient): Promise<void> {
  const doc = vscode.window.activeTextEditor?.document;
  if (!doc || !/harness\.ya?ml$/.test(doc.fileName)) {
    vscode.window.showWarningMessage("harness.yaml 파일을 연 상태에서 저장하세요.");
    return;
  }
  if (!client.hasToken()) {
    vscode.window.showWarningMessage("먼저 로그인하세요.", "로그인").then((c) => {
      if (c) {
        vscode.commands.executeCommand("harness.login");
      }
    });
    return;
  }

  // 스코프 선택 — personal 또는 내 팀들.
  const picks: vscode.QuickPickItem[] = [{ label: "$(person) 개인(personal)", description: "나만" }];
  try {
    const teams = await client.teams();
    for (const t of teams) {
      picks.push({ label: `$(organization) ${t.name}`, description: `team:${t.id} · 👥 공유` });
    }
  } catch {
    /* 팀 목록 실패해도 personal 은 가능 */
  }
  const chosen = await vscode.window.showQuickPick(picks, { title: "어디에 저장할까요? (스코프)" });
  if (!chosen) {
    return;
  }
  const scope = chosen.description?.startsWith("team:") ? chosen.description.split(" ")[0] : "personal";

  const yaml = doc.getText();
  const guessedId = guessId(doc.fileName, yaml);
  const id = await vscode.window.showInputBox({ title: "저장 id", value: guessedId, ignoreFocusOut: true });
  if (!id) {
    return;
  }
  const name = await vscode.window.showInputBox({ title: "표시 이름(선택)", value: guessedId, ignoreFocusOut: true });
  if (name === undefined) {
    return;
  }
  try {
    const saved = await client.put(id, scope, { name, description: "", yaml });
    vscode.window.setStatusBarMessage(`✓ 저장됨: ${saved.id} (${saved.scope})`, 4000);
  } catch (e) {
    vscode.window.showErrorMessage(`저장 실패: ${e instanceof Error ? e.message : String(e)}`);
  }
}

export async function openFromStore(client: HarnessStoreClient, h: HarnessSummary): Promise<void> {
  try {
    const full = await client.get(h.id, h.scope);
    const document = await vscode.workspace.openTextDocument({ content: full.yaml, language: "yaml" });
    await vscode.window.showTextDocument(document, { preview: false });
  } catch (e) {
    vscode.window.showErrorMessage(`불러오기 실패: ${e instanceof Error ? e.message : String(e)}`);
  }
}

export async function deleteFromStore(client: HarnessStoreClient, h: HarnessSummary): Promise<void> {
  const ok = await vscode.window.showWarningMessage(
    `'${h.name || h.id}' 를 저장소에서 삭제할까요? (${h.scope})`,
    { modal: true },
    "삭제",
  );
  if (ok !== "삭제") {
    return;
  }
  try {
    await client.remove(h.id, h.scope);
    vscode.window.setStatusBarMessage(`삭제됨: ${h.id}`, 3000);
  } catch (e) {
    vscode.window.showErrorMessage(`삭제 실패: ${e instanceof Error ? e.message : String(e)}`);
  }
}

function guessId(fileName: string, yaml: string): string {
  const m = yaml.match(/^\s*id:\s*(\S+)/m);
  if (m) {
    return m[1].replace(/["']/g, "");
  }
  const base = fileName.split(/[/\\]/).pop() ?? "harness";
  return base.replace(/\.harness\.ya?ml$|\.ya?ml$/i, "") || "harness";
}

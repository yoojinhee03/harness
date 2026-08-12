import * as vscode from "vscode";
import type { HarnessStoreClient, HarnessSummary } from "./harnessStore";

/** "내 하네스" 사이드바 — 공유 저장소 목록. SSE 이벤트마다 refresh() 로 재조회(라이브). */
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
    item.description = h.id;
    item.iconPath = new vscode.ThemeIcon("cloud");
    item.contextValue = "harnessStoreItem";
    item.tooltip = new vscode.MarkdownString(
      [`**${h.name || h.id}**  \`${h.id}\``, "", h.description || "(설명 없음)", "", `_수정: ${h.updated_at ?? "-"}_`]
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
    try {
      return await this.client.list();
    } catch {
      // 백엔드 미기동 등 — 빈 목록(viewsWelcome)로. 저장/열기 시 구체 오류를 띄운다.
      return [];
    }
  }
}

/** 활성 harness.yaml 을 공유 저장소에 저장(upsert). id/이름을 물어본다. */
export async function saveActiveToStore(client: HarnessStoreClient): Promise<void> {
  const doc = vscode.window.activeTextEditor?.document;
  if (!doc || !/harness\.ya?ml$/.test(doc.fileName)) {
    vscode.window.showWarningMessage("harness.yaml 파일을 연 상태에서 저장하세요.");
    return;
  }
  const yaml = doc.getText();
  const guessedId = guessId(doc.fileName, yaml);
  const id = await vscode.window.showInputBox({
    title: "공유 저장소에 저장 — id",
    value: guessedId,
    prompt: "웹·다른 에디터에서 이 id 로 보입니다",
    ignoreFocusOut: true,
  });
  if (!id) {
    return;
  }
  const name = await vscode.window.showInputBox({
    title: "표시 이름(선택)",
    value: guessedId,
    ignoreFocusOut: true,
  });
  if (name === undefined) {
    return;
  }
  try {
    const saved = await client.put(id, { name, description: "", yaml });
    vscode.window.setStatusBarMessage(`✓ 저장소에 저장됨: ${saved.id}`, 4000);
  } catch (e) {
    vscode.window.showErrorMessage(`저장 실패: ${e instanceof Error ? e.message : String(e)}`);
  }
}

/** 저장소의 하네스를 열어 편집(Untitled yaml). */
export async function openFromStore(client: HarnessStoreClient, h: HarnessSummary): Promise<void> {
  try {
    const full = await client.get(h.id);
    const document = await vscode.workspace.openTextDocument({ content: full.yaml, language: "yaml" });
    await vscode.window.showTextDocument(document, { preview: false });
  } catch (e) {
    vscode.window.showErrorMessage(`불러오기 실패: ${e instanceof Error ? e.message : String(e)}`);
  }
}

export async function deleteFromStore(client: HarnessStoreClient, h: HarnessSummary): Promise<void> {
  const ok = await vscode.window.showWarningMessage(`'${h.name || h.id}' 를 저장소에서 삭제할까요?`, { modal: true }, "삭제");
  if (ok !== "삭제") {
    return;
  }
  try {
    await client.remove(h.id);
    vscode.window.setStatusBarMessage(`삭제됨: ${h.id}`, 3000);
  } catch (e) {
    vscode.window.showErrorMessage(`삭제 실패: ${e instanceof Error ? e.message : String(e)}`);
  }
}

function guessId(fileName: string, yaml: string): string {
  const m = yaml.match(/^\s*id:\s*(\S+)/m); // metadata.id 우선
  if (m) {
    return m[1].replace(/["']/g, "");
  }
  const base = fileName.split(/[/\\]/).pop() ?? "harness";
  return base.replace(/\.harness\.ya?ml$|\.ya?ml$/i, "") || "harness";
}

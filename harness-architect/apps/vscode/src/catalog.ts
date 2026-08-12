import * as vscode from "vscode";
import type { HarnessServer } from "./mcp";

export interface CatalogComponent {
  id: string;
  type: string;
  name: string;
  version: string;
  summary: string;
  provides: string[];
  requires: string[];
  context_tokens: number;
  added_tools: number;
}

type Node =
  | { kind: "type"; type: string; count: number }
  | { kind: "component"; comp: CatalogComponent };

/** 카탈로그를 type 별로 묶어 보여주는 사이드바 트리. list_catalog 를 호출한다. */
export class CatalogProvider implements vscode.TreeDataProvider<Node> {
  private readonly _onDidChange = new vscode.EventEmitter<Node | void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  private comps: CatalogComponent[] = [];
  private loaded = false;

  constructor(private server: HarnessServer) {}

  setServer(server: HarnessServer): void {
    this.server = server;
    this.refresh();
  }

  refresh(): void {
    this.loaded = false;
    this._onDidChange.fire();
  }

  getTreeItem(node: Node): vscode.TreeItem {
    if (node.kind === "type") {
      const item = new vscode.TreeItem(
        `${node.type} (${node.count})`,
        vscode.TreeItemCollapsibleState.Expanded,
      );
      item.iconPath = new vscode.ThemeIcon(iconForType(node.type));
      item.contextValue = "harnessType";
      return item;
    }
    const c = node.comp;
    const item = new vscode.TreeItem(c.name, vscode.TreeItemCollapsibleState.None);
    item.description = `${c.id}@${c.version}`;
    item.iconPath = new vscode.ThemeIcon(iconForType(c.type));
    item.contextValue = "harnessComponent";
    item.tooltip = new vscode.MarkdownString(
      [
        `**${c.name}**  \`${c.id}@${c.version}\``,
        "",
        c.summary,
        "",
        c.provides.length ? `- provides: ${c.provides.map((p) => `\`${p}\``).join(", ")}` : "",
        c.requires.length ? `- requires: ${c.requires.map((p) => `\`${p}\``).join(", ")}` : "",
        `- 비용: ${c.context_tokens} 토큰 · 도구 +${c.added_tools}`,
      ]
        .filter(Boolean)
        .join("\n"),
    );
    item.command = {
      command: "harness.copyRef",
      title: "ref 복사",
      arguments: [`${c.id}@${c.version}`],
    };
    return item;
  }

  async getChildren(node?: Node): Promise<Node[]> {
    if (!node) {
      if (!this.loaded) {
        try {
          const rows = (await this.server.call("list_catalog", {})) as CatalogComponent[];
          this.comps = Array.isArray(rows) ? rows : [];
          this.loaded = true;
        } catch (e) {
          // 서버 경로 오류 등 — 빈 트리(viewsWelcome)로 떨어뜨리고 안내한다.
          this.comps = [];
          const msg = e instanceof Error ? e.message : String(e);
          vscode.window
            .showErrorMessage(`Harness 카탈로그 로드 실패: ${msg}`, "설정 열기")
            .then((c) => c && vscode.commands.executeCommand("workbench.action.openSettings", "harness.serverCommand"));
          return [];
        }
      }
      const types = [...new Set(this.comps.map((c) => c.type))].sort();
      return types.map((type) => ({
        kind: "type",
        type,
        count: this.comps.filter((c) => c.type === type).length,
      }));
    }
    if (node.kind === "type") {
      return this.comps
        .filter((c) => c.type === node.type)
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((comp) => ({ kind: "component", comp }));
    }
    return [];
  }
}

function iconForType(type: string): string {
  switch (type) {
    case "skill":
      return "book";
    case "mcp":
      return "plug";
    case "context":
      return "note";
    case "hook":
      return "zap";
    default:
      return "circle-outline";
  }
}

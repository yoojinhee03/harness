import * as os from "node:os";
import * as vscode from "vscode";
import type { ServerSpec } from "./mcp";

export function workspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

/** 설정 문자열의 `${workspaceFolder}` 와 선행 `~` 를 확장한다. */
export function expand(value: string): string {
  const root = workspaceRoot() ?? "";
  return value
    .replace(/\$\{workspaceFolder\}/g, root)
    .replace(/^~(?=$|[/\\])/, os.homedir());
}

export interface HarnessConfig {
  spec: ServerSpec;
  catalogDir: string;
  defaultTarget: string;
}

export function readConfig(): HarnessConfig {
  const cfg = vscode.workspace.getConfiguration("harness");
  const command = expand(cfg.get<string>("serverCommand") ?? "");
  const args = (cfg.get<string[]>("serverArgs") ?? []).map(expand);
  const catalogDir = expand(cfg.get<string>("catalogDir") ?? "");
  const env: NodeJS.ProcessEnv = { ...process.env };
  if (catalogDir) {
    env.CATALOG_DIR = catalogDir;
  }
  return {
    spec: { command, args, cwd: workspaceRoot(), env },
    catalogDir,
    defaultTarget: cfg.get<string>("defaultTarget") ?? "claude-code",
  };
}

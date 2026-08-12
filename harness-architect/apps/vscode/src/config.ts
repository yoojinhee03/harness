import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
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
  /** 실제로 선택된 서버 출처 — 상태 표시/디버그용. */
  source: "user" | "bundled" | "venv";
}

/** 확장에 동봉된 자립 서버(파이썬 없는 사용자용)가 있으면 그 경로를 돌려준다. */
function bundledServer(extensionPath: string): { bin: string; catalog: string } | undefined {
  const exe = process.platform === "win32" ? "harness-mcp.exe" : "harness-mcp";
  const bin = path.join(extensionPath, "server", "bin", exe);
  if (!fs.existsSync(bin)) {
    return undefined;
  }
  return { bin, catalog: path.join(extensionPath, "server", "catalog") };
}

/** 설정에서 명시적으로(기본값 아님) 지정한 값만 돌려준다. */
function userValue<T>(inspect: ReturnType<vscode.WorkspaceConfiguration["inspect"]> | undefined): T | undefined {
  const i = inspect as { globalValue?: T; workspaceValue?: T; workspaceFolderValue?: T } | undefined;
  return i?.workspaceFolderValue ?? i?.workspaceValue ?? i?.globalValue;
}

/**
 * 서버 실행 사양을 결정한다. 우선순위:
 *   1) 사용자가 명시한 `harness.serverCommand`
 *   2) 확장에 동봉된 자립 바이너리(server/bin) — 파이썬 없는 사용자
 *   3) venv 기본값(모노레포 개발자)
 */
export function readConfig(extensionPath?: string): HarnessConfig {
  const cfg = vscode.workspace.getConfiguration("harness");
  const userCommand = userValue<string>(cfg.inspect("serverCommand"));
  const userCatalog = userValue<string>(cfg.inspect("catalogDir"));
  const serverArgs = (cfg.get<string[]>("serverArgs") ?? []).map(expand);

  let command: string;
  let args: string[];
  let catalogDir: string;
  let source: HarnessConfig["source"];

  const bundled = extensionPath ? bundledServer(extensionPath) : undefined;

  if (userCommand) {
    command = expand(userCommand);
    args = serverArgs;
    catalogDir = userCatalog ? expand(userCatalog) : expand(cfg.get<string>("catalogDir") ?? "");
    source = "user";
  } else if (bundled) {
    command = bundled.bin;
    args = [];
    catalogDir = userCatalog ? expand(userCatalog) : bundled.catalog;
    source = "bundled";
  } else {
    command = expand(cfg.get<string>("serverCommand") ?? "");
    args = serverArgs;
    catalogDir = expand(cfg.get<string>("catalogDir") ?? "");
    source = "venv";
  }

  const env: NodeJS.ProcessEnv = { ...process.env };
  if (catalogDir) {
    env.CATALOG_DIR = catalogDir;
  }

  return {
    spec: { command, args, cwd: workspaceRoot(), env },
    catalogDir,
    defaultTarget: cfg.get<string>("defaultTarget") ?? "claude-code",
    source,
  };
}

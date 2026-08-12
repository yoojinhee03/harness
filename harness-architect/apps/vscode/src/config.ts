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
 *   2) (배포/설치 모드) 확장에 동봉된 자립 바이너리(server/bin) — 파이썬 없는 사용자
 *   3) venv 기본값(모노레포 개발자)
 *
 * devMode(F5 확장 개발 호스트)에서는 동봉 바이너리를 건너뛰고 venv 를 우선한다 —
 * 파이썬 패키지의 변경이 재빌드 없이 바로 반영되도록(동결 바이너리는 옛 코드).
 */
export function readConfig(extensionPath?: string, devMode = false): HarnessConfig {
  const cfg = vscode.workspace.getConfiguration("harness");
  const userCommand = userValue<string>(cfg.inspect("serverCommand"));
  const userCatalog = userValue<string>(cfg.inspect("catalogDir"));
  const serverArgs = (cfg.get<string[]>("serverArgs") ?? []).map(expand);

  let command: string;
  let args: string[];
  let catalogDir: string;
  let source: HarnessConfig["source"];

  // 번들은 확장 경로(절대)라 어느 워크스페이스에서도 존재하면 쓸 수 있다.
  // venv 기본값은 ${workspaceFolder} 상대라 모노레포를 열었을 때만 존재한다 → 존재 여부로 판단.
  const bundled = extensionPath ? bundledServer(extensionPath) : undefined;
  const venvDefault = expand(cfg.get<string>("serverCommand") ?? "");
  const venvExists = venvDefault !== "" && fs.existsSync(venvDefault);
  const venvCatalog = expand(cfg.get<string>("catalogDir") ?? "");

  if (userCommand) {
    command = expand(userCommand);
    args = serverArgs;
    catalogDir = userCatalog ? expand(userCatalog) : venvCatalog;
    source = "user";
  } else {
    // dev: 라이브 venv 우선하되 없으면 번들로 폴백(모노레포 밖 폴더). prod: 번들 우선하되 없으면 venv.
    const order: Array<"venv" | "bundled"> = devMode ? ["venv", "bundled"] : ["bundled", "venv"];
    const pick = order.find((o) => (o === "venv" ? venvExists : !!bundled)) ?? order[0];
    if (pick === "bundled" && bundled) {
      command = bundled.bin;
      args = [];
      catalogDir = userCatalog ? expand(userCatalog) : bundled.catalog;
      source = "bundled";
    } else {
      command = venvDefault;
      args = serverArgs;
      catalogDir = userCatalog ? expand(userCatalog) : venvCatalog;
      source = "venv";
    }
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

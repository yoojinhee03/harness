// harness MCP 서버를 자식 프로세스로 띄우고 stdio JSON-RPC(줄 구분 JSON)로 대화한다.
// 런타임 npm 의존성 0 — MCP stdio 프레이밍이 개행 구분 JSON 이라 손수 구현한다.
import { ChildProcess, spawn } from "node:child_process";
import * as vscode from "vscode";

interface Pending {
  resolve: (v: unknown) => void;
  reject: (e: Error) => void;
}

export interface ServerSpec {
  command: string;
  args: string[];
  cwd?: string;
  env: NodeJS.ProcessEnv;
}

/** MCP 툴 result 봉투에서 실제 반환값을 꺼낸다. dict 반환은 그대로, 비-object 반환은 {result:x} 로 감싸져 옴. */
function unwrap(result: any): unknown {
  const sc = result?.structuredContent;
  if (sc && typeof sc === "object") {
    const keys = Object.keys(sc);
    if (keys.length === 1 && keys[0] === "result") {
      return (sc as { result: unknown }).result;
    }
    return sc;
  }
  const text = (result?.content ?? [])
    .filter((c: any) => c?.type === "text")
    .map((c: any) => c.text)
    .join("");
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export class HarnessServer {
  private proc?: ChildProcess;
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private buffer = "";
  private initialized?: Promise<void>;

  constructor(
    private readonly spec: ServerSpec,
    private readonly output: vscode.OutputChannel,
  ) {}

  private ensureProc(): void {
    if (this.proc && this.proc.exitCode === null && !this.proc.killed) {
      return;
    }
    this.output.appendLine(`[harness] spawn: ${this.spec.command} ${this.spec.args.join(" ")}`);
    const proc = spawn(this.spec.command, this.spec.args, {
      cwd: this.spec.cwd,
      env: this.spec.env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.proc = proc;
    proc.stdout?.on("data", (d: Buffer) => this.onData(d.toString("utf8")));
    proc.stderr?.on("data", (d: Buffer) => this.output.append(`[server] ${d.toString("utf8")}`));
    // 이미 교체된(stale) 프로세스의 늦은 이벤트는 무시 — 현재 proc 일 때만 상태를 정리한다.
    proc.on("error", (err) => {
      if (this.proc === proc) {
        this.fail(err);
      }
    });
    proc.on("exit", (code, signal) => {
      if (this.proc === proc) {
        this.fail(new Error(`서버 종료 (code=${code ?? "?"}, signal=${signal ?? "-"})`));
      }
    });
  }

  private fail(err: Error): void {
    this.output.appendLine(`[harness] ${err.message}`);
    for (const p of this.pending.values()) {
      p.reject(err);
    }
    this.pending.clear();
    this.proc = undefined;
    this.initialized = undefined;
    this.buffer = "";
  }

  private onData(chunk: string): void {
    this.buffer += chunk;
    let idx: number;
    while ((idx = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, idx).trim();
      this.buffer = this.buffer.slice(idx + 1);
      if (!line) {
        continue;
      }
      let msg: any;
      try {
        msg = JSON.parse(line);
      } catch {
        this.output.appendLine(`[harness] 비-JSON 라인 무시: ${line.slice(0, 120)}`);
        continue;
      }
      if (typeof msg.id === "number" && this.pending.has(msg.id)) {
        const p = this.pending.get(msg.id)!;
        this.pending.delete(msg.id);
        if (msg.error) {
          p.reject(new Error(msg.error.message ?? "MCP 오류"));
        } else {
          p.resolve(msg.result);
        }
      }
    }
  }

  private notify(method: string, params?: unknown): void {
    this.ensureProc();
    this.proc!.stdin!.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
  }

  private request(method: string, params?: unknown, timeoutMs = 120000): Promise<unknown> {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`시간 초과: ${method}`));
        }
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (v) => {
          clearTimeout(timer);
          resolve(v);
        },
        reject: (e) => {
          clearTimeout(timer);
          reject(e);
        },
      });
      try {
        this.ensureProc();
        this.proc!.stdin!.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
      } catch (e) {
        this.pending.delete(id);
        clearTimeout(timer);
        reject(e as Error);
      }
    });
  }

  private ensureInitialized(): Promise<void> {
    if (!this.initialized) {
      this.initialized = (async () => {
        await this.request("initialize", {
          protocolVersion: "2025-06-18",
          capabilities: {},
          clientInfo: { name: "harness-vscode", version: "0.1.0" },
        });
        this.notify("notifications/initialized");
      })().catch((e) => {
        this.initialized = undefined;
        throw e;
      });
    }
    return this.initialized;
  }

  /** MCP 툴 호출 → 파싱된 반환값. */
  async call(name: string, args: Record<string, unknown>): Promise<unknown> {
    await this.ensureInitialized();
    const result: any = await this.request("tools/call", { name, arguments: args });
    if (result?.isError) {
      const text = (result.content ?? []).map((c: any) => c.text).join("\n");
      throw new Error(text || `툴 오류: ${name}`);
    }
    return unwrap(result);
  }

  restart(): void {
    this.dispose();
  }

  dispose(): void {
    const proc = this.proc;
    this.fail(new Error("서버 종료(dispose)"));
    proc?.kill();
  }
}

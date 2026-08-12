// 공유 하네스 저장소 클라이언트 — 웹과 같은 FastAPI 백엔드(HTTP)에 Bearer 토큰으로 붙어
// 사용자·팀 스코프로 저장/목록/열기하고, SSE 로 다른 클라이언트의 변경을 실시간으로 받는다.
// (확장은 fetch 기반 SSE 라 Authorization 헤더를 그대로 실을 수 있다 — 웹의 ?token= 과 다름.)
import * as vscode from "vscode";

export interface HarnessSummary {
  id: string;
  scope: string; // "personal:<uid>" | "team:<tid>"
  owner_id: string;
  name: string;
  description: string;
  updated_at: string;
}

export interface HarnessDoc extends HarnessSummary {
  yaml: string;
}

export interface Team {
  id: string;
  name: string;
  owner_id: string;
  members: string[];
}

export interface Account {
  id: string;
  handle: string;
  token: string;
}

export class HarnessStoreClient {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
  ) {}

  hasToken(): boolean {
    return this.token.trim().length > 0;
  }

  private url(path: string): string {
    return `${this.baseUrl.replace(/\/+$/, "")}${path}`;
  }

  private headers(json = false): Record<string, string> {
    const h: Record<string, string> = {};
    if (this.token) {
      h.authorization = `Bearer ${this.token}`;
    }
    if (json) {
      h["content-type"] = "application/json";
    }
    return h;
  }

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const r = await fetch(this.url(path), {
      method,
      headers: this.headers(body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (r.status === 401) {
      throw new Error("인증 필요 — 'Harness Architect: 로그인'으로 토큰을 설정하세요");
    }
    if (!r.ok) {
      throw new Error(`${method} ${path} 실패: HTTP ${r.status}`);
    }
    return (await r.json()) as T;
  }

  // 인증
  register(handle: string): Promise<Account> {
    return this.req<Account>("POST", "/auth/register", { handle });
  }

  // 하네스 (스코프)
  list(): Promise<HarnessSummary[]> {
    return this.req<HarnessSummary[]>("GET", "/harnesses");
  }

  get(id: string, scope: string): Promise<HarnessDoc> {
    return this.req<HarnessDoc>("GET", `/harnesses/${encodeURIComponent(id)}?scope=${encodeURIComponent(scope)}`);
  }

  put(id: string, scope: string, body: { name: string; description: string; yaml: string }): Promise<HarnessDoc> {
    return this.req<HarnessDoc>(
      "PUT",
      `/harnesses/${encodeURIComponent(id)}?scope=${encodeURIComponent(scope)}`,
      body,
    );
  }

  remove(id: string, scope: string): Promise<void> {
    return this.req<void>("DELETE", `/harnesses/${encodeURIComponent(id)}?scope=${encodeURIComponent(scope)}`);
  }

  // 팀
  teams(): Promise<Team[]> {
    return this.req<Team[]>("GET", "/teams");
  }

  createTeam(name: string): Promise<Team> {
    return this.req<Team>("POST", "/teams", { name });
  }

  addMember(tid: string, handle: string): Promise<Team> {
    return this.req<Team>("POST", `/teams/${encodeURIComponent(tid)}/members`, { handle });
  }
}

/**
 * `/harnesses/events` SSE 를 Bearer 토큰으로 구독한다. 어떤 이벤트든 onEvent 로 알린다.
 * 연결이 끊기면 백오프 후 자동 재연결. dispose 로 중단.
 */
export function connectEvents(
  baseUrl: string,
  token: string,
  onEvent: (type: string) => void,
  output: vscode.OutputChannel,
): vscode.Disposable {
  let disposed = false;
  let controller: AbortController | undefined;
  let retryTimer: ReturnType<typeof setTimeout> | undefined;
  const url = `${baseUrl.replace(/\/+$/, "")}/harnesses/events`;

  const loop = async (): Promise<void> => {
    while (!disposed) {
      if (!token) {
        return; // 토큰 없으면 구독 안 함(로그인 후 재연결).
      }
      controller = new AbortController();
      try {
        const resp = await fetch(url, {
          headers: { accept: "text/event-stream", authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) {
          throw new Error(`SSE HTTP ${resp.status}`);
        }
        output.appendLine(`[store] SSE 연결됨: ${url}`);
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!disposed) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          // SSE 프레임 경계는 빈 줄 — sse-starlette 는 CRLF 를 쓰므로 \r?\n\r?\n 로 자른다.
          const boundary = /\r?\n\r?\n/;
          let m: RegExpExecArray | null;
          while ((m = boundary.exec(buffer)) !== null) {
            const frame = buffer.slice(0, m.index);
            buffer = buffer.slice(m.index + m[0].length);
            let type = "message";
            for (const line of frame.split(/\r?\n/)) {
              if (line.startsWith("event:")) {
                type = line.slice(6).trim();
              }
            }
            onEvent(type);
          }
        }
      } catch (e) {
        if (!disposed) {
          const msg = e instanceof Error ? e.message : String(e);
          output.appendLine(`[store] SSE 끊김(${msg}) — 3초 후 재연결`);
        }
      }
      if (disposed) {
        break;
      }
      await new Promise<void>((resolve) => {
        retryTimer = setTimeout(resolve, 3000);
      });
    }
  };

  void loop();

  return {
    dispose() {
      disposed = true;
      controller?.abort();
      if (retryTimer) {
        clearTimeout(retryTimer);
      }
    },
  };
}

// 공유 하네스 저장소 클라이언트 — 웹과 같은 FastAPI 백엔드(HTTP)에 붙어 저장/목록/열기하고,
// SSE 로 다른 클라이언트(웹·다른 에디터)의 변경을 실시간으로 받는다. Node fetch 스트리밍 사용.
import * as vscode from "vscode";

export interface HarnessSummary {
  id: string;
  name: string;
  description: string;
  updated_at: string;
}

export interface HarnessDoc extends HarnessSummary {
  yaml: string;
}

export class HarnessStoreClient {
  constructor(private readonly baseUrl: string) {}

  private url(path: string): string {
    return `${this.baseUrl.replace(/\/+$/, "")}${path}`;
  }

  async list(): Promise<HarnessSummary[]> {
    const r = await fetch(this.url("/harnesses"));
    if (!r.ok) {
      throw new Error(`목록 실패: HTTP ${r.status}`);
    }
    return (await r.json()) as HarnessSummary[];
  }

  async get(id: string): Promise<HarnessDoc> {
    const r = await fetch(this.url(`/harnesses/${encodeURIComponent(id)}`));
    if (!r.ok) {
      throw new Error(`불러오기 실패: HTTP ${r.status}`);
    }
    return (await r.json()) as HarnessDoc;
  }

  async put(id: string, body: { name: string; description: string; yaml: string }): Promise<HarnessDoc> {
    const r = await fetch(this.url(`/harnesses/${encodeURIComponent(id)}`), {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      throw new Error(`저장 실패: HTTP ${r.status}`);
    }
    return (await r.json()) as HarnessDoc;
  }

  async remove(id: string): Promise<void> {
    const r = await fetch(this.url(`/harnesses/${encodeURIComponent(id)}`), { method: "DELETE" });
    if (!r.ok) {
      throw new Error(`삭제 실패: HTTP ${r.status}`);
    }
  }
}

/**
 * `/harnesses/events` SSE 를 구독한다. 어떤 이벤트든 onEvent 로 알려(트리 새로고침용) 준다.
 * 연결이 끊기면 백오프 후 자동 재연결. dispose 로 중단.
 */
export function connectEvents(
  baseUrl: string,
  onEvent: (type: string) => void,
  output: vscode.OutputChannel,
): vscode.Disposable {
  let disposed = false;
  let controller: AbortController | undefined;
  let retryTimer: ReturnType<typeof setTimeout> | undefined;
  const url = `${baseUrl.replace(/\/+$/, "")}/harnesses/events`;

  const loop = async (): Promise<void> => {
    while (!disposed) {
      controller = new AbortController();
      try {
        const resp = await fetch(url, {
          headers: { accept: "text/event-stream" },
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

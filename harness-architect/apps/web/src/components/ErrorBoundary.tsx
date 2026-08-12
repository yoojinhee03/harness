import { Component, type ErrorInfo, type ReactNode } from "react";

/** 렌더 오류를 잡아 백지 대신 복구 화면을 보여준다(제품 견고화). */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI 오류:", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex h-full items-center justify-center bg-bg px-6 text-fg">
        <div className="w-full max-w-md text-center">
          <div className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl bg-err/15 text-err">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 9v4M12 17h.01M10.3 3.9l-8 13.9A2 2 0 004 21h16a2 2 0 001.7-3.2l-8-13.9a2 2 0 00-3.4 0z" />
            </svg>
          </div>
          <h1 className="text-base font-semibold">문제가 발생했어요</h1>
          <p className="mt-1 text-sm text-muted">화면을 그리는 중 오류가 났습니다. 새로고침하면 대부분 해결됩니다.</p>
          <pre className="mt-3 overflow-x-auto rounded-lg border border-line bg-surface p-3 text-left text-xs text-muted">
            {this.state.error.message}
          </pre>
          <button
            onClick={() => location.reload()}
            className="mt-4 h-9 rounded-lg bg-accent px-4 text-sm font-medium text-accent-fg hover:bg-accent-hover"
          >
            새로고침
          </button>
        </div>
      </div>
    );
  }
}

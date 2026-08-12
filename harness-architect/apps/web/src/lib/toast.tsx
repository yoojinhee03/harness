// 토스트 알림 — 액션 피드백(저장·복사·삭제·오류). 우하단 스택, 자동 소멸.
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

type ToastKind = "success" | "error" | "info";
interface Toast {
  id: number;
  kind: ToastKind;
  msg: string;
}

const Ctx = createContext<(msg: string, kind?: ToastKind) => void>(() => undefined);

export function useToast() {
  return useContext(Ctx);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);

  const push = useCallback((msg: string, kind: ToastKind = "success") => {
    const id = ++seq.current;
    setToasts((t) => [...t, { id, kind, msg }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);
  }, []);

  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex items-start gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm shadow-panel"
            role="status"
          >
            <span
              className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${
                t.kind === "success" ? "bg-ok" : t.kind === "error" ? "bg-err" : "bg-accent"
              }`}
            />
            <span className="text-fg/90">{t.msg}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

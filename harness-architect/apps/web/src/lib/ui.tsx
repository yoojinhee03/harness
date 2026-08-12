import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import type { ComponentType, Severity } from "../api/client";

export const TYPE_LABEL: Record<ComponentType, string> = {
  mcp: "MCP",
  skill: "Skill",
  context: "Context",
  hook: "Hook",
};

// 타입별 색 — 토큰 위에 얹는 은은한 배지(다크/라이트 공용, 반투명).
export const TYPE_COLOR: Record<ComponentType, string> = {
  mcp: "bg-sky-500/15 text-sky-400",
  skill: "bg-violet-500/15 text-violet-400",
  context: "bg-amber-500/15 text-amber-400",
  hook: "bg-rose-500/15 text-rose-400",
};

function cx(...parts: (string | false | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "subtle" | "danger";
  size?: "sm" | "md";
};

export function Button({ variant = "primary", size = "md", className, ...props }: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:opacity-40 disabled:pointer-events-none";
  const sizes = { sm: "h-7 px-2.5 text-xs", md: "h-9 px-3.5 text-sm" };
  const variants = {
    primary: "bg-accent text-accent-fg hover:bg-accent-hover",
    ghost: "text-fg/80 hover:text-fg hover:bg-surface-2",
    subtle: "bg-surface-2 text-fg hover:bg-line",
    danger: "text-err hover:bg-err/10",
  };
  return <button className={cx(base, sizes[size], variants[variant], className)} {...props} />;
}

export function IconButton({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cx(
        "grid h-8 w-8 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-fg",
        className,
      )}
      {...props}
    />
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-xl border border-line bg-surface p-4", className)}>{children}</div>;
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cx(
        "h-9 w-full rounded-lg border border-line bg-surface-2 px-3 text-sm text-fg placeholder:text-muted/70",
        "focus:border-accent/60 focus:outline-none",
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cx(
        "w-full resize-none rounded-lg border border-line bg-surface-2 p-3 text-sm text-fg placeholder:text-muted/70",
        "focus:border-accent/60 focus:outline-none",
        className,
      )}
      {...props}
    />
  );
}

export function Badge({ children, className = "bg-surface-2 text-muted" }: { children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", className)}>
      {children}
    </span>
  );
}

// 별칭 — 기존 코드 호환(둥근 pill)
export function Chip({ children, className = "bg-surface-2 text-muted" }: { children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", className)}>
      {children}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-muted">
      {children}
    </kbd>
  );
}

export function SeverityDot({ severity }: { severity: Severity | "ok" }) {
  const color = severity === "error" ? "bg-err" : severity === "ok" ? "bg-ok" : "bg-warn";
  return <span className={cx("inline-block h-2 w-2 rounded-full", color)} />;
}

export function Spinner() {
  return (
    <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-muted/30 border-t-fg" />
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-[15px] font-semibold text-fg">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-6 py-10 text-center">
      <p className="text-sm text-fg">{title}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export const codeBlock =
  "overflow-x-auto rounded-lg border border-line bg-[rgb(var(--bg))] p-3 text-xs leading-relaxed text-fg/90";

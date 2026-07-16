import type { ComponentType, Severity } from "../api/client";

export const TYPE_LABEL: Record<ComponentType, string> = {
  mcp: "MCP",
  skill: "Skill",
  context: "Context",
  hook: "Hook",
};

export const TYPE_COLOR: Record<ComponentType, string> = {
  mcp: "bg-sky-100 text-sky-700",
  skill: "bg-violet-100 text-violet-700",
  context: "bg-amber-100 text-amber-700",
  hook: "bg-rose-100 text-rose-700",
};

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost";
  type?: "button" | "submit";
}) {
  const base = "px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed";
  const styles =
    variant === "primary"
      ? "bg-slate-900 text-white hover:bg-slate-700"
      : "bg-white text-slate-700 border border-slate-300 hover:bg-slate-100";
  return (
    <button type={type} className={`${base} ${styles}`} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

export function Chip({
  children,
  className = "bg-slate-100 text-slate-700",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

export function SeverityDot({ severity }: { severity: Severity | "ok" }) {
  const color =
    severity === "error" ? "bg-err" : severity === "ok" ? "bg-ok" : "bg-warn";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />;
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>{children}</div>;
}

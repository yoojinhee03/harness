// 다크/라이트 테마 — <html data-theme> 에 적용, localStorage 영속. 기본 다크.
import { useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "harness.theme";

export function initTheme(): Theme {
  const saved = (localStorage.getItem(KEY) as Theme | null) ?? "dark";
  document.documentElement.setAttribute("data-theme", saved);
  return saved;
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem(KEY) as Theme | null) ?? "dark");
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(KEY, theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

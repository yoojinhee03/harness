/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 진단 유형 색 체계 — 충족(초록)/경고·gap(앰버)/오류(빨강). 공통 UI 원칙.
        ok: { DEFAULT: "#16a34a", bg: "#f0fdf4", border: "#bbf7d0" },
        warn: { DEFAULT: "#d97706", bg: "#fffbeb", border: "#fde68a" },
        err: { DEFAULT: "#dc2626", bg: "#fef2f2", border: "#fecaca" },
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        "surface-2": token("surface-2"),
        line: token("line"),
        fg: token("fg"),
        muted: token("muted"),
        accent: token("accent"),
        "accent-hover": token("accent-hover"),
        "accent-fg": token("accent-fg"),
        ok: token("ok"),
        warn: token("warn"),
        err: token("err"),
      },
      borderRadius: {
        lg: "8px",
        xl: "10px",
        "2xl": "14px",
      },
      fontSize: {
        xs: ["11px", "16px"],
        sm: ["13px", "18px"],
      },
      boxShadow: {
        panel: "0 1px 2px rgb(0 0 0 / 0.06), 0 8px 24px rgb(0 0 0 / 0.18)",
      },
    },
  },
  plugins: [],
};

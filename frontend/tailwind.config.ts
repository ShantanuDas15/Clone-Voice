import type { Config } from "tailwindcss";

// Colours are CSS variables (app/globals.css) so light, dark and the user's override share one
// set of utilities. Do not use `dark:` variants: the theme is chosen by `data-theme`, not by
// the media query alone (tests/theme.test.ts fails on `dark:` in app/ and components/).
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // §4.4: control 6 px, card and dialog 10 px; `rounded-full` is the pill. Nothing else is allowed
      // (tests/theme.test.ts).
      borderRadius: { DEFAULT: "6px", lg: "10px" },
      colors: {
        background: "hsl(var(--background) / <alpha-value>)",
        surface: "hsl(var(--surface) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        muted: "hsl(var(--muted) / <alpha-value>)",
        "muted-foreground": "hsl(var(--muted-foreground) / <alpha-value>)",
        border: "hsl(var(--border) / <alpha-value>)",
        line: "hsl(var(--line) / <alpha-value>)",
        primary: "hsl(var(--primary) / <alpha-value>)",
        "primary-foreground": "hsl(var(--primary-foreground) / <alpha-value>)",
        danger: "hsl(var(--danger) / <alpha-value>)",
        "danger-foreground": "hsl(var(--danger-foreground) / <alpha-value>)",
        success: "hsl(var(--success) / <alpha-value>)",
        warning: "hsl(var(--warning) / <alpha-value>)",
        "warning-foreground": "hsl(var(--warning-foreground) / <alpha-value>)",
      },
      // Motion tokens (UX plan §4.5): `fast` for feedback to a press or toggle, `base` for things
      // appearing. All collapse under prefers-reduced-motion (app/globals.css).
      transitionDuration: { fast: "120ms", base: "200ms" },
      // Allowed motion only (§4.10): the indeterminate bar while a request is in flight, a dialog
      // appearing, and the one-time waveform draw-in when a generated take finishes.
      keyframes: {
        indeterminate: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(300%)" },
        },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "draw-in": {
          from: { opacity: "0", transform: "scaleY(0.15)" },
          to: { opacity: "1", transform: "scaleY(1)" },
        },
        // The home page only (§4.10, §12.19): the sample card rises once, its side bars draw once
        // (transform only, so each bar keeps its own opacity), and the background ribbons drift.
        rise: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "none" },
        },
        "bar-in": { from: { transform: "scaleY(0)" }, to: { transform: "none" } },
        drift: { from: { transform: "translateX(0)" }, to: { transform: "translateX(-50%)" } },
      },
      animation: {
        indeterminate: "indeterminate 1.4s ease-in-out infinite",
        "fade-in": "fade-in 200ms ease-out both",
        "draw-in": "draw-in 350ms ease-out both",
        rise: "rise 200ms cubic-bezier(0.2, 0.7, 0.2, 1) both",
        "bar-in": "bar-in 380ms cubic-bezier(0.2, 0.7, 0.2, 1) both",
        "drift-slow": "drift 26s linear infinite",
        "drift-mid": "drift 38s linear infinite reverse",
        "drift-long": "drift 52s linear infinite",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;

"use client";

import { useEffect, useState } from "react";

import { type Theme, applyTheme, nextTheme, syncThemeColor } from "@/lib/theme";

const LABEL: Record<Theme, string> = { system: "System", light: "Light", dark: "Dark" };

function Icon({ theme }: { theme: Theme }) {
  const common = {
    width: 20,
    height: 20,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
  };
  if (theme === "light") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    );
  }
  if (theme === "dark") {
    return (
      <svg {...common}>
        <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  );
}

/**
 * Cycles System → Light → Dark. The icon shows the *selected mode*, so "System" is never confused
 * with whatever the OS currently resolves to. `initial` comes from the server (the cookie), so the
 * first render already matches the page and nothing shifts or flashes.
 */
export function ThemeToggle({ initial }: { initial: Theme }) {
  const [theme, setTheme] = useState<Theme>(initial);
  const [announcement, setAnnouncement] = useState("");

  // Keep the browser-chrome colour right on load, and when the OS flips while following it.
  useEffect(() => {
    syncThemeColor(theme);
    if (theme !== "system" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => syncThemeColor("system");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [theme]);

  const upcoming = nextTheme(theme);

  return (
    <>
      <button
        type="button"
        onClick={() => {
          applyTheme(upcoming);
          setTheme(upcoming);
          setAnnouncement(`Theme set to ${LABEL[upcoming].toLowerCase()}.`);
        }}
        aria-label={`Theme: ${LABEL[theme]}. Switch to ${LABEL[upcoming].toLowerCase()}.`}
        title={`Theme: ${LABEL[theme]}`}
        className="inline-flex h-11 w-11 items-center justify-center rounded border border-line"
      >
        <Icon theme={theme} />
      </button>
      <span role="status" className="sr-only">
        {announcement}
      </span>
    </>
  );
}

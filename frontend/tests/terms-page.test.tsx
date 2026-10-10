import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import TermsPage, { metadata } from "@/app/(public)/terms/page";
import { TERMS_SECTIONS, TERMS_STATUS, TERMS_VERSION } from "@/lib/terms-content";

describe("terms page", () => {
  it("is on the same version the backend makes users consent to", () => {
    const config = readFileSync(path.resolve(__dirname, "../../backend/core/config.py"), "utf8");
    const backend = /TERMS_VERSION:\s*str\s*=\s*"([^"]+)"/.exec(config)?.[1];
    expect(backend).toBeTruthy();
    expect(TERMS_VERSION).toBe(backend);
  });

  it("renders one h1, the version and every section", () => {
    render(<TermsPage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByText(TERMS_VERSION)).toBeInTheDocument();
    for (const s of TERMS_SECTIONS) {
      expect(screen.getByRole("heading", { level: 2, name: s.heading })).toBeInTheDocument();
    }
  });

  it("says it is a draft, and is kept out of search, until it is published", () => {
    render(<TermsPage />);
    if (TERMS_STATUS === "draft") {
      expect(screen.getByRole("status")).toHaveTextContent(/draft/i);
      expect(metadata.robots).toEqual({ index: false, follow: false });
    } else {
      expect(screen.queryByText(/draft/i)).not.toBeInTheDocument();
    }
  });

  it("does not pull in the mono font, which would add a late font request to a text page", () => {
    // The mono face is `preload: false`, so its first use is requested after the scripts; on the
    // CI runner that pushed /terms over the LCP budget (FE-UX42). Mono is for timecodes.
    const page = readFileSync(path.resolve(__dirname, "../app/(public)/terms/page.tsx"), "utf8");
    expect(page).not.toMatch(/font-mono/);
  });

  it("makes no promise about a retention figure that the server owns", () => {
    const text = TERMS_SECTIONS.map((s) => s.body).join(" ");
    expect(text).not.toMatch(/\b\d+\s*(day|days|hour|hours)\b/i);
  });
});

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Logo } from "@/components/logo";
import { BRAND_NAME } from "@/lib/brand";

const ROOT = path.resolve(__dirname, "..");
function sources(dir: string): string[] {
  return readdirSync(path.join(ROOT, dir)).flatMap((name) => {
    const rel = path.join(dir, name);
    if (statSync(path.join(ROOT, rel)).isDirectory()) return sources(rel);
    return /\.(ts|tsx)$/.test(name) ? [rel] : [];
  });
}

describe("product name", () => {
  it("is defined once, so a rename is a one-line change", () => {
    expect(BRAND_NAME).toBe("CloneVoice");
    const offenders = ["app", "components", "lib", "hooks"]
      .flatMap(sources)
      .filter((f) => f !== path.join("lib", "brand.ts"))
      .filter((f) =>
        readFileSync(path.join(ROOT, f), "utf8")
          .split("\n")
          // Comments may name the product; code and strings may not.
          .filter((line) => !/^\s*(\/\/|\/?\*)/.test(line))
          .some((line) => line.includes("CloneVoice")),
      );
    expect(offenders).toEqual([]);
  });

  it("is what the logo shows", () => {
    render(<Logo />);
    expect(screen.getByText(BRAND_NAME)).toBeInTheDocument();
  });
});

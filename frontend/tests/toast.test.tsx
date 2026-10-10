import { render, screen } from "@testing-library/react";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { ToastHost } from "@/components/toast-host";
import { notify } from "@/lib/toast";

describe("lazy toasts", () => {
  it("shows a toast raised after the host mounted", async () => {
    render(<ToastHost />);
    notify.success("Name updated.");
    expect(await screen.findByText("Name updated.")).toBeInTheDocument();
  });

  it("shows several toasts, including one raised once the library is loaded", async () => {
    render(<ToastHost />);
    notify.error("Couldn't delete that voice.");
    expect(await screen.findByText("Couldn't delete that voice.")).toBeInTheDocument();
    notify.success("Deleted “A”.");
    expect(await screen.findByText("Deleted “A”.")).toBeInTheDocument();
  });

  it("keeps a toast raised before the host mounted and shows it once it does", async () => {
    notify.success("Raised early.");
    render(<ToastHost />);
    expect(await screen.findByText("Raised early.")).toBeInTheDocument();
  });

  it("keeps sonner out of every route bundle: only the host imports it", () => {
    const root = path.resolve(__dirname, "..");
    const walk = (dir: string): string[] =>
      readdirSync(path.join(root, dir)).flatMap((n) => {
        const rel = path.join(dir, n);
        if (statSync(path.join(root, rel)).isDirectory()) return walk(rel);
        return /\.tsx?$/.test(n) ? [rel] : [];
      });
    const importers = ["app", "components", "lib", "hooks"]
      .flatMap(walk)
      .filter((f) =>
        /from "sonner"|import\("sonner"\)/.test(readFileSync(path.join(root, f), "utf8")),
      );
    expect(importers).toEqual([path.join("components", "toast-host.tsx")]);
  });
});

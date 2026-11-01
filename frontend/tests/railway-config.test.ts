import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = (name: string) => readFileSync(path.resolve(__dirname, "../..", name), "utf8");

/** Value of a top-level `key = ...` line in a small TOML file. */
const toml = (text: string, key: string) =>
  new RegExp(`^${key}\\s*=\\s*(.+)$`, "m").exec(text)?.[1]?.trim();

describe("web app Railway config (RAILWAY_READINESS_REPORT.md F-02)", () => {
  const config = root("frontend/railway.toml");
  const dockerfile = root("frontend/Dockerfile");

  it("builds frontend/Dockerfile from the repo root", () => {
    expect(toml(config, "builder")).toBe('"DOCKERFILE"');
    const dockerfilePath = toml(config, "dockerfilePath")?.replaceAll('"', "") ?? "";
    expect(dockerfilePath).toBe("frontend/Dockerfile");
    expect(existsSync(path.resolve(__dirname, "../..", dockerfilePath))).toBe(true);
  });

  it("health-checks a public route that exists", () => {
    expect(toml(config, "healthcheckPath")).toBe('"/login"');
    expect(existsSync(path.resolve(__dirname, "../app/(public)/login/page.tsx"))).toBe(true);
  });

  it("takes every build-time NEXT_PUBLIC_* variable as a build argument", () => {
    for (const name of [
      "NEXT_PUBLIC_API_BASE_URL",
      "NEXT_PUBLIC_APP_ORIGIN",
      "NEXT_PUBLIC_SENTRY_DSN",
    ]) {
      expect(dockerfile).toContain(`ARG ${name}`);
      expect(dockerfile).toContain(`${name}=$${name}`);
    }
  });

  it("runs unprivileged, in production mode, on the Node major CI uses", () => {
    expect(dockerfile).toMatch(/^USER node$/m);
    expect(dockerfile).toContain("NODE_ENV=production");
    const nvmrc = root("frontend/.nvmrc").trim();
    expect(dockerfile).toMatch(new RegExp(`^FROM node:${nvmrc}-slim@sha256:[0-9a-f]{64}`, "m"));
  });

  it("keeps host build output and secrets out of the build context", () => {
    const ignore = root(".dockerignore");
    for (const entry of ["frontend/node_modules/", "frontend/.next/", "frontend/.env*"]) {
      expect(ignore).toContain(entry);
    }
  });
});

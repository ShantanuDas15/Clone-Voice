import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/errors";
import { isReportableApiError } from "@/lib/observability/lazy";
import { scrubEvent, scrubRoute, scrubString } from "@/lib/observability/scrub";

const JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlc2lnbg";
const RESET_TOKEN = "dGhpcy1pcy1hLXJlc2V0LXRva2VuLXRoYXQtaXMtbG9uZw";

describe("scrubString", () => {
  it("redacts emails, JWTs and long opaque tokens", () => {
    const out = scrubString(`fail for jane.doe+x@example.com with ${JWT} and ${RESET_TOKEN}`);
    expect(out).toBe("fail for [email] with [token] and [token]");
  });

  it("leaves ordinary messages and short ids alone", () => {
    expect(scrubString("Cannot read properties of undefined (reading 'id')")).toBe(
      "Cannot read properties of undefined (reading 'id')",
    );
    expect(scrubString("status 503 req abc123")).toBe("status 503 req abc123");
  });
});

describe("scrubRoute", () => {
  it("drops origin, query and fragment and masks ids and tokens", () => {
    expect(
      scrubRoute(`https://app.example.com/verify-email?email=a@b.co#token=${RESET_TOKEN}`),
    ).toBe("/verify-email");
    expect(scrubRoute("/profile/3f2c1a9e-1b2c-4d5e-8f90-a1b2c3d4e5f6/edit")).toBe(
      "/profile/:id/edit",
    );
    expect(scrubRoute(`/reset/${RESET_TOKEN}`)).toBe("/reset/:token");
  });
});

describe("scrubEvent", () => {
  const dirty = {
    event_id: "e1",
    level: "error",
    message: "boom for jane@example.com",
    user: { email: "jane@example.com", ip_address: "1.2.3.4", id: "u1" },
    request: {
      url: `https://app.example.com/reset-password#token=${RESET_TOKEN}`,
      query_string: "email=jane@example.com",
      cookies: { refresh: "secret" },
      headers: { Authorization: `Bearer ${JWT}` },
      data: { text: "my private synthesis text", password: "hunter2" },
    },
    extra: { input_text: "my private synthesis text" },
    contexts: { device: { name: "x" } },
    breadcrumbs: [{ category: "ui.input", message: "typed jane@example.com" }],
    tags: { route: "/dashboard", status: 500, secret: "nope", email: "jane@example.com" },
    transaction: "https://app.example.com/profile/3f2c1a9e-1b2c-4d5e-8f90-a1b2c3d4e5f6?x=1",
    exception: {
      values: [
        {
          type: "TypeError",
          value: `bad token ${JWT}`,
          stacktrace: {
            frames: [
              {
                filename: "https://app.example.com/_next/static/chunks/app.js?v=jane@example.com",
                function: "f",
                lineno: 3,
                colno: 9,
                in_app: true,
                vars: { password: "hunter2" },
              },
            ],
          },
        },
      ],
    },
  };

  it("keeps no user, request, breadcrumb, extra or context data", () => {
    const clean = scrubEvent(dirty) as Record<string, unknown>;
    for (const key of ["user", "request", "extra", "contexts", "breadcrumbs"]) {
      expect(clean).not.toHaveProperty(key);
    }
  });

  it("emits nothing identifying anywhere in the serialized event", () => {
    const json = JSON.stringify(scrubEvent(dirty));
    for (const secret of [
      "jane",
      "example.com/reset",
      "hunter2",
      "private synthesis",
      "1.2.3.4",
      JWT,
      RESET_TOKEN,
      "Bearer",
      "secret",
      "3f2c1a9e",
    ]) {
      expect(json).not.toContain(secret);
    }
  });

  it("keeps the useful, non-identifying fields", () => {
    const clean = scrubEvent(dirty) as unknown as {
      event_id: string;
      level: string;
      message: string;
      tags: Record<string, string>;
      transaction: string;
      exception: { values: { type: string; stacktrace: { frames: Record<string, unknown>[] } }[] };
    };
    expect(clean.event_id).toBe("e1");
    expect(clean.level).toBe("error");
    expect(clean.message).toBe("boom for [email]");
    expect(clean.tags).toEqual({ route: "/dashboard", status: "500" });
    expect(clean.transaction).toBe("/profile/:id");
    const frame = clean.exception.values[0]!.stacktrace.frames[0]!;
    expect(frame).toMatchObject({ filename: "/_next/static/chunks/app.js", lineno: 3, colno: 9 });
    expect(frame).not.toHaveProperty("vars");
  });

  it("tolerates an empty or oddly shaped event", () => {
    expect(scrubEvent({})).toEqual({});
    expect(() => scrubEvent({ exception: "x", tags: 5, message: 3 })).not.toThrow();
  });
});

describe("isReportableApiError", () => {
  const err = (status: number) => new ApiError({ status, kind: "SERVER", message: "m" });

  it("reports server faults only, not user, auth or network conditions", () => {
    expect(isReportableApiError(err(500))).toBe(true);
    expect(isReportableApiError(err(503))).toBe(true);
    for (const status of [0, 401, 403, 404, 409, 422, 429]) {
      expect(isReportableApiError(err(status))).toBe(false);
    }
    expect(isReportableApiError(new Error("x"))).toBe(false);
  });
});

describe("reporting guardrails", () => {
  const ROOT = path.resolve(__dirname, "..");
  const read = (rel: string) => readFileSync(path.join(ROOT, rel), "utf8");

  it("imports the SDK only dynamically so it stays out of the initial JS budget", () => {
    const report = read("lib/observability/report.ts");
    expect(report).toMatch(/import\("@sentry\/browser"\)/);
    expect(report).not.toMatch(/^import .* from "@sentry\/browser"/m);
  });

  it("runs the SDK with no default integrations, no breadcrumbs and the scrubber", () => {
    const report = read("lib/observability/report.ts");
    expect(report).toContain("defaultIntegrations: false");
    expect(report).toContain("sendDefaultPii: false");
    expect(report).toContain("beforeBreadcrumb: () => null");
    expect(report).toContain("beforeSend: (event) => scrubEvent(event)");
  });
});

describe("initial-bundle guardrail", () => {
  it("keeps the reporter out of every statically imported module", () => {
    const ROOT = path.resolve(__dirname, "..");
    for (const rel of [
      "app/error.tsx",
      "app/global-error.tsx",
      "lib/query.ts",
      "lib/observability/lazy.ts",
      "components/providers.tsx",
    ]) {
      expect(readFileSync(path.join(ROOT, rel), "utf8"), rel).not.toMatch(
        /^import .*["']@\/lib\/observability\/report["']/m,
      );
    }
  });
});

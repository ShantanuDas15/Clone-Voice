import { describe, expect, it } from "vitest";

import { ApiError, normalizeError, parseRetryAfter } from "@/lib/errors";

describe("normalizeError", () => {
  it("handles {detail: string}", async () => {
    const e = await normalizeError({ status: 404, data: { detail: "Voice profile not found" } });
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status: 404, kind: "NOT_FOUND", message: "Voice profile not found" });
  });

  it("maps {detail: [...]} validation errors to fields", async () => {
    const e = await normalizeError({
      status: 422,
      data: {
        detail: [
          {
            loc: ["body", "text"],
            msg: "Value error, Text contains characters unsupported",
            type: "value_error",
          },
          { loc: ["body", "name"], msg: "String should have at least 1 character", type: "x" },
        ],
      },
    });
    expect(e.kind).toBe("VALIDATION");
    expect(e.fieldErrors).toEqual([
      { field: "text", message: "Text contains characters unsupported" },
      { field: "name", message: "String should have at least 1 character" },
    ]);
    expect(e.message).toBe("Text contains characters unsupported");
  });

  it("handles slowapi {error: string} 429 with Retry-After", async () => {
    const e = await normalizeError({
      status: 429,
      data: { error: "Rate limit exceeded: 5 per 1 minute" },
      headers: { "Retry-After": "42" },
    });
    expect(e).toMatchObject({ kind: "RATE_LIMITED", retryAfterSec: 42 });
    expect(e.message).toContain("Rate limit exceeded");
  });

  it("classifies a 'service busy' 429 as BUSY", async () => {
    const e = await normalizeError({ status: 429, data: { detail: "Service busy, try again" } });
    expect(e.kind).toBe("BUSY");
  });

  it("decodes Blob JSON bodies", async () => {
    const blob = new Blob([JSON.stringify({ detail: "Profile is not ready" })], {
      type: "application/json",
    });
    const e = await normalizeError({ status: 409, data: blob });
    expect(e).toMatchObject({ kind: "PROFILE_NOT_READY", message: "Profile is not ready" });
  });

  it("handles Blob non-JSON bodies", async () => {
    const e = await normalizeError({ status: 400, data: new Blob(["plain text"]) });
    expect(e.message).toBe("plain text");
  });

  it("handles empty bodies with a default message", async () => {
    const e = await normalizeError({ status: 404, data: "" });
    expect(e).toMatchObject({ kind: "NOT_FOUND", message: "That item no longer exists." });
  });

  it("never echoes server text for 5xx", async () => {
    const e = await normalizeError({ status: 500, data: "Traceback (most recent call last) ..." });
    expect(e.kind).toBe("SERVER");
    expect(e.message).not.toContain("Traceback");
  });

  it("maps 503 to BUSY and keeps Retry-After", async () => {
    const e = await normalizeError({
      status: 503,
      data: { detail: "db down" },
      headers: { "retry-after": "5" },
    });
    expect(e).toMatchObject({ kind: "BUSY", retryAfterSec: 5 });
  });

  it.each([
    [403, "Email address not verified", "EMAIL_UNVERIFIED"],
    [403, "Incorrect password", "BAD_PASSWORD"],
    [403, "Not authorized to use this voice profile", "FORBIDDEN"],
    [409, "The terms have changed", "TERMS_CHANGED"],
    [409, "Voice profile is not ready", "PROFILE_NOT_READY"],
    [409, "Email already registered", "CONFLICT"],
  ] as const)("disambiguates %i %s", async (status, detail, kind) => {
    expect((await normalizeError({ status, data: { detail } })).kind).toBe(kind);
  });

  it("does not show server text for 401", async () => {
    const e = await normalizeError({
      status: 401,
      data: { detail: "Could not validate credentials" },
    });
    expect(e.kind).toBe("UNAUTHENTICATED");
    expect(e.message).toBe("Your session has expired. Please sign in again.");
  });

  it.each(["NETWORK", "TIMEOUT", "CANCELLED"] as const)(
    "handles status 0 code %s",
    async (code) => {
      const e = await normalizeError({ status: 0, code });
      expect(e).toMatchObject({ status: 0, kind: code });
    },
  );

  it("captures X-Request-ID when exposed", async () => {
    const e = await normalizeError({ status: 500, headers: { "X-Request-ID": "abc" } });
    expect(e.requestId).toBe("abc");
  });
});

describe("parseRetryAfter", () => {
  it("parses seconds, dates, and junk", () => {
    expect(parseRetryAfter("30")).toBe(30);
    expect(
      parseRetryAfter("Wed, 21 Oct 2026 07:28:10 GMT", Date.parse("Wed, 21 Oct 2026 07:28:00 GMT")),
    ).toBe(10);
    expect(parseRetryAfter("soon")).toBeUndefined();
    expect(parseRetryAfter(undefined)).toBeUndefined();
  });
});

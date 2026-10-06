import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/errors";
import { createQueryClient, retryDelay, shouldRetryQuery } from "@/lib/query";

const err = (status: number) => new ApiError({ status, kind: "UNKNOWN", message: "x" });

describe("query retry policy (R5)", () => {
  it("retries network errors and 502/503/504 up to twice", () => {
    for (const s of [0, 502, 503, 504]) {
      expect(shouldRetryQuery(0, err(s))).toBe(true);
      expect(shouldRetryQuery(1, err(s))).toBe(true);
      expect(shouldRetryQuery(2, err(s))).toBe(false);
    }
  });

  it("never retries other statuses or non-ApiErrors", () => {
    for (const s of [400, 401, 404, 422, 429, 500]) expect(shouldRetryQuery(0, err(s))).toBe(false);
    expect(shouldRetryQuery(0, new Error("boom"))).toBe(false);
  });

  it("does not retry cancellations", () => {
    expect(shouldRetryQuery(0, new ApiError({ status: 0, kind: "CANCELLED", message: "x" }))).toBe(
      false,
    );
  });

  it("never auto-retries mutations", () => {
    expect(createQueryClient().getDefaultOptions().mutations?.retry).toBe(false);
  });

  it("backs off exponentially with a cap", () => {
    expect(retryDelay(0)).toBeLessThanOrEqual(1000);
    expect(retryDelay(10)).toBeLessThanOrEqual(10_000);
    expect(retryDelay(10)).toBeGreaterThanOrEqual(5000);
  });
});

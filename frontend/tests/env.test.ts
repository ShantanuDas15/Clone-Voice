import { describe, expect, it } from "vitest";

import { apiOrigin, parseEnv } from "@/lib/env";

describe("parseEnv", () => {
  it("accepts a valid config", () => {
    expect(parseEnv({ NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000/api/v1" })).toEqual({
      NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000/api/v1",
    });
  });

  it("rejects missing, malformed and trailing-slash URLs", () => {
    expect(() => parseEnv({})).toThrow(/NEXT_PUBLIC_API_BASE_URL/);
    expect(() => parseEnv({ NEXT_PUBLIC_API_BASE_URL: "not a url" })).toThrow(
      /NEXT_PUBLIC_API_BASE_URL/,
    );
    expect(() => parseEnv({ NEXT_PUBLIC_API_BASE_URL: "http://x.test/api/v1/" })).toThrow(
      /trailing slash/,
    );
  });

  it("derives the API origin", () => {
    expect(apiOrigin("https://api.example.com/api/v1")).toBe("https://api.example.com");
  });
});

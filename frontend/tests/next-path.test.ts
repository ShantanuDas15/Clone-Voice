import { describe, expect, it } from "vitest";

import { sanitizeNext } from "@/lib/auth/next-path";

describe("sanitizeNext (open-redirect prevention)", () => {
  it.each([
    ["/dashboard", "/dashboard"],
    ["/profile?tab=history#x", "/profile?tab=history#x"],
  ])("keeps safe relative path %s", (input, out) => expect(sanitizeNext(input)).toBe(out));

  it.each([
    "https://evil.test/x",
    "//evil.test",
    "/\\evil.test",
    "\\\\evil.test",
    "javascript:alert(1)",
    "dashboard",
    "/ok\nHeader: x",
    "",
    null,
    undefined,
  ])("rejects %j", (input) =>
    expect(sanitizeNext(input as string | null | undefined)).toBe("/dashboard"),
  );
});

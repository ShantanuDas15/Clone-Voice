import { describe, expect, it } from "vitest";

import { sanitizeNext } from "@/lib/auth/next-path";

describe("sanitizeNext (open-redirect prevention)", () => {
  it.each([
    ["/generate", "/generate"],
    ["/voices?tab=x#y", "/voices?tab=x#y"],
    ["/history", "/history"],
  ])("keeps safe relative path %s", (input, out) => expect(sanitizeNext(input)).toBe(out));

  it.each([
    ["/dashboard", "/generate"],
    ["/profile", "/voices"],
    ["/profile?tab=history#x", "/voices?tab=history#x"],
  ])("maps the renamed route %s to %s", (input, out) => expect(sanitizeNext(input)).toBe(out));

  it("does not map look-alike paths", () => {
    expect(sanitizeNext("/profile-x")).toBe("/profile-x");
    expect(sanitizeNext("/dashboard/extra")).toBe("/dashboard/extra");
  });

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
    expect(sanitizeNext(input as string | null | undefined)).toBe("/generate"),
  );
});

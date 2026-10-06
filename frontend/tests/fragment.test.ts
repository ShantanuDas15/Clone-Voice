import { afterEach, describe, expect, it, vi } from "vitest";

import { consumeFragmentToken, parseFragmentToken } from "@/lib/auth/fragment";
import { GOOGLE_ERROR_MESSAGES, googleErrorMessage } from "@/lib/auth/google-errors";

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("parseFragmentToken", () => {
  it.each([
    ["#token=abc.def-1", "abc.def-1"],
    ["token=abc", "abc"],
    ["#token=a%2Bb", "a+b"],
    ["#token=", null],
    ["#other=1", null],
    ["", null],
  ])("parses %j", (hash, expected) => expect(parseFragmentToken(hash)).toBe(expected));
});

describe("consumeFragmentToken", () => {
  it("returns the token and strips the fragment exactly once", () => {
    window.history.replaceState(null, "", "/verify-email?x=1#token=secret");
    const spy = vi.spyOn(window.history, "replaceState");
    expect(consumeFragmentToken()).toBe("secret");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("");
    expect(window.location.search).toBe("?x=1");
  });

  it("does not touch history when there is no fragment", () => {
    const spy = vi.spyOn(window.history, "replaceState");
    expect(consumeFragmentToken()).toBeNull();
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("googleErrorMessage", () => {
  it("has distinct copy for every known code", () => {
    const messages = Object.values(GOOGLE_ERROR_MESSAGES);
    expect(new Set(messages).size).toBe(messages.length);
    expect(Object.keys(GOOGLE_ERROR_MESSAGES).sort()).toEqual([
      "google_account_conflict",
      "google_email_unverified",
      "google_failed",
      "google_no_email",
      "session_unavailable",
    ]);
  });
  it("falls back to generic text for unknown codes and null for none", () => {
    expect(googleErrorMessage("whatever")).toBe("Sign-in failed. Please try again.");
    expect(googleErrorMessage("__proto__")).toBe("Sign-in failed. Please try again.");
    expect(googleErrorMessage(null)).toBeNull();
  });
});

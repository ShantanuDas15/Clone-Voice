import { beforeEach, describe, expect, it } from "vitest";

import { clearDraft, getDraft, saveDraft } from "@/lib/draft";

describe("in-memory draft (U3.2, R2, R16)", () => {
  beforeEach(clearDraft);

  it("returns the draft to the user who saved it", () => {
    saveDraft("u1", { text: "Keep me", voiceName: "Mine" });
    expect(getDraft("u1")).toMatchObject({ text: "Keep me", voiceName: "Mine" });
  });

  it("shows another user nothing, even though the same tab still holds the draft", () => {
    saveDraft("u1", { text: "Private" });
    expect(getDraft("u2")).toEqual({ voiceId: "", text: "", voiceName: "" });
  });

  it("drops the previous user's draft when a different user starts saving", () => {
    saveDraft("u1", { text: "Private", voiceName: "Old" });
    saveDraft("u2", { voiceId: "v" });
    expect(getDraft("u2")).toEqual({ voiceId: "v", text: "", voiceName: "" });
    expect(getDraft("u1").text).toBe("");
  });

  it("ignores saves and reads without a signed-in user", () => {
    saveDraft(undefined, { text: "x" });
    expect(getDraft(undefined).text).toBe("");
    saveDraft("u1", { text: "y" });
    expect(getDraft(undefined).text).toBe("");
  });

  it("is emptied by a deliberate sign-out", () => {
    saveDraft("u1", { text: "Gone" });
    clearDraft();
    expect(getDraft("u1").text).toBe("");
  });

  it("never stores consent", () => {
    expect(Object.keys(getDraft("u1"))).not.toContain("consent");
  });
});

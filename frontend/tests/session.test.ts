import { HttpResponse, http as mswHttp } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  __resetSessionForTests,
  clearSession,
  getAccessToken,
  handleChannelMessage,
  refreshAccessToken,
  subscribe,
} from "@/lib/auth/session";
import { server } from "@/mocks/server";

const REFRESH = "http://api.test/api/v1/auth/refresh";

function countRefreshes(): { count: () => number } {
  let n = 0;
  server.use(
    mswHttp.post(REFRESH, async () => {
      n += 1;
      await new Promise((r) => setTimeout(r, 5));
      return HttpResponse.json({ access_token: `tok-${n}`, token_type: "bearer" });
    }),
  );
  return { count: () => n };
}

beforeEach(() => __resetSessionForTests());
afterEach(() => vi.unstubAllGlobals());

describe("refreshAccessToken", () => {
  it("shares one network call between concurrent callers (single-flight)", async () => {
    const calls = countRefreshes();
    const results = await Promise.all([
      refreshAccessToken(),
      refreshAccessToken(),
      refreshAccessToken(),
    ]);
    expect(calls.count()).toBe(1);
    expect(new Set(results).size).toBe(1);
    expect(getAccessToken()).toBe("tok-1");
  });

  it("never issues more than one request per burst over 100 iterations (rotation safety, G-22)", async () => {
    const calls = countRefreshes();
    for (let i = 0; i < 100; i++) {
      const out = await Promise.all(Array.from({ length: 5 }, () => refreshAccessToken()));
      expect(out.every((t) => t !== null)).toBe(true);
    }
    expect(calls.count()).toBe(100);
  });

  it("resolves null (not an error) when the refresh cookie is invalid", async () => {
    server.use(
      mswHttp.post(REFRESH, () =>
        HttpResponse.json({ detail: "Invalid refresh token" }, { status: 401 }),
      ),
    );
    await expect(refreshAccessToken()).resolves.toBeNull();
    expect(getAccessToken()).toBeNull();
  });

  it("propagates network failures instead of pretending to be signed out", async () => {
    server.use(mswHttp.post(REFRESH, () => HttpResponse.error()));
    await expect(refreshAccessToken()).rejects.toMatchObject({ kind: "NETWORK" });
  });

  it("a tab that waited on the cross-tab lock adopts the winner's token without a request", async () => {
    const calls = countRefreshes();
    vi.stubGlobal("navigator", {
      locks: {
        request: async (_name: string, cb: () => Promise<unknown>) => {
          // Another tab refreshed and broadcast while we were waiting for the lock.
          handleChannelMessage({ type: "token", token: "from-other-tab" });
          return cb();
        },
      },
    });
    await expect(refreshAccessToken()).resolves.toBe("from-other-tab");
    expect(calls.count()).toBe(0);
  });
});

describe("cross-tab events", () => {
  it("a logout message clears the token and notifies subscribers without re-broadcasting", () => {
    handleChannelMessage({ type: "token", token: "abc" });
    const events: string[] = [];
    subscribe((e) => events.push(e));
    handleChannelMessage({ type: "logout" });
    expect(getAccessToken()).toBeNull();
    expect(events).toEqual(["cleared"]);
  });

  it("clearSession is silent when there was no session", () => {
    const events: string[] = [];
    subscribe((e) => events.push(e));
    clearSession();
    expect(events).toEqual([]);
  });
});

import { HttpResponse, http as mswHttp } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { getJson } from "@/lib/api/http";
import {
  __resetSessionForTests,
  getAccessToken,
  handleChannelMessage,
  subscribe,
} from "@/lib/auth/session";
import { server } from "@/mocks/server";

const API = "http://api.test/api/v1";

beforeEach(() => __resetSessionForTests());

function protectedEndpoint(validToken: string, seen: string[]) {
  server.use(
    mswHttp.get(`${API}/secret`, ({ request }) => {
      const auth = request.headers.get("authorization") ?? "";
      seen.push(auth);
      return auth === `Bearer ${validToken}`
        ? HttpResponse.json({ ok: true })
        : HttpResponse.json({ detail: "Could not validate credentials" }, { status: 401 });
    }),
  );
}

describe("401 handling", () => {
  it("attaches the bearer token", async () => {
    handleChannelMessage({ type: "token", token: "good" });
    const seen: string[] = [];
    protectedEndpoint("good", seen);
    await getJson("/secret");
    expect(seen).toEqual(["Bearer good"]);
  });

  it("refreshes once and retries once on 401", async () => {
    handleChannelMessage({ type: "token", token: "expired" });
    const seen: string[] = [];
    protectedEndpoint("test-access-token", seen); // default refresh handler issues this token
    let refreshes = 0;
    server.use(
      mswHttp.post(`${API}/auth/refresh`, () => {
        refreshes += 1;
        return HttpResponse.json({ access_token: "test-access-token", token_type: "bearer" });
      }),
    );
    await expect(getJson("/secret")).resolves.toEqual({ ok: true });
    expect(refreshes).toBe(1);
    expect(seen).toEqual(["Bearer expired", "Bearer test-access-token"]);
  });

  it("concurrent 401s trigger a single refresh", async () => {
    handleChannelMessage({ type: "token", token: "expired" });
    protectedEndpoint("fresh", []);
    let refreshes = 0;
    server.use(
      mswHttp.post(`${API}/auth/refresh`, async () => {
        refreshes += 1;
        await new Promise((r) => setTimeout(r, 10));
        return HttpResponse.json({ access_token: "fresh", token_type: "bearer" });
      }),
    );
    await Promise.all([getJson("/secret"), getJson("/secret"), getJson("/secret")]);
    expect(refreshes).toBe(1);
  });

  it("a second 401 after the retry fails and does not loop", async () => {
    handleChannelMessage({ type: "token", token: "expired" });
    const seen: string[] = [];
    protectedEndpoint("never-issued", seen);
    await expect(getJson("/secret")).rejects.toMatchObject({
      status: 401,
      kind: "UNAUTHENTICATED",
    });
    expect(seen).toHaveLength(2);
  });

  it("ends the session when refresh fails", async () => {
    handleChannelMessage({ type: "token", token: "expired" });
    protectedEndpoint("x", []);
    server.use(
      mswHttp.post(`${API}/auth/refresh`, () =>
        HttpResponse.json({ detail: "Invalid" }, { status: 401 }),
      ),
    );
    const events: string[] = [];
    subscribe((e) => events.push(e));
    await expect(getJson("/secret")).rejects.toMatchObject({ status: 401 });
    expect(getAccessToken()).toBeNull();
    expect(events).toContain("cleared");
  });

  it("does not refresh for a request whose token was already replaced", async () => {
    handleChannelMessage({ type: "token", token: "old" });
    const seen: string[] = [];
    server.use(
      mswHttp.get(`${API}/secret`, ({ request }) => {
        const auth = request.headers.get("authorization") ?? "";
        seen.push(auth);
        if (auth === "Bearer old") {
          // Another tab rotated the token while this request was in flight.
          handleChannelMessage({ type: "token", token: "new" });
          return HttpResponse.json({ detail: "expired" }, { status: 401 });
        }
        return HttpResponse.json({ ok: true });
      }),
      mswHttp.post(`${API}/auth/refresh`, () => {
        throw new Error("refresh must not be called");
      }),
    );
    await expect(getJson("/secret")).resolves.toEqual({ ok: true });
    expect(seen).toEqual(["Bearer old", "Bearer new"]);
  });

  it("never refreshes on a failed login", async () => {
    server.use(
      mswHttp.post(`${API}/auth/login`, () =>
        HttpResponse.json({ detail: "Incorrect" }, { status: 401 }),
      ),
    );
    const { login } = await import("@/lib/api/auth");
    await expect(login({ email: "a@b.co", password: "x" })).rejects.toMatchObject({ status: 401 });
  });
});

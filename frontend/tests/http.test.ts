import { HttpResponse, http as mswHttp } from "msw";
import { describe, expect, it } from "vitest";

import { getJson } from "@/lib/api/http";
import { fetchTerms } from "@/lib/api/terms";
import { ApiError } from "@/lib/errors";
import { server } from "@/mocks/server";

const API = "http://api.test/api/v1";

describe("http client", () => {
  it("returns parsed bodies", async () => {
    await expect(fetchTerms()).resolves.toEqual({ version: "1", url: null });
  });

  it("throws ApiError for HTTP failures", async () => {
    server.use(
      mswHttp.get(`${API}/x`, () => HttpResponse.json({ detail: "nope" }, { status: 403 })),
    );
    await expect(getJson("/x")).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      kind: "FORBIDDEN",
    });
  });

  it("throws a NETWORK ApiError when the connection drops", async () => {
    server.use(mswHttp.get(`${API}/x`, () => HttpResponse.error()));
    const err = await getJson("/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 0, kind: "NETWORK" });
  });

  it("reports cancellation", async () => {
    server.use(mswHttp.get(`${API}/x`, () => HttpResponse.json({})));
    const controller = new AbortController();
    controller.abort();
    await expect(getJson("/x", { signal: controller.signal })).rejects.toMatchObject({
      kind: "CANCELLED",
    });
  });
});

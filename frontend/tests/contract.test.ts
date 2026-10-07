import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import * as authApi from "@/lib/api/auth";
import { http as client } from "@/lib/api/http";
import { fetchHistory } from "@/lib/api/history";
import { synthesize } from "@/lib/api/synthesize";
import { uploadProfile } from "@/lib/api/voice";
import { fixtures, handlers } from "@/mocks/handlers";
import { server } from "@/mocks/server";

import {
  matchSpecPath,
  operation,
  responseSchema,
  spec,
  validateComponent,
  validateSchema,
} from "./helpers/openapi";

const API = "http://api.test/api/v1";
const ID = "44444444-4444-4444-8444-444444444444";

/** Record the JSON body the real client function sends, answering with `status`. */
function captureJson(method: "post" | "patch" | "delete", path: string, status = 200) {
  const seen: { body?: unknown } = {};
  server.use(
    http[method](`${API}${path}`, async ({ request }) => {
      seen.body = await request.json();
      return status === 204
        ? new HttpResponse(null, { status })
        : HttpResponse.json(fixtures.user, { status });
    }),
  );
  return seen;
}

function requestSchema(method: string, template: string): Record<string, unknown> {
  const schema = operation(method, template)?.requestBody?.content["application/json"]?.schema;
  if (!schema) throw new Error(`${method} ${template} declares no JSON request body`);
  return schema;
}

describe("OpenAPI snapshot", () => {
  it("is OpenAPI 3.1 and declares the endpoints the client calls", () => {
    expect(Object.keys(spec.paths)).toEqual(
      expect.arrayContaining([
        "/api/v1/auth/login",
        "/api/v1/voice/upload",
        "/api/v1/synthesize/history",
      ]),
    );
  });
});

describe("response fixtures match the backend schemas", () => {
  const cases: [string, string, unknown][] = [
    ["user", "UserOut", fixtures.user],
    ["profile", "VoiceProfileOut", fixtures.profile],
    ["generation", "GenerationOut", fixtures.generation],
    ["token", "TokenResponse", fixtures.token],
    ["terms", "TermsOut", { version: "1", url: null }],
  ];

  it.each(cases)("%s fixture is a valid %s", (_name, schema, value) => {
    expect(validateComponent(schema, value)).toEqual([]);
  });

  it.each(cases)("%s fixture invents no field the backend lacks (%s)", (_name, schema, value) => {
    const known = Object.keys(
      (spec.components.schemas[schema]?.properties as Record<string, unknown>) ?? {},
    );
    expect(Object.keys(value as object).filter((k) => !known.includes(k))).toEqual([]);
  });

  it("the validator rejects drift (a missing required field, a wrong type)", () => {
    const { email: _omitted, ...withoutEmail } = fixtures.user;
    expect(validateComponent("UserOut", withoutEmail)).not.toEqual([]);
    expect(validateComponent("UserOut", { ...fixtures.user, has_password: "yes" })).not.toEqual([]);
  });
});

describe("every default mock handler matches the spec", () => {
  const rows = handlers.map((h) => {
    const info = (h as unknown as { info: { method: string; path: string } }).info;
    return { method: info.method, url: info.path.replace(":id", ID) };
  });

  it.each(rows)("$method $url", async ({ method, url }) => {
    const template = matchSpecPath(new URL(url).pathname);
    expect(template, "handler path is not in the OpenAPI spec").not.toBeNull();
    const op = operation(method, template as string);
    expect(op, "handler method is not declared for that path").toBeDefined();

    const res = await fetch(url, { method });
    const declared = op!.responses[String(res.status)];
    expect(declared, `status ${res.status} is not declared`).toBeDefined();

    const schema = responseSchema(op!, res.status);
    if (schema && res.headers.get("content-type")?.includes("json")) {
      expect(validateSchema(schema, await res.json())).toEqual([]);
    }
  });

  it("mocks every endpoint the app calls", () => {
    const mocked = new Set(
      rows.map((r) => `${r.method} ${matchSpecPath(new URL(r.url).pathname)}`),
    );
    for (const key of [
      "POST /api/v1/auth/signup",
      "POST /api/v1/auth/login",
      "PATCH /api/v1/auth/me",
      "DELETE /api/v1/auth/me",
      "POST /api/v1/voice/upload",
      "POST /api/v1/synthesize",
    ]) {
      expect(mocked.has(key), key).toBe(true);
    }
  });
});

describe("requests the client builds match the request schemas", () => {
  it("the validator rejects a payload the backend would 422 (canary)", () => {
    const schema = requestSchema("post", "/api/v1/auth/login");
    expect(validateSchema(schema, { email: "a@b.co" })).not.toEqual([]);
    expect(validateSchema(schema, { email: "a@b.co", password: 12345678 })).not.toEqual([]);
  });

  it("signup", async () => {
    const seen = captureJson("post", "/auth/signup", 201);
    await authApi.signup({ email: "a@b.co", password: "Password123!", name: "Ada" });
    expect(validateSchema(requestSchema("post", "/api/v1/auth/signup"), seen.body)).toEqual([]);
  });

  it("login", async () => {
    const seen = captureJson("post", "/auth/login");
    await authApi.login({ email: "a@b.co", password: "Password123!" });
    expect(validateSchema(requestSchema("post", "/api/v1/auth/login"), seen.body)).toEqual([]);
  });

  it("verify-email", async () => {
    const seen = captureJson("post", "/auth/verify-email");
    await authApi.verifyEmail("a-token");
    expect(validateSchema(requestSchema("post", "/api/v1/auth/verify-email"), seen.body)).toEqual(
      [],
    );
  });

  it("forgot-password", async () => {
    const seen = captureJson("post", "/auth/forgot-password", 202);
    await authApi.forgotPassword("a@b.co");
    expect(
      validateSchema(requestSchema("post", "/api/v1/auth/forgot-password"), seen.body),
    ).toEqual([]);
  });

  it("reset-password sends snake_case new_password", async () => {
    const seen = captureJson("post", "/auth/reset-password");
    await authApi.resetPassword({ token: "t", newPassword: "Password123!" });
    expect(validateSchema(requestSchema("post", "/api/v1/auth/reset-password"), seen.body)).toEqual(
      [],
    );
  });

  it("PATCH /auth/me", async () => {
    const seen = captureJson("patch", "/auth/me");
    await authApi.updateName("Grace");
    expect(validateSchema(requestSchema("patch", "/api/v1/auth/me"), seen.body)).toEqual([]);
  });

  it.each([["hunter2!A"], [undefined]])("DELETE /auth/me with password %s", async (password) => {
    const seen = captureJson("delete", "/auth/me", 204);
    await authApi.deleteAccount(password);
    expect(validateSchema(requestSchema("delete", "/api/v1/auth/me"), seen.body)).toEqual([]);
  });

  it("POST /synthesize", async () => {
    const seen: { body?: unknown } = {};
    server.use(
      http.post(`${API}/synthesize`, async ({ request }) => {
        seen.body = await request.json();
        return new HttpResponse(new Uint8Array([82, 73, 70, 70]), {
          headers: { "Content-Type": "audio/wav" },
        });
      }),
    );
    await synthesize({ voiceProfileId: ID, text: "Hello." });
    expect(validateSchema(requestSchema("post", "/api/v1/synthesize"), seen.body)).toEqual([]);
  });

  it("POST /voice/upload sends only declared multipart fields, including every required one", async () => {
    // jsdom's XHR hands MSW an unserialisable FormData, so inspect the request at the client instead.
    const post = vi.spyOn(client, "post").mockResolvedValue({ data: fixtures.profile });
    await uploadProfile({
      name: "My voice",
      file: new File([new Uint8Array(8)], "a.wav", { type: "audio/wav" }),
      termsVersion: "1",
    });
    const form = post.mock.calls[0]![1] as FormData;
    const sent = [...form.keys()];
    post.mockRestore();

    const schema = spec.components.schemas.Body_upload_audio_api_v1_voice_upload_post as {
      properties: Record<string, unknown>;
      required: string[];
    };
    expect(sent.length).toBeGreaterThan(0);
    expect(sent.filter((f) => !Object.keys(schema.properties).includes(f))).toEqual([]);
    expect(schema.required.filter((f) => !sent.includes(f))).toEqual([]);
  });

  it("GET /synthesize/history sends only declared query params, within their bounds", async () => {
    const seen: { params?: URLSearchParams } = {};
    server.use(
      http.get(`${API}/synthesize/history`, ({ request }) => {
        seen.params = new URL(request.url).searchParams;
        return HttpResponse.json([], { headers: { "X-Total-Count": "0" } });
      }),
    );
    await fetchHistory(100);

    const declared = operation("get", "/api/v1/synthesize/history")!.parameters!;
    const names = declared.map((p) => p.name);
    expect([...seen.params!.keys()].filter((k) => !names.includes(k))).toEqual([]);
    for (const param of declared) {
      const raw = seen.params!.get(param.name);
      if (raw === null) continue;
      expect(validateSchema(param.schema, Number(raw)), param.name).toEqual([]);
    }
  });
});

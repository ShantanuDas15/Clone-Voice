import { describe, expect, it } from "vitest";

import { loginSchema, signupSchema } from "@/lib/validation/auth";

const ok = { email: "a@b.co", name: "Ada", password: "12345678" };

describe("signupSchema (backend bounds)", () => {
  it("accepts valid input and trims name", () => {
    expect(signupSchema.parse({ ...ok, name: "  Ada  " }).name).toBe("Ada");
  });
  it("enforces password 8-128", () => {
    expect(signupSchema.safeParse({ ...ok, password: "1234567" }).success).toBe(false);
    expect(signupSchema.safeParse({ ...ok, password: "x".repeat(128) }).success).toBe(true);
    expect(signupSchema.safeParse({ ...ok, password: "x".repeat(129) }).success).toBe(false);
  });
  it("rejects blank or over-long names and bad emails", () => {
    expect(signupSchema.safeParse({ ...ok, name: "   " }).success).toBe(false);
    expect(signupSchema.safeParse({ ...ok, name: "x".repeat(256) }).success).toBe(false);
    expect(signupSchema.safeParse({ ...ok, email: "nope" }).success).toBe(false);
  });
});

describe("loginSchema", () => {
  it("allows short passwords (server decides) up to 4096", () => {
    expect(loginSchema.safeParse({ email: "a@b.co", password: "x" }).success).toBe(true);
    expect(loginSchema.safeParse({ email: "a@b.co", password: "x".repeat(4097) }).success).toBe(
      false,
    );
    expect(loginSchema.safeParse({ email: "a@b.co", password: "" }).success).toBe(false);
  });
});

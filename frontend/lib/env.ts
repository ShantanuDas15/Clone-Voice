import "@/lib/zod-setup";
import { z } from "zod";

const envSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z
    .string()
    .url()
    .refine((v) => !v.endsWith("/"), "must not end with a trailing slash"),
  NEXT_PUBLIC_APP_ORIGIN: z.string().url().optional(),
});

export type Env = z.infer<typeof envSchema>;

/** Validate raw env values; throws a readable error naming every bad variable. */
export function parseEnv(raw: Record<string, string | undefined>): Env {
  const result = envSchema.safeParse(raw);
  if (!result.success) {
    const issues = result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`);
    throw new Error(`Invalid frontend environment: ${issues.join("; ")}`);
  }
  return result.data;
}

// Next.js inlines NEXT_PUBLIC_* only for literal property access.
export const env: Env = parseEnv({
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  NEXT_PUBLIC_APP_ORIGIN: process.env.NEXT_PUBLIC_APP_ORIGIN,
});

/** API origin (scheme + host), where `/health/*` lives outside `/api/v1`. */
export function apiOrigin(baseUrl: string = env.NEXT_PUBLIC_API_BASE_URL): string {
  return new URL(baseUrl).origin;
}

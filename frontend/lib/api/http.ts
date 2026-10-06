import {
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";

import { createPlainClient, toRawFailure } from "@/lib/api/plain";
import { clearSession, getAccessToken, refreshAccessToken } from "@/lib/auth/session";
import { env } from "@/lib/env";
import { ApiError, normalizeError } from "@/lib/errors";

export { DEFAULT_TIMEOUT_MS } from "@/lib/api/plain";
/** Long timeout for `/synthesize` and `/voice/upload` (G-03 worst case ≈ 70 s plus cold start). */
export const LONG_TIMEOUT_MS = 120_000;

/** Endpoints that must never trigger the 401 → refresh → retry flow. */
const NO_REFRESH_PATHS = ["/auth/login", "/auth/signup", "/auth/refresh", "/auth/logout"];

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean };

function bearer(token: string | null): string | undefined {
  return token ? `Bearer ${token}` : undefined;
}

/**
 * Axios instance for authenticated calls: attaches the in-memory bearer token and, on a
 * 401, performs exactly one refresh and one retry (§5.3). A failed refresh ends the session.
 */
export function createHttpClient(baseURL: string = env.NEXT_PUBLIC_API_BASE_URL): AxiosInstance {
  const client = createPlainClient(baseURL);
  // Replace the plain client's error handler with an auth-aware one.
  client.interceptors.response.clear();

  client.interceptors.request.use((config) => {
    const header = bearer(getAccessToken());
    if (header && !config.headers.Authorization) config.headers.Authorization = header;
    return config;
  });

  client.interceptors.response.use(
    (response) => response,
    async (error: unknown) => {
      const failure = toRawFailure(error);
      const config = (error as { config?: RetriableConfig }).config;
      const eligible =
        failure.status === 401 &&
        config !== undefined &&
        !config._retried &&
        !NO_REFRESH_PATHS.some((p) => config.url?.startsWith(p));

      if (eligible && config) {
        const sentWith = config.headers.Authorization;
        const current = bearer(getAccessToken());
        // Another caller already refreshed since this request left: just retry with that token.
        const token =
          current && current !== sentWith ? current.slice(7) : await refreshAccessToken();
        if (token) {
          config._retried = true;
          config.headers.Authorization = `Bearer ${token}`;
          return client.request(config);
        }
        clearSession();
      }
      throw await normalizeError(failure);
    },
  );
  return client;
}

export const http = createHttpClient();

/** Config overrides for the two long-running endpoints. */
export const longRequest: Pick<AxiosRequestConfig, "timeout"> = { timeout: LONG_TIMEOUT_MS };

/** Typed GET returning only the body. */
export async function getJson<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await http.get<T>(url, config);
  return response.data;
}

export { ApiError };

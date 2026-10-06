import axios, { type AxiosInstance, isAxiosError, isCancel } from "axios";

import { env } from "@/lib/env";
import { type RawFailure, normalizeError } from "@/lib/errors";

/** Default timeout for ordinary calls (plan §5.2). */
export const DEFAULT_TIMEOUT_MS = 15_000;

/** Convert any thrown value from Axios into the transport-neutral failure shape. */
export function toRawFailure(error: unknown): RawFailure {
  if (isCancel(error)) return { status: 0, code: "CANCELLED" };
  if (isAxiosError(error)) {
    if (error.response) {
      return {
        status: error.response.status,
        data: error.response.data,
        headers: error.response.headers as Record<string, string | undefined>,
      };
    }
    const timedOut = error.code === "ECONNABORTED" || error.code === "ETIMEDOUT";
    return { status: 0, code: timedOut ? "TIMEOUT" : "NETWORK" };
  }
  return { status: 0, code: "NETWORK" };
}

/** Axios instance with cookies and error normalizing, but no auth logic (used by the session core). */
export function createPlainClient(baseURL: string = env.NEXT_PUBLIC_API_BASE_URL): AxiosInstance {
  const client = axios.create({ baseURL, withCredentials: true, timeout: DEFAULT_TIMEOUT_MS });
  client.interceptors.response.use(
    (response) => response,
    async (error: unknown) => {
      throw await normalizeError(toRawFailure(error));
    },
  );
  return client;
}

export const plainClient = createPlainClient();

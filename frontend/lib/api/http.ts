import axios, { type AxiosInstance, type AxiosRequestConfig, isAxiosError, isCancel } from "axios";

import { env } from "@/lib/env";
import { ApiError, type RawFailure, normalizeError } from "@/lib/errors";

/** Default timeout for ordinary calls (plan §5.2). */
export const DEFAULT_TIMEOUT_MS = 15_000;
/** Long timeout for `/synthesize` and `/voice/upload` (G-03 worst case ≈ 70 s plus cold start). */
export const LONG_TIMEOUT_MS = 120_000;

function toRawFailure(error: unknown): RawFailure {
  if (isCancel(error)) return { status: 0, code: "CANCELLED" };
  if (isAxiosError(error)) {
    if (error.response) {
      return {
        status: error.response.status,
        data: error.response.data,
        headers: error.response.headers as Record<string, string | undefined>,
      };
    }
    return {
      status: 0,
      code: error.code === "ECONNABORTED" || error.code === "ETIMEDOUT" ? "TIMEOUT" : "NETWORK",
    };
  }
  return { status: 0, code: "NETWORK" };
}

/** Create an Axios instance whose every failure surfaces as an `ApiError`. */
export function createHttpClient(baseURL: string = env.NEXT_PUBLIC_API_BASE_URL): AxiosInstance {
  const client = axios.create({ baseURL, withCredentials: true, timeout: DEFAULT_TIMEOUT_MS });
  client.interceptors.response.use(
    (response) => response,
    async (error: unknown) => {
      throw await normalizeError(toRawFailure(error));
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

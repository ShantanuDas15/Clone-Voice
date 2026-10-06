import axios from "axios";

import { apiOrigin } from "@/lib/env";

export type HealthState = "ok" | "degraded" | "unknown";

/**
 * Probe `GET /health/ready` (served at the API origin, outside /api/v1).
 * 200 → ok, 503 → degraded (R17); any other outcome is "unknown" so a
 * flaky probe never blocks the UI.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthState> {
  try {
    const response = await axios.get(`${apiOrigin()}/health/ready`, {
      signal,
      timeout: 5_000,
      validateStatus: (s) => s === 200 || s === 503,
    });
    return response.status === 200 ? "ok" : "degraded";
  } catch {
    return "unknown";
  }
}

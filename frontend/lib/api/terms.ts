import { getJson } from "@/lib/api/http";

export interface Terms {
  version: string;
  url: string | null;
  /** Days a generated clip is kept; null or absent when the server states no figure. */
  output_retention_days?: number | null;
  /** Minutes a password-reset link stays valid; absent on an older backend. */
  password_reset_expire_minutes?: number | null;
}

/** Fetch the current acceptable-use terms version/link. */
export function fetchTerms(): Promise<Terms> {
  return getJson<Terms>("/terms");
}

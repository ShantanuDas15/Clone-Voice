import { getJson } from "@/lib/api/http";

export interface Terms {
  version: string;
  url: string | null;
}

/** Fetch the current acceptable-use terms version/link. */
export function fetchTerms(): Promise<Terms> {
  return getJson<Terms>("/terms");
}

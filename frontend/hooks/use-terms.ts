import { useQuery } from "@tanstack/react-query";

import { fetchTerms } from "@/lib/api/terms";

/** The current terms and output retention; shared cache key with the upload form. */
export function useTerms() {
  return useQuery({ queryKey: ["terms"], queryFn: fetchTerms, staleTime: 5 * 60_000 });
}

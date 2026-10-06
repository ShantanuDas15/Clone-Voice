"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { type Generation, type HistoryPage, fetchHistory, hasMoreHistory } from "@/lib/api/history";
import { HISTORY_KEY } from "@/hooks/use-voice-profiles";

/** Merge pages into one list, keeping the first occurrence of each id (offsets shift as rows arrive). */
export function flattenHistory(pages: readonly HistoryPage[]): Generation[] {
  const seen = new Set<string>();
  const out: Generation[] = [];
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      out.push(item);
    }
  }
  return out;
}

/** Paged history, newest first. Refetches on focus and after synthesis (R11). */
export function useHistory() {
  return useInfiniteQuery({
    queryKey: HISTORY_KEY,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => fetchHistory(pageParam, signal),
    getNextPageParam: (last) =>
      hasMoreHistory(last) ? last.offset + last.items.length : undefined,
  });
}

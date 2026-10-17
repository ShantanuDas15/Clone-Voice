"use client";

import {
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import {
  type Generation,
  type HistoryPage,
  deleteGeneration,
  fetchHistory,
  hasMoreHistory,
} from "@/lib/api/history";
import { ApiError } from "@/lib/errors";
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

/**
 * Paged history, newest first, optionally narrowed to one voice. The key extends HISTORY_KEY, so
 * invalidating HISTORY_KEY (after synthesis, delete) refreshes every filtered list as well.
 */
export function useHistory(voiceProfileId?: string) {
  return useInfiniteQuery({
    queryKey: voiceProfileId ? [...HISTORY_KEY, voiceProfileId] : HISTORY_KEY,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => fetchHistory(pageParam, signal, undefined, voiceProfileId),
    getNextPageParam: (last) =>
      hasMoreHistory(last) ? last.offset + last.items.length : undefined,
  });
}

/** The pages without generation `id`, and one less in the total when it was there. */
export function withoutGeneration(
  data: InfiniteData<HistoryPage>,
  id: string,
): InfiniteData<HistoryPage> {
  const present = data.pages.some((page) => page.items.some((item) => item.id === id));
  if (!present) return data;
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.filter((item) => item.id !== id),
      total: page.total === null ? null : Math.max(0, page.total - 1),
    })),
  };
}

/**
 * Delete one generation with optimistic removal and rollback. A 404 means it is already gone, so
 * it counts as success. The list is refetched either way so its total comes from the server.
 */
export function useDeleteGeneration() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      try {
        await deleteGeneration(id);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return;
        throw e;
      }
    },
    retry: false,
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: HISTORY_KEY });
      // Every cached list (unfiltered and per voice) may hold the row.
      const previous = client.getQueriesData<InfiniteData<HistoryPage>>({ queryKey: HISTORY_KEY });
      client.setQueriesData<InfiniteData<HistoryPage>>({ queryKey: HISTORY_KEY }, (old) =>
        old ? withoutGeneration(old, id) : old,
      );
      return { previous };
    },
    onError: (_error, _id, context) => {
      for (const [key, data] of context?.previous ?? []) client.setQueryData(key, data);
    },
    onSettled: () => void client.invalidateQueries({ queryKey: HISTORY_KEY }),
  });
}

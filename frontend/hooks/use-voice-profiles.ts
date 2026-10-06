"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type VoiceProfile, deleteProfile, fetchProfiles } from "@/lib/api/voice";
import { ApiError } from "@/lib/errors";

export const PROFILES_KEY = ["voice-profiles"] as const;
export const HISTORY_KEY = ["history"] as const;

/** All of the signed-in user's profiles, newest first (refetched on window focus, R11). */
export function useProfiles() {
  return useQuery({ queryKey: PROFILES_KEY, queryFn: ({ signal }) => fetchProfiles(signal) });
}

/**
 * Delete with optimistic removal and rollback. A 404 means it is already gone, so it counts as
 * success. Generations are erased with the profile, so history is invalidated either way.
 */
export function useDeleteProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      try {
        await deleteProfile(id);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return;
        throw e;
      }
    },
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: PROFILES_KEY });
      const previous = client.getQueryData<VoiceProfile[]>(PROFILES_KEY);
      client.setQueryData<VoiceProfile[]>(PROFILES_KEY, (old) => old?.filter((p) => p.id !== id));
      return { previous };
    },
    onError: (_error, _id, context) => {
      if (context?.previous) client.setQueryData(PROFILES_KEY, context.previous);
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: PROFILES_KEY });
      void client.invalidateQueries({ queryKey: HISTORY_KEY });
    },
  });
}

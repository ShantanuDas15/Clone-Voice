"use client";

import { useState } from "react";

import { AudioPlayer } from "@/components/audio-player";
import { flattenHistory, useHistory } from "@/hooks/use-history";
import { useObjectUrl } from "@/hooks/use-object-url";
import { type Generation, fetchGenerationAudio, isFailedGeneration } from "@/lib/api/history";
import { ApiError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { Button } from "@/components/ui/button";

const PREVIEW_CHARS = 140;

type PlayState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "ready"; blob: Blob }
  | { phase: "expired" }
  | { phase: "error"; message: string };

function playError(error: unknown): PlayState {
  if (error instanceof ApiError && (error.status === 404 || error.status === 410)) {
    return { phase: "expired" };
  }
  return {
    phase: "error",
    message: error instanceof ApiError ? error.message : "Couldn't load this audio.",
  };
}

function Playback({ gen }: { gen: Generation }) {
  const [state, setState] = useState<PlayState>(
    gen.audio_available ? { phase: "idle" } : { phase: "expired" },
  );
  const url = useObjectUrl(state.phase === "ready" ? state.blob : null);

  async function load() {
    setState({ phase: "loading" });
    try {
      setState({ phase: "ready", blob: await fetchGenerationAudio(gen.id) });
    } catch (e) {
      setState(playError(e));
    }
  }

  if (state.phase === "expired") {
    return (
      <p className="text-sm text-muted-foreground">
        The audio has expired and is no longer available (clips are kept for 30 days).
      </p>
    );
  }
  if (state.phase === "ready") {
    return url ? (
      <AudioPlayer
        src={url}
        filename={`clonevoice-${gen.id}.wav`}
        label={`Generated audio from ${formatDateTime(gen.created_at)}`}
        autoPlay
      />
    ) : null;
  }
  return (
    <div className="space-y-1">
      <Button
        variant="secondary"
        size="sm"
        onClick={() => void load()}
        disabled={state.phase === "loading"}
      >
        {state.phase === "loading" ? "Loading…" : state.phase === "error" ? "Try again" : "Play"}
      </Button>
      {state.phase === "error" && (
        <p role="alert" className="text-sm">
          {state.message}
        </p>
      )}
    </div>
  );
}

function HistoryItem({ gen }: { gen: Generation }) {
  const [expanded, setExpanded] = useState(false);
  const failed = isFailedGeneration(gen);
  const long = gen.input_text.length > PREVIEW_CHARS;
  const text = expanded || !long ? gen.input_text : `${gen.input_text.slice(0, PREVIEW_CHARS)}…`;

  return (
    <li className="space-y-2 rounded border border-border p-3">
      <p className="whitespace-pre-wrap break-words">{text}</p>
      {long && (
        <Button
          variant="quiet"
          size="sm"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? "Show less" : "Show more"}
        </Button>
      )}
      <p className="text-sm text-muted-foreground">
        {gen.voice_profile_name} · {formatDateTime(gen.created_at)}
        {gen.duration_seconds !== null && !failed && ` · ${gen.duration_seconds.toFixed(1)} s`}
      </p>
      {failed ? <p className="text-sm">Failed — no audio was produced.</p> : <Playback gen={gen} />}
    </li>
  );
}

/** Past generations, newest first, with load-more, per-row playback and expiry handling. */
export function HistoryList() {
  const { data, isPending, isError, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useHistory();

  if (isPending) {
    return (
      <ul aria-busy="true" aria-label="Loading history" className="space-y-2">
        {[0, 1].map((i) => (
          <li key={i} className="h-20 animate-pulse rounded bg-muted" />
        ))}
      </ul>
    );
  }
  if (isError) {
    return (
      <div role="alert" className="space-y-2">
        <p>We couldn&apos;t load your history.</p>
        <Button variant="secondary" size="sm" onClick={() => void refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const items = flattenHistory(data.pages);
  if (items.length === 0) {
    return (
      <p className="text-muted-foreground">
        Nothing generated yet. Speech you create on the dashboard will appear here.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {items.map((gen) => (
          <HistoryItem key={gen.id} gen={gen} />
        ))}
      </ul>
      {hasNextPage && (
        <Button
          variant="secondary"
          onClick={() => void fetchNextPage()}
          disabled={isFetchingNextPage}
        >
          {isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      )}
    </div>
  );
}

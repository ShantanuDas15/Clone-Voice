"use client";

import Link from "next/link";
import { useState } from "react";

import { ExpandableText } from "@/components/expandable-text";
import { Take } from "@/components/take";
import { flattenHistory, useHistory } from "@/hooks/use-history";
import { useObjectUrl } from "@/hooks/use-object-url";
import { useTerms } from "@/hooks/use-terms";
import { type Generation, fetchGenerationAudio, isFailedGeneration } from "@/lib/api/history";
import { ApiError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { generationDetails } from "@/lib/generation-details";
import { saveBlob } from "@/lib/download";
import { describeRetention, expiresSoon } from "@/lib/retention";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";

const PREVIEW_CHARS = 140;
const NAME_CHARS = 40;

/** The start of a row's text, to tell identical buttons apart ("Play: Hello there."). */
function snippet(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > NAME_CHARS ? `${flat.slice(0, NAME_CHARS).trimEnd()}…` : flat;
}

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
  const retentionDays = useTerms().data?.output_retention_days;
  const retention = describeRetention(retentionDays);
  const [state, setState] = useState<PlayState>(
    gen.audio_available ? { phase: "idle" } : { phase: "expired" },
  );
  const [saving, setSaving] = useState(false);
  const name = snippet(gen.input_text);
  const url = useObjectUrl(state.phase === "ready" ? state.blob : null);

  async function load() {
    setState({ phase: "loading" });
    try {
      setState({ phase: "ready", blob: await fetchGenerationAudio(gen.id) });
    } catch (e) {
      setState(playError(e));
    }
  }

  /** Fetch the audio and hand it to the browser as a file, without playing it first. */
  async function download() {
    setSaving(true);
    try {
      saveBlob(await fetchGenerationAudio(gen.id), `clonevoice-${gen.id}.wav`);
    } catch (e) {
      setState(playError(e));
    } finally {
      setSaving(false);
    }
  }

  if (state.phase === "expired") {
    return (
      <p className="text-sm text-muted-foreground">
        <Badge>Expired</Badge> The audio is no longer available
        {retention ? ` (clips are kept for ${retention})` : ""}.
      </p>
    );
  }
  if (state.phase === "ready") {
    return url ? (
      <Take
        src={url}
        blob={state.blob}
        filename={`clonevoice-${gen.id}.wav`}
        label={`Generated audio from ${formatDateTime(gen.created_at)}`}
        autoPlay
        focusPlay
      />
    ) : null;
  }
  const soon = expiresSoon(gen.created_at, retentionDays);
  const busy = state.phase === "loading" || saving;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void load()}
          disabled={busy}
          aria-label={
            state.phase === "loading"
              ? "Loading audio…"
              : `${state.phase === "error" ? "Try again" : "Play"}: ${name}`
          }
        >
          {state.phase === "loading"
            ? "Loading audio…"
            : state.phase === "error"
              ? "Try again"
              : "Play"}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void download()}
          disabled={busy}
          aria-label={`Download: ${name}`}
        >
          {saving ? "Preparing…" : "Download"}
        </Button>
      </div>
      {soon && (
        <p className="text-sm text-muted-foreground">Expires in {soon}. Download it to keep it.</p>
      )}
      {state.phase === "error" && (
        <p role="alert" className="text-sm">
          {state.message}
        </p>
      )}
    </div>
  );
}

function HistoryItem({ gen }: { gen: Generation }) {
  const failed = isFailedGeneration(gen);
  const details = generationDetails(gen);

  return (
    <li className="space-y-2 rounded border border-border p-3">
      <ExpandableText text={gen.input_text} limit={PREVIEW_CHARS} />
      <p className="text-sm text-muted-foreground">
        {gen.voice_profile_name} · {formatDateTime(gen.created_at)}
        {gen.duration_seconds !== null && !failed && ` · ${gen.duration_seconds.toFixed(1)} s`}
      </p>
      {details.length > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="generation-details">
          {details.join(" · ")}
        </p>
      )}
      {failed ? (
        <p className="text-sm">
          <Badge tone="notice">Failed</Badge> No audio was produced.
        </p>
      ) : (
        <Playback gen={gen} />
      )}
    </li>
  );
}

/** Past generations, newest first, with load-more, per-row playback and expiry handling. */
export function HistoryList() {
  const { data, isPending, isError, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useHistory();
  const retention = describeRetention(useTerms().data?.output_retention_days);
  const [announcement, setAnnouncement] = useState("");

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
      <div className="space-y-3">
        <p className="text-muted-foreground">
          Nothing generated yet. Speech you create will appear here.
        </p>
        <Link href="/generate" className={buttonVariants()}>
          Generate speech
        </Link>
      </div>
    );
  }

  // The whole history's size comes from the server (X-Total-Count); say where the user is in it.
  const total = data.pages[data.pages.length - 1]?.total ?? null;
  const count =
    total === null
      ? null
      : items.length < total
        ? `Showing ${items.length} of ${total}.`
        : `${total} ${total === 1 ? "generation" : "generations"}.`;

  async function loadMore() {
    const before = items.length;
    const result = await fetchNextPage();
    const after = result.data ? flattenHistory(result.data.pages).length : before;
    const shown = result.data?.pages[result.data.pages.length - 1]?.total ?? null;
    setAnnouncement(
      `Loaded ${after - before} more${shown !== null ? `. Showing ${after} of ${shown}` : ""}.`,
    );
  }

  return (
    <div className="space-y-3">
      {count && <p className="text-sm text-muted-foreground">{count}</p>}
      {retention && (
        <p className="text-sm text-muted-foreground">
          Audio is kept for {retention}. The text and date stay here after the audio expires.
        </p>
      )}
      <ul className="space-y-2">
        {items.map((gen) => (
          <HistoryItem key={gen.id} gen={gen} />
        ))}
      </ul>
      {hasNextPage && (
        <Button variant="secondary" onClick={() => void loadMore()} disabled={isFetchingNextPage}>
          {isFetchingNextPage ? "Loading more…" : "Load more"}
        </Button>
      )}
      <span role="status" aria-live="polite" className="sr-only">
        {announcement}
      </span>
    </div>
  );
}

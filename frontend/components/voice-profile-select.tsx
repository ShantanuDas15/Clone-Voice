"use client";

import { useId } from "react";

import { useProfiles } from "@/hooks/use-voice-profiles";

interface Props {
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}

/** Select over *ready* profiles only (failed ones would 409 on synthesis); reused by Phase 4. */
export function VoiceProfileSelect({ value, onChange, disabled }: Props) {
  const id = useId();
  const { data, isPending, isError } = useProfiles();
  const ready = (data ?? []).filter((p) => p.status === "ready");

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        Voice
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled || isPending || ready.length === 0}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 block min-h-11 w-full rounded border border-border bg-background px-3"
      >
        <option value="">{isPending ? "Loading…" : "Choose a voice"}</option>
        {ready.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      {isError && (
        <p role="alert" className="mt-1 text-sm">
          Couldn&apos;t load your voices.
        </p>
      )}
      {!isPending && !isError && ready.length === 0 && (
        <p className="mt-1 text-sm text-muted-foreground">
          No voices are ready yet.{" "}
          <a href="/profile" className="underline">
            Create one
          </a>
          .
        </p>
      )}
    </div>
  );
}

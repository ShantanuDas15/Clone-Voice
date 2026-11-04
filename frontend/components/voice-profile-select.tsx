"use client";

import Link from "next/link";

import { useProfiles } from "@/hooks/use-voice-profiles";
import { miniBars } from "@/lib/home-demo";

interface Props {
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}

/** A stable small number from an id, so a voice always gets the same glyph. */
function seedOf(id: string): number {
  let n = 0;
  for (const ch of id) n = (n * 31 + ch.charCodeAt(0)) % 997;
  return (n % 17) + 1;
}

/** A voice's identity mark: small bars shaped from its id (not its audio). Decorative. */
function Glyph({ id }: { id: string }) {
  const bars = miniBars(22, seedOf(id));
  return (
    <svg
      aria-hidden
      focusable="false"
      viewBox="0 0 120 26"
      preserveAspectRatio="none"
      className="gx-glyph"
    >
      {bars.map((v, i) => (
        <rect
          key={i}
          x={i * (120 / 22) + 1}
          y={13 - (v * 26) / 2}
          width={3}
          height={v * 26}
          rx={1.5}
        />
      ))}
    </svg>
  );
}

/**
 * Voice choice as cards (owner-approved mock, UX plan §12.26): one radio per *ready* profile (failed
 * ones would 409 on synthesis), each with a glyph and its clip count. A native radio group, so the
 * arrow keys, labels and screen-reader semantics are the browser's.
 */
export function VoiceProfileSelect({ value, onChange, disabled }: Props) {
  const { data, isPending, isError } = useProfiles();
  const ready = (data ?? []).filter((p) => p.status === "ready");

  return (
    <div>
      <div className="gx-lab">
        <span aria-hidden className="gx-n">
          1
        </span>
        <span id="tts-voice-label">Voice</span>
      </div>
      {ready.length > 0 ? (
        <div role="radiogroup" aria-labelledby="tts-voice-label" className="gx-voices">
          {ready.map((p) => {
            const clips = p.samples?.length ?? 0;
            return (
              <label key={p.id} className="gx-vc">
                <input
                  type="radio"
                  name="tts-voice"
                  className="sr-only"
                  aria-label={p.name}
                  value={p.id}
                  checked={value === p.id}
                  disabled={disabled}
                  onChange={() => onChange(p.id)}
                />
                <span aria-hidden className="gx-tick" />
                <span aria-hidden className="gx-vname">
                  {p.name}
                </span>
                <Glyph id={p.id} />
                {clips > 0 ? (
                  <span aria-hidden className="gx-vnote">
                    {clips} {clips === 1 ? "clip" : "clips"}
                  </span>
                ) : null}
              </label>
            );
          })}
        </div>
      ) : (
        <p role="group" aria-labelledby="tts-voice-label" className="text-sm text-muted-foreground">
          {isPending ? "Loading voices…" : null}
        </p>
      )}
      {isError && (
        <p role="alert" className="mt-1 text-sm">
          Couldn&apos;t load your voices.
        </p>
      )}
      {!isPending && !isError && ready.length === 0 && (
        <p className="mt-1 text-sm text-muted-foreground">
          No voices are ready yet.{" "}
          <Link href="/voices" className="underline">
            Create one
          </Link>
          .
        </p>
      )}
    </div>
  );
}

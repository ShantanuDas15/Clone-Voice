/**
 * Plain names for the voice engines the server reports by id (`generations.engine`,
 * `engine_fallback_from`). The ids (`sv2tts`, `chatterbox_turbo`) are model names that mean nothing
 * to a person; keep this table in step with the backend registry (`TTS_ENGINE` in core/config.py).
 */
const ENGINE_NAMES: Readonly<Record<string, string>> = {
  sv2tts: "Standard",
  chatterbox: "Expressive",
  chatterbox_turbo: "Expressive Turbo",
  chatterbox_nano: "Expressive Nano",
};

/** The standard engine is the unremarkable default, so a row made by it needs no mention. */
export const STANDARD_ENGINE = "sv2tts";

/** A person-facing name for an engine id; an id this app does not know is never shown raw. */
export function engineName(id: string): string {
  return ENGINE_NAMES[id] ?? "another";
}

/**
 * One plain sentence about which engine made a clip, or null when there is nothing to say (the
 * standard engine, or no engine reported). A backup beats the engine line: it explains why the
 * clip may not sound like the engine that was asked for.
 */
export function describeEngine(
  engine: string | null | undefined,
  fallbackFrom: string | null | undefined,
): string | null {
  if (fallbackFrom) {
    return `Made by the backup voice engine (${engineName(fallbackFrom)} was unavailable)`;
  }
  if (engine && engine !== STANDARD_ENGINE) return `Voice engine: ${engineName(engine)}`;
  return null;
}

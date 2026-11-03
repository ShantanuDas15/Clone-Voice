/** Largest clip we will decode just to draw its shape; longer ones fall back to no waveform. */
export const MAX_DECODE_BYTES = 8 * 1024 * 1024;

/**
 * Reduce PCM samples to `buckets` bars: each is the loudest sample in its slice, scaled so the
 * loudest bar is 1. Returns null for silence or no data (nothing worth drawing).
 */
export function bucketPeaks(samples: Float32Array, buckets: number): number[] | null {
  if (samples.length === 0 || buckets <= 0) return null;
  const size = samples.length / buckets;
  const peaks: number[] = [];
  let max = 0;
  for (let b = 0; b < buckets; b += 1) {
    const from = Math.floor(b * size);
    const to = Math.max(from + 1, Math.floor((b + 1) * size));
    let peak = 0;
    for (let i = from; i < to && i < samples.length; i += 1) {
      const v = Math.abs(samples[i] ?? 0);
      if (v > peak) peak = v;
    }
    peaks.push(peak);
    if (peak > max) max = peak;
  }
  return max === 0 ? null : peaks.map((p) => p / max);
}

type AudioContextCtor = typeof AudioContext;

/** `Blob.arrayBuffer()` where it exists, a FileReader where it does not (older engines, jsdom). */
function readBytes(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === "function") return blob.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

/** How loud a take is over time: `levels[n]` is the loudness of the slice that starts at `n * hop` s. */
export interface Envelope {
  /** Seconds each entry covers. */
  hop: number;
  /** 0..1, the loudest slice being 1. Never empty. */
  levels: number[];
}

/** Slice length of the loudness curve: fine enough to follow syllables, coarse enough to stay small. */
export const ENVELOPE_HOP_S = 0.025;

/**
 * Reduce PCM samples to a loudness curve: the RMS of each `hop`-second slice, scaled so the loudest
 * slice is 1 and then eased (power 0.7) so quiet speech still moves it. Returns null for silence or
 * no data.
 */
export function bucketEnvelope(
  samples: Float32Array,
  sampleRate: number,
  hop = ENVELOPE_HOP_S,
): Envelope | null {
  if (samples.length === 0 || !(sampleRate > 0) || !(hop > 0)) return null;
  const size = Math.max(1, Math.round(sampleRate * hop));
  const rms: number[] = [];
  let max = 0;
  for (let from = 0; from < samples.length; from += size) {
    const to = Math.min(samples.length, from + size);
    let sum = 0;
    for (let i = from; i < to; i += 1) {
      const v = samples[i] ?? 0;
      sum += v * v;
    }
    const value = Math.sqrt(sum / (to - from));
    rms.push(value);
    if (value > max) max = value;
  }
  return max === 0 ? null : { hop: size / sampleRate, levels: rms.map((v) => (v / max) ** 0.7) };
}

/** Decode `blob`, or null when that is not possible (no Web Audio, an undecodable codec, too large). */
async function decode(blob: Blob): Promise<AudioBuffer | null> {
  if (blob.size === 0 || blob.size > MAX_DECODE_BYTES) return null;
  const Ctor: AudioContextCtor | undefined =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
  if (!Ctor) return null;
  const ctx = new Ctor();
  try {
    return await ctx.decodeAudioData(await readBytes(blob));
  } finally {
    void ctx.close().catch(() => undefined);
  }
}

/**
 * Decode `blob` in the browser and return its bar heights, or null when that is not possible
 * (no Web Audio, a codec the browser cannot decode, too large). Never throws: the waveform is a
 * nicety and playback must not depend on it.
 */
export async function computePeaks(blob: Blob, buckets = 64): Promise<number[] | null> {
  try {
    const decoded = await decode(blob);
    return decoded ? bucketPeaks(decoded.getChannelData(0), buckets) : null;
  } catch {
    return null;
  }
}

/**
 * The bar heights and the loudness curve of `blob` from ONE decode (the playback pulse needs both).
 * Null when the audio cannot be decoded; the envelope alone is null when it is silent. Never throws.
 */
export async function analyseBlob(
  blob: Blob,
  buckets = 64,
): Promise<{ peaks: number[] | null; envelope: Envelope | null } | null> {
  try {
    const decoded = await decode(blob);
    if (!decoded) return null;
    const samples = decoded.getChannelData(0);
    return {
      peaks: bucketPeaks(samples, buckets),
      envelope: bucketEnvelope(samples, decoded.sampleRate),
    };
  } catch {
    return null;
  }
}

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

/**
 * Decode `blob` in the browser and return its bar heights, or null when that is not possible
 * (no Web Audio, a codec the browser cannot decode, too large). Never throws: the waveform is a
 * nicety and playback must not depend on it.
 */
export async function computePeaks(blob: Blob, buckets = 64): Promise<number[] | null> {
  try {
    if (blob.size === 0 || blob.size > MAX_DECODE_BYTES) return null;
    const Ctor: AudioContextCtor | undefined =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
    if (!Ctor) return null;
    const ctx = new Ctor();
    try {
      const decoded = await ctx.decodeAudioData(await readBytes(blob));
      return bucketPeaks(decoded.getChannelData(0), buckets);
    } finally {
      void ctx.close().catch(() => undefined);
    }
  } catch {
    return null;
  }
}

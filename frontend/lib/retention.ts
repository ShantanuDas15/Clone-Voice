/**
 * Describe how long generated audio is kept, from the server's `output_retention_days`.
 * Returns null when the server gave no usable number (kept until deleted, an older backend, or a
 * failed request), so the UI never states a figure the server did not.
 */
export function describeRetention(days: number | null | undefined): string | null {
  if (typeof days !== "number" || !Number.isFinite(days) || days <= 0) return null;
  if (days >= 1) {
    const n = Math.round(days);
    return `${n} ${n === 1 ? "day" : "days"}`;
  }
  const hours = Math.max(1, Math.round(days * 24));
  return `${hours} ${hours === 1 ? "hour" : "hours"}`;
}

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

/** A clip is "close to expiring" within this many days; further out, saying so is just noise. */
export const EXPIRY_NOTICE_DAYS = 7;

/**
 * How long until audio made at `createdAt` is deleted, when that is soon enough to matter
 * ("3 days", "5 hours", "less than an hour"). Null when the server gave no retention period, the
 * date is unreadable, the clip is already past it (the server answers 410 and the row says so), or
 * it is further away than EXPIRY_NOTICE_DAYS. Never states a figure the server did not.
 */
export function expiresSoon(
  createdAt: string,
  retentionDays: number | null | undefined,
  now: number = Date.now(),
): string | null {
  if (typeof retentionDays !== "number" || !Number.isFinite(retentionDays) || retentionDays <= 0) {
    return null;
  }
  const created = Date.parse(createdAt);
  if (Number.isNaN(created)) return null;
  const remainingDays = (created + retentionDays * 86_400_000 - now) / 86_400_000;
  if (remainingDays <= 0 || remainingDays > EXPIRY_NOTICE_DAYS) return null;
  if (remainingDays >= 1) {
    const n = Math.floor(remainingDays);
    return `${n} ${n === 1 ? "day" : "days"}`;
  }
  const hours = Math.floor(remainingDays * 24);
  if (hours < 1) return "less than an hour";
  return `${hours} ${hours === 1 ? "hour" : "hours"}`;
}

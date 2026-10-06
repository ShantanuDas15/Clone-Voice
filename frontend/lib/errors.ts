/**
 * ApiError normalizer (FRONTEND_IMPLEMENTATION_PLAN.md §5.5).
 *
 * The backend emits four error shapes and no machine codes (G-04):
 *   {detail: string} | {detail: [{loc,msg,type}]} | {error: string} (slowapi 429) | plain text.
 * `kind` is derived from status first, then from exact backend strings (STRING_KINDS);
 * the table disappears once BD-3 ships real codes.
 */

export type ApiErrorKind =
  | "NETWORK"
  | "TIMEOUT"
  | "CANCELLED"
  | "VALIDATION"
  | "UNAUTHENTICATED"
  | "EMAIL_UNVERIFIED"
  | "BAD_PASSWORD"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "GONE"
  | "TERMS_CHANGED"
  | "PROFILE_NOT_READY"
  | "CONFLICT"
  | "PAYLOAD_TOO_LARGE"
  | "RATE_LIMITED"
  | "BUSY"
  | "SERVER"
  | "UNKNOWN";

/** Exact backend `detail` strings that disambiguate a shared status code. */
const STRING_KINDS: ReadonlyArray<{ status: number; match: RegExp; kind: ApiErrorKind }> = [
  { status: 403, match: /^Email address not verified/i, kind: "EMAIL_UNVERIFIED" },
  { status: 403, match: /^Incorrect password/i, kind: "BAD_PASSWORD" },
  { status: 409, match: /terms.*changed/i, kind: "TERMS_CHANGED" },
  { status: 409, match: /not ready/i, kind: "PROFILE_NOT_READY" },
];

const STATUS_KINDS: Readonly<Record<number, ApiErrorKind>> = {
  401: "UNAUTHENTICATED",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  409: "CONFLICT",
  410: "GONE",
  413: "PAYLOAD_TOO_LARGE",
  422: "VALIDATION",
  429: "RATE_LIMITED",
};

/** User-facing copy per kind. Server text is never echoed for 5xx. */
const DEFAULT_MESSAGES: Readonly<Record<ApiErrorKind, string>> = {
  NETWORK: "Can't reach the server. Check your connection and try again.",
  TIMEOUT: "The request took too long. Check History before trying again.",
  CANCELLED: "The request was cancelled.",
  VALIDATION: "Some of the information you entered isn't valid.",
  UNAUTHENTICATED: "Your session has expired. Please sign in again.",
  EMAIL_UNVERIFIED: "Please verify your email address to continue.",
  BAD_PASSWORD: "That password is incorrect.",
  FORBIDDEN: "You don't have permission to do that.",
  NOT_FOUND: "That item no longer exists.",
  GONE: "That item is no longer available.",
  TERMS_CHANGED: "The terms have changed. Please review and accept them again.",
  PROFILE_NOT_READY: "That voice isn't ready yet.",
  CONFLICT: "That conflicts with the current state. Refresh and try again.",
  PAYLOAD_TOO_LARGE: "That file is too large.",
  RATE_LIMITED: "Too many requests. Please wait a moment and try again.",
  BUSY: "The service is busy. Please try again shortly.",
  SERVER: "Something went wrong on our side. Please try again.",
  UNKNOWN: "Something went wrong. Please try again.",
};

export interface FieldError {
  field: string;
  message: string;
}

export interface ApiErrorInit {
  status: number;
  kind: ApiErrorKind;
  message: string;
  fieldErrors?: FieldError[];
  retryAfterSec?: number;
  requestId?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  readonly fieldErrors: FieldError[];
  readonly retryAfterSec?: number;
  readonly requestId?: string;

  constructor(init: ApiErrorInit) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.kind = init.kind;
    this.fieldErrors = init.fieldErrors ?? [];
    this.retryAfterSec = init.retryAfterSec;
    this.requestId = init.requestId;
  }
}

/** Minimal transport-neutral view of a failed HTTP exchange. */
export interface RawFailure {
  /** HTTP status; 0 for network errors, timeouts and cancellations. */
  status: number;
  /** Response body: parsed JSON, string, Blob, or undefined. */
  data?: unknown;
  headers?: Record<string, string | undefined>;
  code?: "NETWORK" | "TIMEOUT" | "CANCELLED";
}

function header(headers: RawFailure["headers"], name: string): string | undefined {
  if (!headers) return undefined;
  const lower = name.toLowerCase();
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === lower) return value;
  }
  return undefined;
}

/** Parse `Retry-After` given as delta-seconds or an HTTP date. */
export function parseRetryAfter(
  value: string | undefined,
  now: number = Date.now(),
): number | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed);
  const date = Date.parse(trimmed);
  if (Number.isNaN(date)) return undefined;
  return Math.max(0, Math.ceil((date - now) / 1000));
}

/** Read a Blob as text; falls back to FileReader where `Blob.text()` is missing. */
function readBlobText(blob: Blob): Promise<string> {
  if (typeof blob.text === "function") return blob.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

/** Axios `responseType: "blob"` delivers error bodies as Blobs; decode them to JSON/text. */
export async function decodeBlobBody(data: unknown): Promise<unknown> {
  if (typeof Blob === "undefined" || !(data instanceof Blob)) return data;
  const text = await readBlobText(data);
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

interface Extracted {
  message?: string;
  fieldErrors: FieldError[];
}

function extract(body: unknown): Extracted {
  if (typeof body === "string") return { message: body.trim() || undefined, fieldErrors: [] };
  if (!isRecord(body)) return { fieldErrors: [] };

  const { detail, error } = body;
  if (typeof detail === "string") return { message: detail, fieldErrors: [] };
  if (typeof error === "string") return { message: error, fieldErrors: [] };

  if (Array.isArray(detail)) {
    const fieldErrors: FieldError[] = [];
    for (const item of detail) {
      if (!isRecord(item) || typeof item.msg !== "string") continue;
      const loc = Array.isArray(item.loc) ? item.loc : [];
      // Drop the leading "body"/"query" segment FastAPI prepends.
      const path = loc.filter(
        (p): p is string | number => typeof p === "string" || typeof p === "number",
      );
      const field = path.slice(path[0] === "body" || path[0] === "query" ? 1 : 0).join(".");
      fieldErrors.push({ field, message: item.msg.replace(/^Value error, /, "") });
    }
    return { message: fieldErrors[0]?.message, fieldErrors };
  }
  return { fieldErrors: [] };
}

function kindFor(status: number, serverMessage: string | undefined): ApiErrorKind {
  if (serverMessage) {
    const hit = STRING_KINDS.find((e) => e.status === status && e.match.test(serverMessage));
    if (hit) return hit.kind;
  }
  if (status === 503 || (status === 429 && serverMessage && /busy/i.test(serverMessage))) {
    return "BUSY";
  }
  const byStatus = STATUS_KINDS[status];
  if (byStatus) return byStatus;
  if (status >= 500) return "SERVER";
  return "UNKNOWN";
}

/** Build an ApiError from any failed exchange. Pure apart from decoding Blob bodies. */
export async function normalizeError(failure: RawFailure): Promise<ApiError> {
  const requestId = header(failure.headers, "x-request-id");

  if (failure.status === 0) {
    const kind: ApiErrorKind = failure.code ?? "NETWORK";
    return new ApiError({ status: 0, kind, message: DEFAULT_MESSAGES[kind], requestId });
  }

  const body = await decodeBlobBody(failure.data);
  const { message: serverMessage, fieldErrors } = extract(body);
  const kind = kindFor(failure.status, serverMessage);
  const retryAfterSec = parseRetryAfter(header(failure.headers, "retry-after"));

  // 4xx server text is written for clients and safe to show; 5xx text never is.
  const showServerText =
    failure.status < 500 && serverMessage !== undefined && kind !== "UNAUTHENTICATED";
  const message = showServerText ? serverMessage : DEFAULT_MESSAGES[kind];

  return new ApiError({
    status: failure.status,
    kind,
    message,
    fieldErrors,
    retryAfterSec,
    requestId,
  });
}

/**
 * In-memory session core (plan §5.3).
 *
 * - The access token lives only in this module's memory; it is never written to storage.
 * - Refresh tokens rotate and are single-use (G-22), so refreshes are serialized:
 *   one in-flight promise per tab (single-flight) plus a cross-tab Web Lock. A tab that
 *   waited on the lock adopts a token another tab broadcast meanwhile instead of refreshing.
 */
import { plainClient } from "@/lib/api/plain";
import { ApiError } from "@/lib/errors";

export type SessionEvent = "token" | "cleared";
type Listener = (event: SessionEvent) => void;

interface TokenResponse {
  access_token: string;
}

type ChannelMessage = { type: "token"; token: string } | { type: "logout" };

const CHANNEL_NAME = "clonevoice-auth";
const LOCK_NAME = "clonevoice-refresh";

let accessToken: string | null = null;
let inflight: Promise<string | null> | null = null;
let lastAdoptableToken: { token: string; at: number } | null = null;
const listeners = new Set<Listener>();
let channel: BroadcastChannel | null | undefined;

function emit(event: SessionEvent): void {
  listeners.forEach((l) => l(event));
}

function getChannel(): BroadcastChannel | null {
  if (channel !== undefined) return channel;
  if (typeof BroadcastChannel === "undefined") {
    channel = null;
    return channel;
  }
  channel = new BroadcastChannel(CHANNEL_NAME);
  channel.onmessage = (e: MessageEvent<ChannelMessage>) => handleChannelMessage(e.data);
  return channel;
}

function post(message: ChannelMessage): void {
  getChannel()?.postMessage(message);
}

/** Apply a message from another tab. Exported for tests. */
export function handleChannelMessage(message: ChannelMessage): void {
  if (message.type === "token") {
    accessToken = message.token;
    lastAdoptableToken = { token: message.token, at: Date.now() };
    emit("token");
  } else if (message.type === "logout") {
    clearSession({ broadcast: false });
  }
}

/** Start listening for other tabs' events; safe to call repeatedly. */
export function initSessionSync(): void {
  getChannel();
}

export function getAccessToken(): string | null {
  return accessToken;
}

/** Store a freshly issued token (login/signup/refresh) and tell other tabs. */
export function setAccessToken(token: string): void {
  accessToken = token;
  post({ type: "token", token });
  emit("token");
}

/** Drop the session in this tab; by default also log out the other tabs. */
export function clearSession(options: { broadcast?: boolean } = {}): void {
  const wasSet = accessToken !== null;
  accessToken = null;
  lastAdoptableToken = null;
  if (options.broadcast ?? true) post({ type: "logout" });
  if (wasSet || options.broadcast === false) emit("cleared");
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function requestRefresh(): Promise<string | null> {
  try {
    const { data } = await plainClient.post<TokenResponse>("/auth/refresh");
    setAccessToken(data.access_token);
    return data.access_token;
  } catch (error) {
    // 401 means "no valid session": a normal signed-out outcome, not a failure.
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

async function refreshUnderLock(): Promise<string | null> {
  const startedAt = Date.now();
  const run = async (): Promise<string | null> => {
    if (lastAdoptableToken && lastAdoptableToken.at >= startedAt) return lastAdoptableToken.token;
    return requestRefresh();
  };
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (!locks) return run();
  return locks.request(LOCK_NAME, run);
}

/**
 * Obtain a new access token via the refresh cookie. Resolves null when there is no valid
 * session. Concurrent callers share one request. Never retried automatically (R5).
 */
export function refreshAccessToken(): Promise<string | null> {
  if (!inflight) {
    inflight = refreshUnderLock().finally(() => {
      inflight = null;
    });
  }
  return inflight;
}

/** Test helper: reset module state. */
export function __resetSessionForTests(): void {
  accessToken = null;
  inflight = null;
  lastAdoptableToken = null;
  listeners.clear();
}

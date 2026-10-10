import { MAX_BODY_BYTES, ReportLimiter, clientKey, parseCspReports } from "@/lib/csp-report";

// Reports are tiny and never cached; the route must run per request on the Node runtime.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const limiter = new ReportLimiter();
const NO_CONTENT = () => new Response(null, { status: 204 });

/** Read at most `max` bytes of the body; returns null when the body is larger. */
async function readLimited(request: Request, max: number): Promise<string | null> {
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (declared > max) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > max) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  return new TextDecoder().decode(Buffer.concat(chunks));
}

/**
 * Receives CSP violation reports. It always answers 204 so a probe learns nothing, stores
 * nothing, and writes one structured line per accepted report from scrubbed fields only.
 */
export async function POST(request: Request): Promise<Response> {
  if (!limiter.allow(clientKey(request.headers))) return NO_CONTENT();
  const text = await readLimited(request, MAX_BODY_BYTES);
  if (text === null) return NO_CONTENT();
  for (const report of parseCspReports(request.headers.get("content-type"), text)) {
    process.stdout.write(`${JSON.stringify({ event: "csp-violation", ...report })}\n`);
  }
  return NO_CONTENT();
}

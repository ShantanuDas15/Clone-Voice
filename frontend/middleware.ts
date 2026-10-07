import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { buildCsp, cspHeaderName, generateNonce } from "@/lib/csp";

/**
 * Per-request CSP with a nonce. Next.js reads the nonce from the request's CSP header and
 * applies it to its own scripts. Report-only until `CSP_ENFORCE=1` (server env) after a soak.
 */
export function middleware(request: NextRequest) {
  const nonce = generateNonce();
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
  let apiOrigin = "";
  try {
    apiOrigin = new URL(apiBase).origin;
  } catch {
    // Missing/invalid: lib/env.ts fails the app loudly; the CSP simply omits the API host.
  }
  let reportingOrigin: string | undefined;
  try {
    const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
    reportingOrigin = dsn ? new URL(dsn).origin : undefined;
  } catch {
    // An invalid DSN is rejected by lib/env.ts; the CSP simply omits it.
  }
  const csp = buildCsp({
    nonce,
    apiOrigin,
    reportingOrigin,
    development: process.env.NODE_ENV === "development",
  });
  const headerName = cspHeaderName(process.env.CSP_ENFORCE === "1");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set(headerName, csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set(headerName, csp);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};

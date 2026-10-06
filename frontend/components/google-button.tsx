import { env } from "@/lib/env";
import { googleStartUrl } from "@/lib/api/auth";

/** Plain link: the OAuth flow needs a full-page navigation to the API, never XHR. */
export function GoogleButton() {
  return (
    <a
      href={googleStartUrl(env.NEXT_PUBLIC_API_BASE_URL)}
      className="flex min-h-11 w-full items-center justify-center rounded border border-border px-4 py-2"
    >
      Continue with Google
    </a>
  );
}

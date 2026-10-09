import { GoogleMark } from "@/components/google-mark";
import { buttonVariants } from "@/components/ui/button";
import { env } from "@/lib/env";
import { googleStartUrl } from "@/lib/api/auth";

/** Plain link: the OAuth flow needs a full-page navigation to the API, never XHR. */
export function GoogleButton() {
  return (
    <a
      href={googleStartUrl(env.NEXT_PUBLIC_API_BASE_URL)}
      className={buttonVariants({ variant: "secondary", fullWidth: true }) + " gap-2"}
    >
      <GoogleMark />
      Continue with Google
    </a>
  );
}

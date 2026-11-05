"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm, useWatch } from "react-hook-form";
import { notify } from "@/lib/toast";

import { useAuth } from "@/components/auth-provider";
import { AccountRing } from "@/components/account-ring";
import { TextField } from "@/components/form-fields";
import { ResendVerification } from "@/components/resend-verification";
import { HISTORY_KEY, useProfiles } from "@/hooks/use-voice-profiles";
import * as authApi from "@/lib/api/auth";
import { fetchHistory } from "@/lib/api/history";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { ApiError } from "@/lib/errors";
import { saveBlob } from "@/lib/download";
import { formatDate } from "@/lib/format";
import { pulseVoice } from "@/lib/voice-energy";
import { DELETE_CONFIRMATION, type NameValues, nameSchema } from "@/lib/validation/auth";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";

/** Who you are: the voiceprint ring, the display-name form, and the few facts that never change. */
function ProfileCard({ paused }: { paused: boolean }) {
  const { user, applyUser } = useAuth();
  const inFlight = useRef(false);
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors, isSubmitting, isDirty },
    reset,
  } = useForm<NameValues>({
    resolver: zodResolver(nameSchema),
    defaultValues: { name: user?.name ?? "" },
  });

  const typed = useWatch({ control, name: "name" });

  const onSubmit = handleSubmit(async (values) => {
    if (!user || inFlight.current) return; // R4
    inFlight.current = true;
    const previous = user;
    applyUser({ ...user, name: values.name }); // optimistic
    try {
      const saved = await authApi.updateName(values.name);
      applyUser(saved);
      reset({ name: saved.name });
      pulseVoice(1);
      notify.success("Name updated.");
    } catch (e) {
      applyUser(previous); // rollback
      const message = e instanceof ApiError ? e.message : "Couldn't update your name.";
      const fieldMessage =
        e instanceof ApiError ? e.fieldErrors?.find((f) => f.field === "name")?.message : undefined;
      setError("name", { message: fieldMessage ?? message });
    } finally {
      inFlight.current = false;
    }
  });

  if (!user) return null;
  return (
    <section
      id="s-profile"
      aria-labelledby="profile"
      className="ax-card ax-glow ax-section"
      data-section="profile"
    >
      <div className="ax-head">
        <h2 id="profile" className="text-xl font-semibold">
          Profile
        </h2>
        {user.email_verified_at ? (
          <Badge tone="success">Verified</Badge>
        ) : (
          <Badge tone="notice">Not verified</Badge>
        )}
      </div>
      <div className="ax-id">
        <AccountRing name={typed ?? ""} paused={paused} />
        <div className="ax-who">
          <form
            onSubmit={onSubmit}
            noValidate
            className="ax-name-row"
            aria-label="Change your name"
          >
            <TextField
              label="Display name"
              autoComplete="name"
              error={errors.name?.message}
              {...register("name", { onChange: () => pulseVoice(0.6) })}
            />
            <Button type="submit" disabled={isSubmitting || !isDirty}>
              {isSubmitting ? "Saving…" : "Save name"}
            </Button>
          </form>
          <dl className="ax-facts">
            <div>
              <dt>Email</dt>
              <dd className="[overflow-wrap:anywhere]">{user.email}</dd>
            </div>
            <div>
              <dt>Member since</dt>
              <dd>{formatDate(user.created_at)}</dd>
            </div>
          </dl>
        </div>
      </div>
      {!user.email_verified_at && (
        <div className="ax-alert" role="status">
          <p>
            <strong>Verify your email to start.</strong> You can&apos;t create voices or generate
            speech until you verify.
          </p>
          <ResendVerification />
        </div>
      )}
    </section>
  );
}

/** How you get in: each way to sign in, and whether it is set up. */
function SecurityCard() {
  const { user } = useAuth();
  if (!user) return null;
  const google = user.provider === "google";
  return (
    <section
      id="s-security"
      aria-labelledby="security"
      className="ax-card ax-section"
      data-section="security"
    >
      <div className="ax-head">
        <h2 id="security" className="text-xl font-semibold">
          Sign-in and security
        </h2>
        <p className="ax-sub">How you get in.</p>
      </div>
      <ul className="ax-methods">
        <li className={google ? "ax-method" : "ax-method ax-off"}>
          <span aria-hidden className="ax-method-icon">
            G
          </span>
          <div>
            <b>Google</b>
            <small>
              {google ? "Sign in with your Google account." : "Not used for this account."}
            </small>
          </div>
          {google ? <Badge tone="success">Connected</Badge> : <Badge>Not used</Badge>}
        </li>
        <li className={user.has_password ? "ax-method" : "ax-method ax-off"}>
          <span aria-hidden className="ax-method-icon">
            •••
          </span>
          <div>
            <b>Password</b>
            <small>
              {user.has_password
                ? "Set. We never show it."
                : "Not set. Add one to sign in without Google."}
            </small>
          </div>
          <Link
            href="/forgot-password"
            className="-my-3 inline-flex min-h-11 items-center underline"
          >
            {user.has_password ? "Reset it by email" : "Set one by email"}
          </Link>
        </li>
      </ul>
    </section>
  );
}

/** What is stored for you, from the lists the app already loads (nothing until they have). */
function useStored() {
  const profiles = useProfiles();
  const generated = useQuery({
    queryKey: [...HISTORY_KEY, "count"],
    queryFn: ({ signal }) => fetchHistory(0, signal, 1),
    staleTime: 60_000,
  });
  const voices = profiles.data?.filter((p) => p.status === "ready").length ?? null;
  const clips = profiles.data?.reduce((sum, p) => sum + (p.samples?.length ?? 0), 0) ?? null;
  return { voices, clips, generated: generated.data?.total ?? null };
}

/** Three counters, drawn in once; hidden until the lists have loaded so a number is never a guess. */
function StoredCounts({ stored }: { stored: ReturnType<typeof useStored> }) {
  const items = [
    { label: "voices", value: stored.voices },
    { label: "enrolment clips", value: stored.clips },
    { label: "generated clips", value: stored.generated },
  ];
  if (items.some((i) => i.value === null)) return null;
  return (
    <ul className="ax-counts" aria-label="What is stored for you">
      {items.map((i) => (
        <li key={i.label} className="ax-count">
          <strong className="ax-count-n">{i.value}</strong>
          <span>{i.label}</span>
        </li>
      ))}
    </ul>
  );
}

function ExportData() {
  const { user } = useAuth();
  const inFlight = useRef(false);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!user) return null;
  const needsPassword = user.has_password;

  function cancel() {
    setOpen(false);
    setPassword("");
    setError(null);
  }

  async function onExport() {
    if (inFlight.current) return;
    if (needsPassword && !password) {
      setError("Enter your password to confirm.");
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const blob = await authApi.exportAccountData(needsPassword ? password : undefined);
      saveBlob(blob, `clonevoice-export-${new Date().toISOString().slice(0, 10)}.zip`);
      notify.success("Your data export has been downloaded.");
      cancel();
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.kind === "BAD_PASSWORD") setError("That password is incorrect.");
      else if (e.kind === "RATE_LIMITED")
        setError(e.retryAfterSec ? rateLimitMessage(e) : e.message);
      else setError(e.message);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="ax-foot">
      <p className="text-sm text-muted-foreground">
        One zip. It holds your voice recordings, so keep it private.
      </p>
      <Button onClick={() => setOpen(true)} aria-haspopup="dialog">
        Download my data…
      </Button>
      {open && (
        <Dialog titleId="export-data-title" onClose={cancel} closeDisabled={busy}>
          <h3 id="export-data-title" className="font-medium">
            Download your data?
          </h3>
          <p className="text-sm">
            This can take a little while if you have a lot of audio. Keep the file private: it
            contains your voice recordings.
          </p>
          {needsPassword ? (
            <TextField
              label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          ) : (
            <p className="text-sm">
              You signed in with Google, so no password is needed. Your current session confirms
              it&apos;s you.
            </p>
          )}
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="flex gap-2">
            <Button onClick={() => void onExport()} disabled={busy}>
              {busy ? "Preparing…" : "Download"}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={cancel}>
              Cancel
            </Button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function DeleteAccount() {
  const { user, discardSession } = useAuth();
  const router = useRouter();
  const inFlight = useRef(false);
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!user) return null;
  const confirmed = typed === DELETE_CONFIRMATION;
  const needsPassword = user.has_password;

  function cancel() {
    setOpen(false);
    setTyped("");
    setPassword("");
    setError(null);
  }

  function finish() {
    discardSession();
    notify.success("Your account and all its data have been deleted.");
    router.replace("/");
  }

  async function onDelete() {
    if (inFlight.current || !confirmed) return;
    if (needsPassword && !password) {
      setError("Enter your password to confirm.");
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await authApi.deleteAccount(needsPassword ? password : undefined);
      finish();
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.status === 0 || e.kind === "TIMEOUT") {
        // Ambiguous: the erase may have completed. A 401 on /me means it did.
        try {
          await authApi.fetchMe();
          setError("We couldn't confirm the deletion. Your account still exists; try again.");
        } catch (check) {
          if (check instanceof ApiError && check.status === 401) finish();
          else setError("We couldn't confirm the deletion. Check your connection and try again.");
        }
      } else if (e.kind === "BAD_PASSWORD") setError("That password is incorrect.");
      else if (e.kind === "RATE_LIMITED") setError(rateLimitMessage(e));
      else setError(e.message);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm">
        This permanently erases your account, every voice and every generated clip. It can&apos;t be
        undone.
      </p>
      <Button variant="secondary" onClick={() => setOpen(true)} aria-haspopup="dialog">
        Delete my account…
      </Button>
      {open && (
        <Dialog titleId="del-account-title" onClose={cancel} closeDisabled={busy}>
          <h3 id="del-account-title" className="font-medium">
            Delete your account?
          </h3>
          <p className="text-sm">
            This permanently erases your account, every voice and every generated clip. It
            can&apos;t be undone.
          </p>
          <TextField
            label={`Type ${DELETE_CONFIRMATION} to confirm`}
            autoComplete="off"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          {needsPassword ? (
            <TextField
              label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          ) : (
            <p className="text-sm">
              You signed in with Google, so no password is needed. Your current session confirms
              it&apos;s you.
            </p>
          )}
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="flex gap-2">
            <Button variant="danger" onClick={() => void onDelete()} disabled={!confirmed || busy}>
              {busy ? "Deleting…" : "Delete account"}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={cancel}>
              Cancel
            </Button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

const SECTIONS = [
  { id: "s-profile", label: "Profile" },
  { id: "s-security", label: "Sign-in and security" },
  { id: "s-data", label: "Your data" },
  { id: "s-delete", label: "Delete account" },
] as const;

/** The section nav: plain in-page links; the one in view is marked `aria-current`. */
function SectionRail() {
  const [current, setCurrent] = useState<string>(SECTIONS[0].id);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const seen = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setCurrent(e.target.id);
      },
      { rootMargin: "-30% 0px -60% 0px" },
    );
    for (const { id } of SECTIONS) {
      const el = document.getElementById(id);
      if (el) seen.observe(el);
    }
    return () => seen.disconnect();
  }, []);
  return (
    <nav aria-label="Account sections" className="ax-rail">
      {SECTIONS.map(({ id, label }) => (
        <a
          key={id}
          href={`#${id}`}
          aria-current={current === id ? "true" : undefined}
          data-danger={id === "s-delete" ? true : undefined}
        >
          {label}
        </a>
      ))}
    </nav>
  );
}

/** Account details, display-name editing, a copy of your data, and irreversible account erasure. */
export function AccountSection() {
  const { user } = useAuth();
  const [paused, setPaused] = useState(false);
  const stored = useStored();
  if (!user) return null;
  return (
    <div className="ax-root" data-motion={paused ? "paused" : "on"}>
      <div aria-hidden className="ax-aurora">
        <i className="ax-a" />
        <i className="ax-b" />
      </div>
      <div className="ax-layout">
        <SectionRail />
        <div className="ax-stack">
          <ProfileCard paused={paused} />
          <SecurityCard />
          <section
            id="s-data"
            aria-labelledby="export"
            className="ax-card ax-section"
            data-section="data"
          >
            <div className="ax-head">
              <h2 id="export" className="text-xl font-semibold">
                Your data
              </h2>
              <p className="ax-sub">What we hold, and what you can take.</p>
            </div>
            <StoredCounts stored={stored} />
            <div className="ax-two">
              <ul className="ax-list" aria-label="In the download">
                <li className="ax-list-title" aria-hidden>
                  In the download
                </li>
                <li>Your account details</li>
                <li>Your voices and their recordings</li>
                <li>Everything you generated, with its audio</li>
              </ul>
              <ul className="ax-list ax-list-no" aria-label="Not in the download">
                <li className="ax-list-title" aria-hidden>
                  Not in the download
                </li>
                <li>Your password or sign-in sessions</li>
                <li>Voice embeddings, the model&apos;s private fingerprint of a voice</li>
              </ul>
            </div>
            <ExportData />
          </section>
          <section
            id="s-delete"
            aria-labelledby="danger"
            className="ax-card ax-danger ax-section"
            data-section="delete"
          >
            <div className="ax-head">
              <h2 id="danger" className="text-xl font-semibold">
                Delete account
              </h2>
            </div>
            <DeleteAccount />
            {stored.voices !== null && stored.clips !== null && stored.generated !== null && (
              <ul className="ax-erase" aria-label="What will be erased">
                <li>Account and sign-in</li>
                <li>{stored.voices === 1 ? "1 voice" : `${stored.voices} voices`}</li>
                <li>{stored.clips === 1 ? "1 clip" : `${stored.clips} clips`}</li>
                <li>
                  {stored.generated === 1
                    ? "1 generated clip"
                    : `${stored.generated} generated clips`}
                </li>
              </ul>
            )}
          </section>
          <div className="flex justify-end">
            <button
              type="button"
              aria-pressed={paused}
              onClick={() => setPaused((p) => !p)}
              className="ax-motion"
            >
              {paused ? "Resume motion" : "Pause motion"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

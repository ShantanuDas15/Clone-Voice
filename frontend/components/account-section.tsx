"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { type ReactNode, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useAuth } from "@/components/auth-provider";
import { TextField } from "@/components/form-fields";
import { useDialog } from "@/hooks/use-dialog";
import * as authApi from "@/lib/api/auth";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { ApiError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { DELETE_CONFIRMATION, type NameValues, nameSchema } from "@/lib/validation/auth";

function NameForm() {
  const { user, applyUser } = useAuth();
  const inFlight = useRef(false);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isDirty },
    reset,
  } = useForm<NameValues>({
    resolver: zodResolver(nameSchema),
    defaultValues: { name: user?.name ?? "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    if (!user || inFlight.current) return; // R4
    inFlight.current = true;
    const previous = user;
    applyUser({ ...user, name: values.name }); // optimistic
    try {
      const saved = await authApi.updateName(values.name);
      applyUser(saved);
      reset({ name: saved.name });
      toast.success("Name updated.");
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

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-3">
      <TextField
        label="Display name"
        autoComplete="name"
        error={errors.name?.message}
        {...register("name")}
      />
      <button
        type="submit"
        disabled={isSubmitting || !isDirty}
        className="min-h-11 rounded bg-primary px-4 text-primary-foreground disabled:opacity-60"
      >
        {isSubmitting ? "Saving…" : "Save name"}
      </button>
    </form>
  );
}

/** The account-erasure modal: traps focus, closes on Escape unless a request is in flight. */
function ModalPanel({
  onClose,
  closeDisabled,
  children,
}: {
  onClose: () => void;
  closeDisabled: boolean;
  children: ReactNode;
}) {
  const ref = useDialog<HTMLDivElement>(onClose, closeDisabled);
  return (
    <div
      ref={ref}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="del-account-title"
      className="space-y-3 rounded border border-border bg-muted p-4"
    >
      {children}
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
    toast.success("Your account and all its data have been deleted.");
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
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        className="min-h-11 rounded border border-line px-4"
      >
        Delete my account…
      </button>
      {open && (
        <ModalPanel onClose={cancel} closeDisabled={busy}>
          <h3 id="del-account-title" className="font-medium">
            Delete your account?
          </h3>
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
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void onDelete()}
              disabled={!confirmed || busy}
              className="min-h-11 rounded bg-primary px-4 text-primary-foreground disabled:opacity-60"
            >
              {busy ? "Deleting…" : "Delete account"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={cancel}
              className="min-h-11 rounded border border-line px-4"
            >
              Cancel
            </button>
          </div>
        </ModalPanel>
      )}
    </div>
  );
}

/** Account details, display-name editing and irreversible account erasure. */
export function AccountSection() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <div className="space-y-6">
      <dl className="space-y-1 text-sm">
        <div className="flex gap-2">
          <dt className="shrink-0 text-muted-foreground">Email</dt>
          <dd className="min-w-0 [overflow-wrap:anywhere]">{user.email}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Sign-in</dt>
          <dd>
            {user.provider === "google"
              ? user.has_password
                ? "Google and password"
                : "Google"
              : "Email and password"}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">Member since</dt>
          <dd>{formatDateTime(user.created_at)}</dd>
        </div>
      </dl>
      <NameForm />
      <section aria-labelledby="danger" className="space-y-3 border-t border-border pt-6">
        <h3 id="danger" className="font-medium">
          Delete account
        </h3>
        <DeleteAccount />
      </section>
    </div>
  );
}

import { type InputHTMLAttributes, forwardRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Input } from "@/components/ui/field";

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  /** Always-visible guidance shown under the field, e.g. the rule a password must meet. */
  hint?: string;
}

/** Labelled input with an associated hint and an associated, announced error message. */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, error, hint, id, ...props },
  ref,
) {
  const inputId = id ?? props.name ?? label;
  const describedBy =
    [hint ? `${inputId}-hint` : null, error ? `${inputId}-error` : null]
      .filter(Boolean)
      .join(" ") || undefined;
  return (
    <div>
      <label htmlFor={inputId} className="block text-sm font-medium">
        {label}
      </label>
      <Input
        id={inputId}
        ref={ref}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...props}
      />
      {hint && (
        <p id={`${inputId}-hint`} className="mt-1 text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <Alert tone="danger" id={`${inputId}-error`} className="mt-1">
          {error}
        </Alert>
      )}
    </div>
  );
});

/** A password field with a "Show password" switch so a typo can be checked before submitting. */
export const PasswordField = forwardRef<
  HTMLInputElement,
  Omit<TextFieldProps, "type"> & { showLabel?: string }
>(function PasswordField({ showLabel = "Show password", ...props }, ref) {
  const [shown, setShown] = useState(false);
  return (
    <div>
      <TextField ref={ref} type={shown ? "text" : "password"} {...props} />
      <label className="mt-1 flex min-h-11 items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={shown}
          onChange={(e) => setShown(e.target.checked)}
          className="h-4 w-4"
        />
        {showLabel}
      </label>
    </div>
  );
});

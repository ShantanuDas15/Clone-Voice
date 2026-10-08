import { type InputHTMLAttributes, forwardRef } from "react";

import { Input } from "@/components/ui/field";
import { Alert } from "@/components/ui/alert";

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

/** Labelled input with an associated, announced error message. */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, error, id, ...props },
  ref,
) {
  const inputId = id ?? props.name ?? label;
  return (
    <div>
      <label htmlFor={inputId} className="block text-sm font-medium">
        {label}
      </label>
      <Input
        id={inputId}
        ref={ref}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : undefined}
        {...props}
      />
      {error && (
        <Alert tone="danger" id={`${inputId}-error`} className="mt-1">
          {error}
        </Alert>
      )}
    </div>
  );
});

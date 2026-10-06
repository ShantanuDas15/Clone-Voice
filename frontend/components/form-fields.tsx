import { type InputHTMLAttributes, forwardRef } from "react";

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
      <input
        id={inputId}
        ref={ref}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : undefined}
        className="mt-1 block min-h-11 w-full rounded border border-border bg-background px-3 py-2"
        {...props}
      />
      {error && (
        <p
          id={`${inputId}-error`}
          role="alert"
          className="mt-1 text-sm text-red-600 dark:text-red-400"
        >
          {error}
        </p>
      )}
    </div>
  );
});

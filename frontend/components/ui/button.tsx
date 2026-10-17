import { type VariantProps, cva } from "class-variance-authority";
import { type ButtonHTMLAttributes, forwardRef } from "react";

/**
 * The one button recipe (FRONTEND_UX_IMPROVEMENT_PLAN.md §4.7). Variants differ by role, never by
 * ad-hoc classes; the focus ring comes from the global `:focus-visible` rule in globals.css.
 */
export const buttonVariants = cva(
  "inline-flex items-center justify-center rounded font-medium transition-colors duration-fast disabled:cursor-not-allowed disabled:opacity-60 aria-busy:cursor-progress aria-busy:opacity-60",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-foreground hover:bg-primary/90 active:bg-primary/80 disabled:hover:bg-primary",
        secondary:
          "border border-line bg-surface hover:bg-muted active:bg-muted/70 disabled:hover:bg-surface",
        quiet: "underline underline-offset-2 hover:bg-muted active:bg-muted/70",
        danger:
          "bg-danger text-danger-foreground hover:bg-danger/90 active:bg-danger/80 disabled:hover:bg-danger",
      },
      size: {
        md: "min-h-11 px-4 py-2",
        sm: "min-h-11 px-3 py-2 text-sm",
      },
      fullWidth: { true: "w-full", false: "" },
    },
    defaultVariants: { variant: "primary", size: "md", fullWidth: false },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  /**
   * Marks the button busy (`aria-busy`, `aria-disabled`); the label stays so the layout does not
   * jump. A busy button ignores clicks but is not `disabled`, so it keeps keyboard focus (a
   * disabled button drops focus to the page).
   */
  loading?: boolean;
}

/** A themed button; defaults to `type="button"` so it never submits a form by accident. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, fullWidth, loading, className, type = "button", onClick, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-busy={loading || undefined}
      aria-disabled={loading || undefined}
      onClick={(e) => {
        if (loading) {
          e.preventDefault(); // also stops a submit button from submitting again
          return;
        }
        onClick?.(e);
      }}
      className={buttonVariants({ variant, size, fullWidth, className })}
      {...props}
    />
  );
});

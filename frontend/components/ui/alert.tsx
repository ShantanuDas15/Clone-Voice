import { type VariantProps, cva } from "class-variance-authority";
import type { HTMLAttributes } from "react";

const alertVariants = cva("text-sm", {
  variants: {
    tone: {
      danger: "text-danger",
      success: "text-success",
      neutral: "",
    },
  },
  defaultVariants: { tone: "neutral" },
});

/**
 * An announced message. `danger` is a live `alert` (interrupts); `success`/`neutral` are polite
 * `status` regions. Override with `role` when the urgency differs.
 */
export function Alert({
  tone,
  role,
  className,
  ...props
}: HTMLAttributes<HTMLParagraphElement> & VariantProps<typeof alertVariants>) {
  return (
    <p
      role={role ?? (tone === "danger" ? "alert" : "status")}
      className={alertVariants({ tone, className })}
      {...props}
    />
  );
}

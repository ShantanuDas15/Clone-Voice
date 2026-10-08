import { type VariantProps, cva } from "class-variance-authority";
import type { HTMLAttributes } from "react";

const badgeVariants = cva("inline-block rounded-full px-2 py-0.5 text-xs font-medium", {
  variants: {
    tone: {
      neutral: "bg-muted text-muted-foreground",
      success: "bg-muted text-success",
      notice: "bg-warning text-warning-foreground",
    },
  },
  defaultVariants: { tone: "neutral" },
});

/** A short status label. The text always carries the meaning; colour is only reinforcement. */
export function Badge({
  tone,
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={badgeVariants({ tone, className })} {...props} />;
}

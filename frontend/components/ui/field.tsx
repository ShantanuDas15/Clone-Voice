import {
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  forwardRef,
} from "react";

/** Shared control recipe: `line` outline (3:1), hover, disabled, and a danger outline when invalid. */
const control =
  "mt-1 block w-full rounded border border-line bg-surface px-3 py-2 hover:border-foreground/60 disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-danger";

const join = (className?: string) => (className ? `${control} ${className}` : control);

/** A single-line text control. */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={join(`min-h-11 ${className ?? ""}`.trim())} {...props} />;
  },
);

/** A native select (keeps platform behaviour and screen-reader semantics). */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, ...props }, ref) {
    return <select ref={ref} className={join(`min-h-11 ${className ?? ""}`.trim())} {...props} />;
  },
);

/** A multi-line text control. */
export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={join(className)} {...props} />;
});

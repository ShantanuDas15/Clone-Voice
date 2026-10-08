"use client";

import { type ReactNode, useEffect, useRef } from "react";

import { useDialog } from "@/hooks/use-dialog";

interface DialogProps {
  /** Id of the heading inside `children`; it names the dialog for assistive tech. */
  titleId: string;
  onClose: () => void;
  /** Blocks Escape and scrim clicks, e.g. while a request is in flight. */
  closeDisabled?: boolean;
  children: ReactNode;
}

/**
 * A modal confirmation: a scrim over the page, a centred panel, focus trapped inside, Escape and
 * a scrim click both cancel (unless `closeDisabled`), focus returns to the opener on close, and
 * the page behind does not scroll. Use the `danger` Button variant for the destructive action.
 */
export function Dialog({ titleId, onClose, closeDisabled = false, children }: DialogProps) {
  const ref = useDialog<HTMLDivElement>(onClose, closeDisabled);
  // A press that starts inside the panel (e.g. selecting text) and ends on the scrim is not a
  // dismissal; only a press and release that both land on the scrim are.
  const pressedScrim = useRef(false);

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  return (
    <div
      data-testid="dialog-scrim"
      className="fixed inset-0 z-40 flex items-center justify-center overflow-y-auto bg-foreground/50 p-4"
      onMouseDown={(e) => {
        pressedScrim.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        // On click (after the browser has moved focus) so closing can hand focus back reliably.
        if (pressedScrim.current && e.target === e.currentTarget && !closeDisabled) onClose();
        pressedScrim.current = false;
      }}
    >
      <div
        ref={ref}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-full w-full max-w-md space-y-3 overflow-y-auto rounded-lg border border-line bg-surface p-5"
      >
        {children}
      </div>
    </div>
  );
}

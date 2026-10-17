"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Moves focus to the first field marked `aria-invalid` inside the form after a failed submit, so a
 * keyboard or screen-reader user lands on the problem (react-hook-form forms already do this).
 * Call `focusFirstInvalid()` right after setting the error state; the focus happens once the
 * errors have rendered.
 */
export function useFocusFirstInvalid<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (attempt === 0) return;
    ref.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [attempt]);

  return { ref, focusFirstInvalid: () => setAttempt((a) => a + 1) };
}

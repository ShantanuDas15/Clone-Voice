import autoAnimate from "@formkit/auto-animate";
import { useCallback } from "react";

/** Duration of a row entering, leaving or moving: inside the 120-200 ms band of plan §4.10. */
export const LIST_MOTION_MS = 150;

/**
 * Ref callback for a list: rows the user adds, removes or reorders (a delete, a filter, "Load
 * more") ease in, out and over instead of jumping. The rows present on first render do not
 * animate (no entrance motion on page load), and reduced motion switches it off: AutoAnimate
 * reads `prefers-reduced-motion` itself. Safe where `Element.animate` is missing.
 */
export function useListMotion<T extends HTMLElement = HTMLUListElement>(): (el: T | null) => void {
  return useCallback((el: T | null) => {
    if (el && typeof el.animate === "function") autoAnimate(el, { duration: LIST_MOTION_MS });
  }, []);
}

import { useEffect, useRef, useState } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hidden);
}

/**
 * Make an `aria-modal` container behave like one: focus moves in on open, Tab/Shift+Tab cycle
 * inside it (and pull stray focus back), Escape closes it unless `closeDisabled`, and focus
 * returns to the element that opened it. Attach the returned ref to the dialog element.
 */
export function useDialog<T extends HTMLElement>(onClose: () => void, closeDisabled = false) {
  const ref = useRef<T>(null);
  // Captured during the first render: children's `autoFocus` runs before any effect here.
  const [opener] = useState(() =>
    typeof document === "undefined" ? null : document.activeElement,
  );
  const latest = useRef({ onClose, closeDisabled });
  latest.current = { onClose, closeDisabled };

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    if (!root.contains(document.activeElement)) (focusables(root)[0] ?? root).focus();

    function onKeyDown(event: KeyboardEvent) {
      if (!root) return;
      if (event.key === "Escape") {
        if (!latest.current.closeDisabled) {
          event.preventDefault();
          latest.current.onClose();
        }
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables(root);
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement;
      if (!root.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, [opener]);

  return ref;
}

export type ToastKind = "success" | "error";
type Listener = (kind: ToastKind, message: string) => void;

let listener: Listener | null = null;
const early: Array<[ToastKind, string]> = [];

/** Called by `ToastHost`; replays anything raised before it mounted. */
export function onToast(fn: Listener): () => void {
  listener = fn;
  for (const [kind, message] of early.splice(0)) fn(kind, message);
  return () => {
    if (listener === fn) listener = null;
  };
}

function send(kind: ToastKind, message: string): void {
  if (listener) listener(kind, message);
  else early.push([kind, message]);
}

/**
 * Toast API that does not import `sonner`. The library (about 9 KB gzipped) is fetched by
 * `ToastHost` on the first toast, so the public routes never download it.
 */
export const notify = {
  success: (message: string) => send("success", message),
  error: (message: string) => send("error", message),
};

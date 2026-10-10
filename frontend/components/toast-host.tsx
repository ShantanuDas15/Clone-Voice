"use client";

import { useEffect, useRef, useState } from "react";

import { type ToastKind, onToast } from "@/lib/toast";

type Sonner = typeof import("sonner");

/** Loads `sonner` on the first toast, mounts its region, then shows the queued messages. */
export function ToastHost() {
  const [sonner, setSonner] = useState<Sonner | null>(null);
  const loaded = useRef<Sonner | null>(null);
  const queue = useRef<Array<[ToastKind, string]>>([]);

  useEffect(
    () =>
      onToast((kind, message) => {
        if (loaded.current) {
          loaded.current.toast[kind](message);
          return;
        }
        queue.current.push([kind, message]);
        void import("sonner").then((m) => {
          loaded.current = m;
          setSonner(m);
        });
      }),
    [],
  );

  // The region mounts in this render; its effects run before this one, so it is listening.
  useEffect(() => {
    if (!sonner) return;
    for (const [kind, message] of queue.current.splice(0)) sonner.toast[kind](message);
  }, [sonner]);

  return sonner ? <sonner.Toaster richColors closeButton /> : null;
}

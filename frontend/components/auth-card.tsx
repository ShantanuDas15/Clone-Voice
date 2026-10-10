import type { ReactNode } from "react";

/** The one frame for every account-entry page: a bordered panel with a title and a short lead. */
export function AuthCard({
  title,
  lead,
  children,
}: {
  title: string;
  lead?: string;
  children: ReactNode;
}) {
  return (
    <section className="mx-auto mt-2 max-w-md rounded-lg border border-border bg-surface p-6 sm:mt-8 sm:p-8">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {lead ? <p className="mt-2 text-sm text-muted-foreground">{lead}</p> : null}
      <div className="mt-6">{children}</div>
    </section>
  );
}

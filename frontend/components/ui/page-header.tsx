import type { ReactNode } from "react";

/** Title block for a signed-in page: one `h1`, an optional lead line, an optional side action. */
export function PageHeader({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {children ? <p className="mt-1 text-muted-foreground">{children}</p> : null}
      </div>
      {action}
    </header>
  );
}

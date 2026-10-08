/** A labelled rule between two ways of doing the same thing (Google vs email). */
export function OrDivider({ children }: { children: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground">
      <hr aria-hidden className="flex-1 border-border" />
      <span>{children}</span>
      <hr aria-hidden className="flex-1 border-border" />
    </div>
  );
}

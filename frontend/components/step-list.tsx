import type { ReactNode } from "react";

import type { StepStatus } from "@/lib/first-run";

export interface Step {
  id: string;
  title: string;
  status: StepStatus;
  /** Extra content shown under the title (a hint or an action). */
  detail?: ReactNode;
}

const LABEL: Record<StepStatus, string> = { done: "Done", current: "Next", todo: "To do" };

/** A real sequence, so it is numbered (UX plan §4.9). The next step carries `aria-current`. */
export function StepList({ steps, label }: { steps: Step[]; label: string }) {
  return (
    <ol aria-label={label} className="space-y-3">
      {steps.map((s, i) => (
        <li
          key={s.id}
          aria-current={s.status === "current" ? "step" : undefined}
          className={s.status === "todo" ? "text-muted-foreground" : ""}
        >
          <p className="font-medium">
            <span className="font-mono tabular-nums">{i + 1}.</span> {s.title}{" "}
            <span className="text-sm font-normal text-muted-foreground">({LABEL[s.status]})</span>
          </p>
          {s.detail && s.status !== "done" && <div className="mt-1 text-sm">{s.detail}</div>}
        </li>
      ))}
    </ol>
  );
}

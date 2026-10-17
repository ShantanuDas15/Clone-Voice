"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

/** Long text cut to `limit` characters with a Show more / Show less toggle; short text as is. */
export function ExpandableText({
  text,
  limit,
  className = "",
}: {
  text: string;
  limit: number;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > limit;
  const shown = expanded || !long ? text : `${text.slice(0, limit)}…`;
  return (
    <>
      <p className={`whitespace-pre-wrap break-words ${className}`.trim()}>{shown}</p>
      {long && (
        <Button
          variant="quiet"
          size="sm"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? "Show less" : "Show more"}
        </Button>
      )}
    </>
  );
}

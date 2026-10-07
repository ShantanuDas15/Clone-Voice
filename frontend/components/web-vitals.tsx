"use client";

import { useReportWebVitals } from "next/web-vitals";
import { useEffect } from "react";

import { initReporting, reportVital } from "@/lib/observability/report";

/**
 * Starts error reporting (so uncaught errors are captured) and forwards Core Web Vitals.
 * Rendered only when a DSN is configured, and loaded lazily (see `components/providers.tsx`).
 */
export function WebVitals() {
  useEffect(() => {
    void initReporting();
  }, []);
  useReportWebVitals((metric) => {
    void reportVital({ name: metric.name, value: metric.value, rating: metric.rating });
  });
  return null;
}

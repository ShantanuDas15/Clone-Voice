import type { Page } from "@playwright/test";

// The unfixed header shifted 0.17-0.35; 0.05 leaves room for incidental sub-pixel shifts.
/** Sum of layout shifts (no recent input) over a page load, Chromium only. Call before `goto`. */
export async function observeShifts(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as { __cls: number; __clsWhat: string[] };
    w.__cls = 0;
    w.__clsWhat = [];
    new PerformanceObserver((list) => {
      type Shift = {
        value: number;
        hadRecentInput: boolean;
        startTime: number;
        sources?: { node?: Node; previousRect: DOMRect; currentRect: DOMRect }[];
      };
      for (const e of list.getEntries() as unknown as Shift[]) {
        if (e.hadRecentInput) continue;
        w.__cls += e.value;
        const moved = (e.sources ?? []).map(
          (s) =>
            `${s.node?.nodeName ?? "?"} y ${Math.round(s.previousRect.y)}->${Math.round(s.currentRect.y)}`,
        );
        w.__clsWhat.push(
          `${e.value.toFixed(3)} at ${Math.round(e.startTime)} ms: ${moved.join(", ")}`,
        );
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
}

/** The shift total collected since `observeShifts`. */
export const cls = (page: Page) =>
  page.evaluate(() => (window as unknown as { __cls: number }).__cls);

/** What moved, for the failure message of an assertion on `cls`. */
export const clsWhat = (page: Page) =>
  page.evaluate(() => (window as unknown as { __clsWhat: string[] }).__clsWhat.join("\n"));

// 320 is the smallest supported width, 360 the most common Android phone, 412 a large one.
export const CLS_WIDTHS = [320, 360, 412];

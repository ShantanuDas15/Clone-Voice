import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { autoAnimate } = vi.hoisted(() => ({ autoAnimate: vi.fn() }));
vi.mock("@formkit/auto-animate", () => ({ default: autoAnimate }));

import { LIST_MOTION_MS, useListMotion } from "@/hooks/use-list-motion";

function List() {
  const ref = useListMotion();
  return (
    <ul ref={ref}>
      <li>row</li>
    </ul>
  );
}

describe("useListMotion", () => {
  const original = HTMLElement.prototype.animate;
  afterEach(() => {
    autoAnimate.mockClear();
    HTMLElement.prototype.animate = original;
  });

  it("animates the list at a duration inside the 120-200 ms motion band", () => {
    HTMLElement.prototype.animate = vi.fn();
    const { container } = render(<List />);
    expect(autoAnimate).toHaveBeenCalledTimes(1);
    expect(autoAnimate).toHaveBeenCalledWith(container.querySelector("ul"), {
      duration: LIST_MOTION_MS,
    });
    expect(LIST_MOTION_MS).toBeGreaterThanOrEqual(120);
    expect(LIST_MOTION_MS).toBeLessThanOrEqual(200);
  });

  it("does nothing where the Web Animations API is missing", () => {
    // @ts-expect-error simulate an environment without Element.animate
    HTMLElement.prototype.animate = undefined;
    render(<List />);
    expect(autoAnimate).not.toHaveBeenCalled();
  });
});

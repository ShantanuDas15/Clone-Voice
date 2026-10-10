import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RouteFocus } from "@/components/route-focus";

let path = "/generate";
vi.mock("next/navigation", () => ({ usePathname: () => path }));

function page(heading = "Voices") {
  return (
    <>
      <RouteFocus />
      <main>
        <h1>{heading}</h1>
        <button>Action</button>
      </main>
    </>
  );
}

beforeEach(() => {
  path = "/generate";
  document.body.innerHTML = "";
  (document.activeElement as HTMLElement | null)?.blur();
});

describe("RouteFocus", () => {
  it("does nothing on the first render", () => {
    render(page());
    expect(document.activeElement).toBe(document.body);
  });

  it("focuses the heading when the path changes, without making it a tab stop", () => {
    const { rerender } = render(page());
    path = "/voices";
    rerender(page());
    const h1 = document.querySelector("h1");
    expect(h1).toHaveFocus();
    expect(h1).toHaveAttribute("tabindex", "-1");
  });

  it("does not move focus when the path is unchanged", () => {
    const { rerender } = render(page());
    rerender(page("Other"));
    expect(document.activeElement).toBe(document.body);
  });

  it("leaves focus alone when the new page already placed it", () => {
    const { rerender, getByRole } = render(page());
    getByRole("button").focus();
    path = "/voices";
    rerender(page());
    expect(getByRole("button")).toHaveFocus();
  });

  it("moves focus from the header link that was just followed", () => {
    const { rerender, getByRole } = render(
      <>
        <header>
          <a href="/voices">Voices</a>
        </header>
        {page()}
      </>,
    );
    getByRole("link").focus();
    path = "/voices";
    rerender(
      <>
        <header>
          <a href="/voices">Voices</a>
        </header>
        {page()}
      </>,
    );
    expect(document.querySelector("h1")).toHaveFocus();
  });

  it("does not steal focus from an open modal", () => {
    const { rerender } = render(
      <>
        {page()}
        <div aria-modal="true" role="dialog" />
      </>,
    );
    path = "/voices";
    rerender(
      <>
        {page()}
        <div aria-modal="true" role="dialog" />
      </>,
    );
    expect(document.activeElement).toBe(document.body);
  });

  it("does nothing when the page has no heading", () => {
    const { rerender } = render(<RouteFocus />);
    path = "/voices";
    rerender(<RouteFocus />);
    expect(document.activeElement).toBe(document.body);
  });
});

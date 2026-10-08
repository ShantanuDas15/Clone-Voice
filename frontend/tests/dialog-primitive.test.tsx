import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

function Harness({ closeDisabled = false, onClose = vi.fn() }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <Button onClick={() => setOpen(true)}>open</Button>
      {open && (
        <Dialog
          titleId="t"
          closeDisabled={closeDisabled}
          onClose={() => {
            onClose();
            setOpen(false);
          }}
        >
          <h3 id="t">Delete it?</h3>
          <Button variant="danger">Delete</Button>
          <Button variant="secondary">Cancel</Button>
        </Dialog>
      )}
    </div>
  );
}

describe("Dialog", () => {
  it("is a named modal over a scrim, and locks page scroll while open", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "open" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete it?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByTestId("dialog-scrim")).toContainElement(dialog);
    expect(screen.getByTestId("dialog-scrim").className).toContain("animate-fade-in");
    expect(document.body.style.overflow).toBe("hidden");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(document.body.style.overflow).not.toBe("hidden");
  });

  it("closes on a scrim click but not on a click inside the panel", async () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "open" }));
    await userEvent.click(screen.getByRole("alertdialog"));
    expect(onClose).not.toHaveBeenCalled();
    // A press that starts in the panel and is released on the scrim (text selection) is not a dismissal.
    fireEvent.mouseDown(screen.getByRole("alertdialog"));
    fireEvent.click(screen.getByTestId("dialog-scrim"));
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId("dialog-scrim"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape and scrim clicks while closing is disabled (a request is in flight)", async () => {
    const onClose = vi.fn();
    render(<Harness closeDisabled onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "open" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByTestId("dialog-scrim"));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("returns focus to the opener when it closes", async () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "open" });
    await userEvent.click(opener);
    await userEvent.keyboard("{Escape}");
    expect(opener).toHaveFocus();
    await userEvent.click(opener);
    await userEvent.click(screen.getByTestId("dialog-scrim"));
    expect(opener).toHaveFocus();
  });
});

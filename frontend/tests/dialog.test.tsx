import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import { type ReactNode, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountSection } from "@/components/account-section";
import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { VoiceProfileList } from "@/components/voice-profile-list";
import { useDialog } from "@/hooks/use-dialog";
import { __resetSessionForTests } from "@/lib/auth/session";
import { server } from "@/mocks/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/profile",
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const API = "http://api.test/api/v1";

function wrap(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  __resetSessionForTests();
  __resetBootstrapForTests();
});

function Harness({ closeDisabled = false, empty = false }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(true)}>open</button>
      <button>outside</button>
      {open && <Panel onClose={() => setOpen(false)} closeDisabled={closeDisabled} empty={empty} />}
    </div>
  );
}
function Panel({
  onClose,
  closeDisabled,
  empty,
}: {
  onClose: () => void;
  closeDisabled: boolean;
  empty: boolean;
}) {
  const ref = useDialog<HTMLDivElement>(onClose, closeDisabled);
  return (
    <div ref={ref} role="dialog" aria-label="panel" tabIndex={-1}>
      {!empty && (
        <>
          <button>first</button>
          <button disabled>disabled</button>
          <button>last</button>
        </>
      )}
    </div>
  );
}

describe("useDialog", () => {
  it("moves focus in, cycles Tab and Shift+Tab, and skips disabled controls", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByText("open"));
    expect(screen.getByText("first")).toHaveFocus();
    await user.tab();
    expect(screen.getByText("last")).toHaveFocus();
    await user.tab();
    expect(screen.getByText("first")).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByText("last")).toHaveFocus();
  });

  it("pulls focus back inside when it has strayed outside", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByText("open"));
    screen.getByText("outside").focus();
    await user.tab();
    expect(screen.getByText("first")).toHaveFocus();
  });

  it("closes on Escape and returns focus to the opener", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByText("open"));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("open")).toHaveFocus();
  });

  it("ignores Escape while closing is disabled", async () => {
    const user = userEvent.setup();
    render(<Harness closeDisabled />);
    await user.click(screen.getByText("open"));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("focuses the container and keeps Tab inside when nothing is focusable", async () => {
    const user = userEvent.setup();
    render(<Harness empty />);
    await user.click(screen.getByText("open"));
    expect(screen.getByRole("dialog")).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("dialog")).toHaveFocus();
  });
});

describe("delete-voice dialog", () => {
  it("focuses the confirm button, traps Tab, and Escape cancels back to the row's Delete button", async () => {
    const user = userEvent.setup();
    wrap(<VoiceProfileList />);
    const trigger = await screen.findByRole("button", { name: /^Delete My voice$/ });
    await user.click(trigger);
    expect(screen.getByRole("button", { name: "Delete voice" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Delete voice" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(trigger).toHaveFocus();
  });
});

describe("delete-account dialog", () => {
  async function open(user: ReturnType<typeof userEvent.setup>) {
    await screen.findByLabelText("Display name");
    const trigger = screen.getByRole("button", { name: /delete my account/i });
    await user.click(trigger);
    return trigger;
  }

  it("keeps the trigger mounted, focuses the first field, and restores focus on Escape", async () => {
    const user = userEvent.setup();
    wrap(<AccountSection />);
    const trigger = await open(user);
    expect(screen.getByLabelText(/type delete/i)).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("does not let Tab leave the dialog", async () => {
    const user = userEvent.setup();
    wrap(<AccountSection />);
    await open(user);
    const dialog = screen.getByRole("alertdialog");
    for (let i = 0; i < 8; i += 1) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
  });

  it("ignores Escape while the deletion request is in flight", async () => {
    const user = userEvent.setup();
    server.use(
      mswHttp.delete(`${API}/auth/me`, async () => {
        await new Promise((r) => setTimeout(r, 200));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    wrap(<AccountSection />);
    await open(user);
    await user.type(screen.getByLabelText(/type delete/i), "DELETE");
    await user.type(screen.getByLabelText("Password"), "hunter2hunter2");
    await user.click(screen.getByRole("button", { name: "Delete account" }));
    await screen.findByRole("button", { name: "Deleting…" });
    await user.keyboard("{Escape}");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });
});

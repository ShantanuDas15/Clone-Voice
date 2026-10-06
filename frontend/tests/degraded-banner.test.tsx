import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { DegradedBanner } from "@/components/degraded-banner";
import { server } from "@/mocks/server";

function renderBanner() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DegradedBanner />
    </QueryClientProvider>,
  );
}

describe("DegradedBanner (F23 / R17)", () => {
  it("shows when /health/ready returns 503", async () => {
    server.use(
      http.get("http://api.test/health/ready", () =>
        HttpResponse.json({ status: "degraded" }, { status: 503 }),
      ),
    );
    renderBanner();
    expect(await screen.findByRole("status")).toHaveTextContent(/experiencing problems/i);
  });

  it("stays hidden when healthy", async () => {
    const { container } = renderBanner();
    await new Promise((r) => setTimeout(r, 50));
    expect(container).toBeEmptyDOMElement();
  });

  it("stays hidden when the probe itself fails (unknown)", async () => {
    server.use(http.get("http://api.test/health/ready", () => HttpResponse.error()));
    const { container } = renderBanner();
    await new Promise((r) => setTimeout(r, 50));
    expect(container).toBeEmptyDOMElement();
  });
});

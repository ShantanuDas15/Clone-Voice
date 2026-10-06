import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { server } from "@/mocks/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
});
afterAll(() => server.close());

// jsdom has no object-URL support; stub it so media code can be exercised and revocation asserted.
let objectUrlCounter = 0;
URL.createObjectURL = vi.fn(() => `blob:mock-${++objectUrlCounter}`);
URL.revokeObjectURL = vi.fn();

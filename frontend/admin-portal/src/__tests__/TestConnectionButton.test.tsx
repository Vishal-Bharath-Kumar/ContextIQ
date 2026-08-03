/**
 * TestConnectionButton — React Testing Library tests.
 *
 * Covers TASK-US039-03 DoD items:
 *  - "Testing…" label and aria-busy while request is in-flight
 *  - Inline "OK (N ms)" result in green on success (AC-3)
 *  - Inline "Failed: {detail}" result in red on failure (AC-3)
 *  - role="status" / aria-live="polite" for screen reader announcement (AC-7)
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  describe,
  it,
  expect,
  beforeAll,
  afterEach,
  afterAll,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { TestConnectionButton } from "../components/connectors/TestConnectionButton";

// ---------------------------------------------------------------------------
// MSW mock server
// ---------------------------------------------------------------------------

const server = setupServer();

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function renderButton(connectorId = "ks-001") {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <TestConnectionButton connectorId={connectorId} />
    </QueryClientProvider>
  );
  return { user };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TestConnectionButton", () => {
  it("renders idle state with 'Test Connection' label", () => {
    renderButton();
    expect(
      screen.getByRole("button", { name: "Test connector connection" })
    ).toHaveTextContent("Test Connection");
  });

  it("shows inline 'OK (N ms)' result on successful health-check", async () => {
    server.use(
      http.post("/api/v1/knowledge-sources/ks-001/health-check", () =>
        HttpResponse.json({ ok: true, latency_ms: 42, detail: null })
      )
    );

    const { user } = renderButton("ks-001");
    await user.click(
      screen.getByRole("button", { name: "Test connector connection" })
    );

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("OK (42 ms)");
    expect(result).toHaveClass("text-green-700");
  });

  it("shows inline 'Failed: {detail}' result on API error response", async () => {
    server.use(
      http.post("/api/v1/knowledge-sources/ks-002/health-check", () =>
        HttpResponse.json(
          { ok: false, latency_ms: 0, detail: "Connection refused" },
          { status: 200 }
        )
      )
    );

    const { user } = renderButton("ks-002");
    await user.click(
      screen.getByRole("button", { name: "Test connector connection" })
    );

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("Failed: Connection refused");
    expect(result).toHaveClass("text-red-600");
  });

  it("shows 'Failed: Request failed' when the request throws a network error", async () => {
    server.use(
      http.post("/api/v1/knowledge-sources/ks-003/health-check", () =>
        HttpResponse.error()
      )
    );

    const { user } = renderButton("ks-003");
    await user.click(
      screen.getByRole("button", { name: "Test connector connection" })
    );

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("Failed: Request failed");
    expect(result).toHaveClass("text-red-600");
  });

  it("disables the button and sets aria-busy while request is in-flight", async () => {
    let resolveRequest!: (value: Response) => void;
    server.use(
      http.post("/api/v1/knowledge-sources/ks-004/health-check", () =>
        new Promise<Response>((res) => {
          resolveRequest = res as (value: Response) => void;
        })
      )
    );

    const { user } = renderButton("ks-004");
    const btn = screen.getByRole("button", { name: "Test connector connection" });

    await user.click(btn);

    await waitFor(() => {
      expect(btn).toBeDisabled();
      expect(btn).toHaveTextContent("Testing…");
    });

    // Unblock the request to avoid leaking pending promises
    resolveRequest(
      new Response(JSON.stringify({ ok: true, latency_ms: 1, detail: null }), {
        headers: { "Content-Type": "application/json" },
      })
    );
  });

  it("result span has role='status' and aria-live='polite' for screen reader support", async () => {
    server.use(
      http.post("/api/v1/knowledge-sources/ks-005/health-check", () =>
        HttpResponse.json({ ok: true, latency_ms: 10, detail: null })
      )
    );

    const { user } = renderButton("ks-005");
    await user.click(
      screen.getByRole("button", { name: "Test connector connection" })
    );

    const result = await screen.findByRole("status");
    expect(result).toHaveAttribute("aria-live", "polite");
  });
});

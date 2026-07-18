/**
 * ActivatePolicyDialog — focused AC-4 tests.
 *
 * TASK-US040-05: Verifies dialog lifecycle:
 *  - Dialog opens showing policy name on trigger click.
 *  - Confirm fires POST /activate and closes the dialog on success.
 *  - Cancel does not call POST /activate.
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
  vi,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { ActivatePolicyDialog } from "../components/policies/ActivatePolicyDialog";

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const activateHandler = vi.fn();

const server = setupServer(
  http.post("/api/v1/policies/:id/activate", ({ params }) => {
    activateHandler(params.id);
    return HttpResponse.json({ status: "active" });
  })
);

beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  activateHandler.mockReset();
});
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQC() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function renderDialog(policyId: string, policyName: string) {
  const qc = makeQC();
  return render(
    <QueryClientProvider client={qc}>
      <ActivatePolicyDialog policyId={policyId} policyName={policyName} />
    </QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Tests — AC-4
// ---------------------------------------------------------------------------

describe("ActivatePolicyDialog — AC-4", () => {
  it("shows confirmation dialog with policy name on Activate trigger click", async () => {
    const user = userEvent.setup();
    renderDialog("p1", "PII Filter");

    await user.click(
      screen.getByRole("button", { name: /activate policy PII Filter/i })
    );

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText(/PII Filter/)).toBeInTheDocument();
  });

  it("calls POST /activate and closes dialog on confirm", async () => {
    const user = userEvent.setup();
    renderDialog("p1", "PII Filter");

    await user.click(
      screen.getByRole("button", { name: /activate policy PII Filter/i })
    );

    // Click the Activate action button inside the dialog
    const buttons = screen.getAllByRole("button", { name: /^activate$/i });
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() =>
      expect(activateHandler).toHaveBeenCalledWith("p1")
    );
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    );
  });

  it("does not call POST when Cancel is clicked", async () => {
    const user = userEvent.setup();
    renderDialog("p1", "PII Filter");

    await user.click(
      screen.getByRole("button", { name: /activate policy PII Filter/i })
    );
    await user.click(await screen.findByRole("button", { name: /cancel/i }));

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    );
    expect(activateHandler).not.toHaveBeenCalled();
  });
});

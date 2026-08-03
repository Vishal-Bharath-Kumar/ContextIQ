/**
 * ActivatePolicyDialog — React Testing Library tests.
 *
 * TASK-US040-03 DoD:
 *  - Dialog opens/closes correctly.
 *  - Activate mutation fires on confirm; dialog closes on success.
 *  - Cancel closes dialog without calling any API.
 *  - Buttons are disabled and "Activating…" shown while mutation is pending.
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

// Radix UI Select uses pointer-capture and scroll APIs not available in jsdom.
beforeAll(() => {
  window.HTMLElement.prototype.hasPointerCapture = () => true;
  window.HTMLElement.prototype.setPointerCapture = () => {};
  window.HTMLElement.prototype.releasePointerCapture = () => {};
  window.HTMLElement.prototype.scrollIntoView = () => {};
});

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
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWithQC(ui: React.ReactElement) {
  const qc = makeQC();
  return render(
    <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// ActivatePolicyDialog tests
// ---------------------------------------------------------------------------

describe("ActivatePolicyDialog", () => {
  it("renders the Activate trigger button", () => {
    renderWithQC(
      <ActivatePolicyDialog policyId="policy-uuid-1" policyName="data-access-control" />
    );
    expect(screen.getByRole("button", { name: /activate policy data-access-control/i })).toBeInTheDocument();
  });

  it("opens the dialog when the trigger is clicked", async () => {
    const user = userEvent.setup();
    renderWithQC(
      <ActivatePolicyDialog policyId="policy-uuid-1" policyName="data-access-control" />
    );
    await user.click(screen.getByRole("button", { name: /activate policy data-access-control/i }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText(/data-access-control/i)).toBeInTheDocument();
    expect(screen.getByText(/audit trail/i)).toBeInTheDocument();
  });

  it("closes without calling the API when Cancel is clicked", async () => {
    const user = userEvent.setup();
    renderWithQC(
      <ActivatePolicyDialog policyId="policy-uuid-1" policyName="data-access-control" />
    );
    await user.click(screen.getByRole("button", { name: /activate policy data-access-control/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    );
    expect(activateHandler).not.toHaveBeenCalled();
  });

  it("fires POST /activate and closes dialog on confirm", async () => {
    const user = userEvent.setup();
    renderWithQC(
      <ActivatePolicyDialog policyId="policy-uuid-1" policyName="data-access-control" />
    );
    await user.click(screen.getByRole("button", { name: /activate policy data-access-control/i }));
    // Click the Activate button inside the dialog (not the trigger)
    const activateButtons = screen.getAllByRole("button", { name: /^activate$/i });
    const confirmBtn = activateButtons[activateButtons.length - 1];
    await user.click(confirmBtn);
    await waitFor(() => expect(activateHandler).toHaveBeenCalledWith("policy-uuid-1"));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    );
  });
});

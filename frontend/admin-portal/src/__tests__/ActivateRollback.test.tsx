/**
 * ActivatePolicyDialog & RollbackDropdown — React Testing Library tests.
 *
 * TASK-US040-03 DoD:
 *  - Dialog opens/closes correctly.
 *  - Activate mutation fires on confirm; dialog closes on success.
 *  - Cancel closes dialog without calling any API.
 *  - Buttons are disabled and "Activating…" shown while mutation is pending.
 *  - RollbackDropdown not rendered when no non-active versions exist.
 *  - Selecting a version fires the rollback mutation.
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
import { RollbackDropdown } from "../components/policies/RollbackDropdown";
import type { PolicyListItem } from "../services/policyService";

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
const rollbackHandler = vi.fn();

const server = setupServer(
  http.post("/api/v1/policies/:id/activate", ({ params }) => {
    activateHandler(params.id);
    return HttpResponse.json({ status: "active" });
  }),
  http.post("/api/v1/policies/:id/rollback", ({ params, request }) => {
    const url = new URL(request.url);
    rollbackHandler(params.id, url.searchParams.get("version"));
    return HttpResponse.json({ status: "rolled_back" });
  })
);

beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  activateHandler.mockReset();
  rollbackHandler.mockReset();
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

const POLICY_WITH_VERSIONS: PolicyListItem = {
  id: "policy-uuid-1",
  name: "data-access-control",
  active_version: "1.1.0",
  versions: [
    {
      id: "ver-uuid-2",
      policy_group: "data-access-control",
      version: "1.1.0",
      status: "active",
      author: "alice@example.com",
      description: "Production version",
      activated_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
    },
    {
      id: "ver-uuid-1",
      policy_group: "data-access-control",
      version: "1.0.0",
      status: "superseded",
      author: "bob@example.com",
      description: "Initial version",
      activated_at: null,
      created_at: new Date().toISOString(),
    },
  ],
  latest_author: "alice@example.com",
  activated_at: new Date().toISOString(),
};

const POLICY_ONLY_ACTIVE: PolicyListItem = {
  ...POLICY_WITH_VERSIONS,
  versions: [POLICY_WITH_VERSIONS.versions[0]],
};

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

// ---------------------------------------------------------------------------
// RollbackDropdown tests
// ---------------------------------------------------------------------------

describe("RollbackDropdown", () => {
  it("renders null when no non-active versions exist", () => {
    const { container } = renderWithQC(
      <RollbackDropdown policy={POLICY_ONLY_ACTIVE} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a trigger when non-active versions exist", () => {
    renderWithQC(<RollbackDropdown policy={POLICY_WITH_VERSIONS} />);
    expect(
      screen.getByRole("combobox", { name: /rollback to a previous policy version/i })
    ).toBeInTheDocument();
  });

  it("fires POST /rollback with the selected version", async () => {
    const user = userEvent.setup();
    renderWithQC(<RollbackDropdown policy={POLICY_WITH_VERSIONS} />);
    // Open the dropdown
    await user.click(
      screen.getByRole("combobox", { name: /rollback to a previous policy version/i })
    );
    // Select version 1.0.0
    await user.click(await screen.findByText(/v1\.0\.0/i));
    await waitFor(() =>
      expect(rollbackHandler).toHaveBeenCalledWith("policy-uuid-1", "1.0.0")
    );
  });
});

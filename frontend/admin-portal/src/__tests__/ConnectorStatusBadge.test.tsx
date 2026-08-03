/**
 * ConnectorStatusBadge — React Testing Library snapshot tests.
 *
 * AC-1 / DoD: Verifies that all 4 status variants render with the correct
 * label text and aria-label for screen readers (WCAG 2.1 AA, AC-7).
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { ConnectorStatusBadge } from "../components/connectors/ConnectorStatusBadge";

describe("ConnectorStatusBadge", () => {
  it("renders 'Active' badge with correct aria-label", () => {
    const { container } = render(<ConnectorStatusBadge status="active" />);
    const badge = screen.getByRole("generic", {
      name: "Connector status: Active",
    });
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Active");
    expect(container.firstChild).toMatchSnapshot();
  });

  it("renders 'Inactive' badge with correct aria-label", () => {
    const { container } = render(<ConnectorStatusBadge status="inactive" />);
    const badge = screen.getByRole("generic", {
      name: "Connector status: Inactive",
    });
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Inactive");
    expect(container.firstChild).toMatchSnapshot();
  });

  it("renders 'Syncing' badge with correct aria-label", () => {
    const { container } = render(<ConnectorStatusBadge status="syncing" />);
    const badge = screen.getByRole("generic", {
      name: "Connector status: Syncing",
    });
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Syncing");
    expect(container.firstChild).toMatchSnapshot();
  });

  it("renders 'Error' badge with correct aria-label", () => {
    const { container } = render(<ConnectorStatusBadge status="error" />);
    const badge = screen.getByRole("generic", {
      name: "Connector status: Error",
    });
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Error");
    expect(container.firstChild).toMatchSnapshot();
  });
});

import type { AdminPortalTestArgs } from "../fixtures/adminPortal";
import { test, expect } from "../fixtures/adminPortal";
import { GovernancePage } from "../pages/governance.page";

test("switches governance tabs and verifies the visible content", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
  await loginAsAdmin();
  const governance = new GovernancePage(page);
  await governance.goto();
  await governance.expectLoaded();

  await governance.openComplianceTab();
  await expect(page.getByRole("heading", { name: "Compliance Standards" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save Changes" })).toBeVisible();

  await governance.openRbacTab();
  await expect(page.getByText("Role-Based Access Control (RBAC)")).toBeVisible();

  await governance.openPatternTab();
  await expect(page.getByPlaceholder("Search patterns...")).toBeVisible();

  await governance.openRiskTab();
  await expect(page.getByText("Example Risk Score Calculation")).toBeVisible();
});
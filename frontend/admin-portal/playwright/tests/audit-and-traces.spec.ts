import type { AdminPortalTestArgs } from "../fixtures/adminPortal";
import { test, expect } from "../fixtures/adminPortal";
import { AuditLogPage } from "../pages/audit-log.page";
import { TracesPage } from "../pages/traces.page";

test.describe("admin portal audit and traces", () => {
  test("filters the audit log by action", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const auditLog = new AuditLogPage(page);
    await auditLog.goto();
    await auditLog.expectLoaded();
    await auditLog.filterByAction("model.registered");

    const firstResultRow = page.getByRole("table", { name: "Audit log entries" }).locator("tbody tr").first();
    await expect(firstResultRow).toContainText("model.registered", { timeout: 15_000 });
  });

  test("shows the replay explorer filters and the current traces state", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const traces = new TracesPage(page);
    await traces.goto();
    await traces.expectLoaded();

    const status = page.getByRole("status");
    const traceRows = page.getByRole("table", { name: "Execution trace results" }).locator("tbody tr");

    if ((await traceRows.count()) > 0) {
      await expect(traceRows.first()).toBeVisible();
      return;
    }

    await expect(status).toBeVisible({ timeout: 15_000 });
    await expect(status).toContainText(/Loading traces|No execution traces found\./i);
  });
});
import type { AdminPortalTestArgs } from "../fixtures/adminPortal";
import { test, expect } from "../fixtures/adminPortal";
import { GovernancePage } from "../pages/governance.page";
import { ModelsPage } from "../pages/models.page";
import { PoliciesPage } from "../pages/policies.page";
import { ToolsPage } from "../pages/tools.page";
import { TracesPage } from "../pages/traces.page";

function uniqueId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
}

const VALID_POLICY_REGO = `package contextiq.example

import rego.v1

default allow := false

allow if {
  input.user.role == "admin"
}
`;

test.describe("admin portal workflow actions", () => {
  test("creates, updates, and toggles a tool", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();

    const toolName = uniqueId("playwright_tool");
    const initialDescription = `Initial description ${toolName}`;
    const updatedDescription = `Updated description ${toolName}`;
    const updatedVersion = "2.0.0";
    const tools = new ToolsPage(page);

    await tools.goto();
    await tools.expectListLoaded();
    await tools.openRegisterTool();
    await tools.expectRegisterForm();

    await page.getByLabel("Tool Name").fill(toolName);
    await page.getByLabel("Description").fill(initialDescription);
    await page.getByLabel("Version").fill("1.0.0");
    await page.getByLabel("Input Schema (JSON)").fill('{"type":"object","properties":{"query":{"type":"string"}}}');
    await page.getByRole("button", { name: "Register Tool" }).click();

    await expect(page.getByRole("heading", { name: "Tool Registry" })).toBeVisible({ timeout: 15_000 });
    const toolRow = page.locator("tbody tr").filter({ hasText: toolName }).first();
    await expect(toolRow).toBeVisible({ timeout: 15_000 });
    await expect(toolRow).toContainText(initialDescription);

    await page.getByRole("link", { name: `Edit ${toolName}` }).click();
    await expect(page.getByRole("heading", { name: new RegExp(`Edit Tool: ${toolName}`) })).toBeVisible({ timeout: 15_000 });

    await page.getByLabel("Description").fill(updatedDescription);
    await page.getByLabel("Version").fill(updatedVersion);
    await page.getByRole("button", { name: "Save Changes" }).click();

    await expect(page.getByRole("heading", { name: "Tool Registry" })).toBeVisible({ timeout: 15_000 });
    await expect(toolRow).toContainText(updatedDescription, { timeout: 15_000 });
    await expect(toolRow).toContainText(updatedVersion, { timeout: 15_000 });

    const deactivateSwitch = page.getByLabel(`Deactivate ${toolName}`);
    const activateSwitch = page.getByLabel(`Activate ${toolName}`);
    const startedActive = (await deactivateSwitch.count()) > 0;
    const switchToClick = startedActive ? deactivateSwitch : activateSwitch;
    const expectedAfterToggle = startedActive ? activateSwitch : deactivateSwitch;

    await switchToClick.click();
    await expect(expectedAfterToggle).toBeVisible({ timeout: 15_000 });

    await expectedAfterToggle.click();
    await expect(switchToClick).toBeVisible({ timeout: 15_000 });
  });

  test("creates a model and toggles its active state", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();

    const modelId = `playwright/${uniqueId("model")}`;
    const models = new ModelsPage(page);

    await models.goto();
    await models.expectListLoaded();
    await models.openRegisterModel();
    await models.expectRegisterForm();

    await page.getByLabel("Model ID").fill(modelId);
    await page.getByLabel("Provider").fill("playwright");
    await page.getByLabel("Context window").fill("4096");
    await page.getByLabel("Cost per 1k tokens").fill("0.001");
    await page.getByLabel("chat").check();
    await page.getByRole("button", { name: "Register Model" }).click();

    await expect(page.getByRole("heading", { name: "Models" })).toBeVisible({ timeout: 15_000 });
    const modelRow = page.locator("tbody tr").filter({ hasText: modelId }).first();
    await expect(modelRow).toBeVisible({ timeout: 15_000 });

    const deactivateSwitch = page.getByLabel(`Deactivate ${modelId}`);
    const activateSwitch = page.getByLabel(`Activate ${modelId}`);
    await deactivateSwitch.click();
    await expect(activateSwitch).toBeVisible({ timeout: 15_000 });

    await activateSwitch.click();
    await expect(deactivateSwitch).toBeVisible({ timeout: 15_000 });
  });

  test("creates a policy and can activate then deactivate it", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();

    const policyName = uniqueId("playwright-policy");
    const policies = new PoliciesPage(page);

    await policies.goto();
    await policies.expectListLoaded();
    await policies.openNewPolicy();
    await policies.expectNewPolicyForm();

    await page.getByLabel("Name").fill(policyName);
    await page.getByLabel("Description").fill(`Policy description for ${policyName}`);
    await page.getByRole("textbox", { name: "Rego policy editor" }).fill(VALID_POLICY_REGO);
    await page.getByRole("button", { name: "Save Draft" }).click();

    await expect
      .poll(() => new URL(page.url()).pathname, { timeout: 15_000 })
      .not.toBe("/policies/new");

    await page.goto("/policies");
    await expect(page.getByRole("heading", { name: "Policies" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(policyName)).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: `Activate policy ${policyName}` }).click();
    await page.getByRole("button", { name: "Activate" }).click();
    await page.goto("/policies");
    await expect(page.getByRole("heading", { name: "Policies" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: `Deactivate policy ${policyName}` })).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: `Deactivate policy ${policyName}` }).click();
    await page.getByRole("button", { name: "Deactivate" }).click();
    await page.goto("/policies");
    await expect(page.getByRole("heading", { name: "Policies" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: `Activate policy ${policyName}` })).toBeVisible({ timeout: 15_000 });
  });

  test("saves governance compliance changes and restores the original value", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();

    const governance = new GovernancePage(page);
    await governance.goto();
    await governance.expectLoaded();
    await governance.openComplianceTab();

    const firstSwitch = page.getByRole("switch").first();
    const saveButton = page.getByRole("button", { name: "Save Changes" });
    await expect(firstSwitch).toBeVisible({ timeout: 15_000 });

    const initialState = (await firstSwitch.getAttribute("aria-checked")) ?? "false";

    await firstSwitch.click();
    await saveButton.click();
    await expect(page.getByText("Settings saved successfully")).toBeVisible({ timeout: 15_000 });
    await expect(saveButton).toBeEnabled({ timeout: 5_000 });

    await firstSwitch.click();
    await saveButton.click();
    await expect(page.getByText("Settings saved successfully")).toBeVisible({ timeout: 15_000 });
    await expect(firstSwitch).toHaveAttribute("aria-checked", initialState);
  });

  test("runs connector test and sync actions when connectors exist", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();

    await page.goto("/connectors");
    await expect(page.getByRole("heading", { name: "Connectors" })).toBeVisible({ timeout: 15_000 });

    const rows = page.locator("tbody tr");
    const emptyState = page.getByText("No connectors yet");

    await expect
      .poll(async () => (await rows.count()) + (await emptyState.count()), { timeout: 15_000 })
      .toBeGreaterThan(0);

    if (await rows.count()) {
      const firstRow = rows.first();
      await firstRow.getByRole("button", { name: "Test connector connection" }).click();
      await expect(firstRow.getByText(/OK \(\d+ ms\)|Failed:/i)).toBeVisible({ timeout: 15_000 });

      await firstRow.getByRole("button", { name: "Sync connector now" }).click();
      await expect(firstRow.getByText(/Sync started|Failed to start sync/i)).toBeVisible({ timeout: 15_000 });
      return;
    }

    await expect(emptyState).toBeVisible();
  });

  test("requests a trace export when traces are available", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();

    const traces = new TracesPage(page);
    await traces.goto();
    await traces.expectLoaded();

    const traceLinks = page.getByRole("link", { name: /View trace detail for request/i });
    const status = page.getByRole("status");

    await expect
      .poll(async () => {
        if ((await traceLinks.count()) > 0) {
          return "rows";
        }

        if (await status.count()) {
          const text = (await status.first().textContent())?.trim() ?? "";
          if (/No execution traces found\./i.test(text)) {
            return "empty";
          }
        }

        return "pending";
      }, { timeout: 15_000 })
      .not.toBe("pending");

    if (await traceLinks.count()) {
      await traceLinks.first().click();
      await expect(page.getByRole("heading", { name: /^Trace / })).toBeVisible({ timeout: 15_000 });

      const exportResponse = page.waitForResponse((response) => {
        return /\/api\/v1\/traces\/.+\/export$/i.test(response.url()) && response.request().method() === "GET";
      });

      await page.getByRole("button", { name: "Export trace as JSON file" }).click();
      expect((await exportResponse).ok()).toBeTruthy();
      return;
    }

    await expect(status).toContainText("No execution traces found.");
  });
});
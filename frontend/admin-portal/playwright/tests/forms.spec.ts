import type { AdminPortalTestArgs } from "../fixtures/adminPortal";
import { test, expect } from "../fixtures/adminPortal";
import { ConnectorsPage } from "../pages/connectors.page";
import { ModelsPage } from "../pages/models.page";
import { PoliciesPage } from "../pages/policies.page";
import { ToolsPage } from "../pages/tools.page";

test.describe("admin portal forms", () => {
  test("opens the add connector wizard", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const connectors = new ConnectorsPage(page);
    await connectors.goto();
    await connectors.expectListLoaded();
    await connectors.openAddConnector();
    await connectors.expectWizardOpen();
  });

  test("opens the model registration and installation forms", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const models = new ModelsPage(page);
    await models.goto();
    await models.expectListLoaded();

    await models.openRegisterModel();
    await models.expectRegisterForm();

    await page.goto("/models");
    await models.openInstallModel();
    await models.expectInstallForm();
  });

  test("opens the tool registration form", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const tools = new ToolsPage(page);
    await tools.goto();
    await tools.expectListLoaded();
    await tools.openRegisterTool();
    await tools.expectRegisterForm();
  });

  test("validates tool registration fields before submit", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const tools = new ToolsPage(page);
    await tools.goto();
    await tools.expectListLoaded();
    await tools.openRegisterTool();
    await tools.expectRegisterForm();

    await page.getByLabel("Tool Name").fill("bad name!");
    await page.getByLabel("Input Schema (JSON)").fill("[]");
    await page.getByRole("button", { name: "Register Tool" }).click();

    await expect(page.getByText("Use letters, numbers, dots, dashes, or underscores only")).toBeVisible();
    await expect(page.getByText("Description is required")).toBeVisible();
    await expect(page.getByText('Must be valid JSON representing an object, e.g. {"type": "object"}')).toBeVisible();
  });

  test("validates model registration fields before submit", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const models = new ModelsPage(page);
    await models.goto();
    await models.expectListLoaded();

    await models.openRegisterModel();
    await models.expectRegisterForm();

    await page.getByLabel("Model ID").fill("bad id");
    await page.getByLabel("Provider").fill("");
    await page.getByLabel("Context window").fill("0");
    await page.getByRole("button", { name: "Register Model" }).click();

    await expect(page.getByText("Use LiteLLM format: provider/model or model-name")).toBeVisible();
    await expect(page.getByText("Provider is required")).toBeVisible();
    await expect(page.getByText("Must be a positive integer")).toBeVisible();
    await expect(page.getByText("Select at least one capability")).toBeVisible();
  });

  test("opens the new policy form", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const policies = new PoliciesPage(page);
    await policies.goto();
    await policies.expectListLoaded();
    await policies.openNewPolicy();
    await policies.expectNewPolicyForm();
    await expect(page.getByRole("button", { name: "Save Draft" })).toBeVisible();
  });
});
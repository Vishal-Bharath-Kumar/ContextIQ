import type { AdminPortalTestArgs } from "../fixtures/adminPortal";
import { test, expect } from "../fixtures/adminPortal";
import { RoutingWeightsPage } from "../pages/routing-weights.page";
import { PoliciesPage } from "../pages/policies.page";
import { ToolsPage } from "../pages/tools.page";
import { TracesPage } from "../pages/traces.page";

test.describe("admin portal extra smoke coverage", () => {
  test("loads routing weights save controls", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const routingWeights = new RoutingWeightsPage(page);
    await routingWeights.goto();
    await routingWeights.expectLoaded();
    expect(await routingWeights.saveButtons().count()).toBeGreaterThan(0);
  });

  test("opens an existing tool edit form when tools are available", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const tools = new ToolsPage(page);
    await tools.goto();
    await tools.expectListLoaded();

    const loadingTools = page.getByText("Loading tools…");
    if (await loadingTools.count()) {
      await expect(loadingTools).toBeHidden();
    }

    const editButtons = tools.editButtons();
    const emptyState = page.getByText("No tools registered yet");

    await expect
      .poll(async () => (await editButtons.count()) + (await emptyState.count()), {
        timeout: 10_000,
      })
      .toBeGreaterThan(0);

    if (await editButtons.count()) {
      await tools.openFirstEditTool();

      await expect(page.getByRole("heading", { name: /Edit Tool:/ })).toBeVisible({ timeout: 15_000 });
      await expect(page.getByRole("button", { name: "Save Changes" })).toBeVisible({ timeout: 15_000 });
      return;
    }

    await expect(emptyState).toBeVisible();
  });

  test("opens an existing policy edit form when policies are available", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const policies = new PoliciesPage(page);
    await policies.goto();
    await policies.expectListLoaded();

    const loadingPolicies = page.getByText("Loading policies…");
    if (await loadingPolicies.count()) {
      await expect(loadingPolicies).toBeHidden();
    }

    const editButtons = page.getByRole("link", { name: "Edit", exact: true });
    const emptyState = page.getByText("No policies defined yet");

    await expect
      .poll(async () => (await editButtons.count()) + (await emptyState.count()), {
        timeout: 10_000,
      })
      .toBeGreaterThan(0);

    if (await editButtons.count()) {
      const href = await editButtons.first().getAttribute("href");

      if (!href) {
        throw new Error("Expected first policy edit link to have an href");
      }

      await page.goto(href);

      await expect(page.getByRole("heading", { name: /Edit Policy:/ })).toBeVisible({ timeout: 15_000 });
      await expect(page.getByRole("button", { name: "Save Draft" })).toBeVisible({ timeout: 15_000 });
      return;
    }

    await expect(emptyState).toBeVisible();
  });

  test("opens a trace detail page when traces are available", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
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
      }, {
        timeout: 15_000,
      })
      .not.toBe("pending");

    if (await traceLinks.count()) {
      await traceLinks.first().click();

      await expect(page.getByRole("heading", { name: /^Trace / })).toBeVisible({ timeout: 15_000 });
      await expect(page.getByRole("button", { name: "Export trace as JSON file" })).toBeVisible({ timeout: 15_000 });
      return;
    }

    await expect(status).toContainText("No execution traces found.");
  });
});
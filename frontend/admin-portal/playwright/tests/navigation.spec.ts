import type { AdminPortalTestArgs } from "../fixtures/adminPortal";
import { test, expect } from "../fixtures/adminPortal";

const NAV_CASES: Array<{ path: string; navLabel: string; heading: string | RegExp }> = [
  { path: "/", navLabel: "Dashboard", heading: /Welcome back/i },
  { path: "/connectors", navLabel: "Connectors", heading: "Connectors" },
  { path: "/models", navLabel: "Models", heading: "Models" },
  { path: "/models/weights", navLabel: "Routing Weights", heading: "Dynamic Model Routing" },
  { path: "/tools", navLabel: "Tool Registry", heading: "Tool Registry" },
  { path: "/policies", navLabel: "Policies", heading: "Policies" },
  { path: "/governance", navLabel: "Governance", heading: "Governance Settings" },
  { path: "/traces", navLabel: "Replay Explorer", heading: "Replay Explorer" },
  { path: "/audit-log", navLabel: "Audit Log", heading: "Audit Log" },
];

test.describe("admin portal navigation", () => {
  for (const navCase of NAV_CASES) {
    test(`loads ${navCase.path}`, async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
      await loginAsAdmin();
      await page.goto(navCase.path);

      const heading =
        typeof navCase.heading === "string"
          ? page.getByRole("heading", { name: navCase.heading, exact: true })
          : page.getByRole("heading", { name: navCase.heading });

      await expect(heading).toBeVisible({ timeout: 15_000 });
    });
  }

  for (const navCase of NAV_CASES) {
    test(`clicks sidebar tab for ${navCase.path}`, async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
      await loginAsAdmin();

      const primaryNav = page.getByRole("navigation", { name: "Primary" });
      await primaryNav.getByRole("link", { name: navCase.navLabel, exact: true }).click();

      await expect(page).toHaveURL(new RegExp(`${navCase.path === "/" ? "/$" : `${navCase.path}$`}`));

      const heading =
        typeof navCase.heading === "string"
          ? page.getByRole("heading", { name: navCase.heading, exact: true })
          : page.getByRole("heading", { name: navCase.heading });

      await expect(heading).toBeVisible({ timeout: 15_000 });
    });
  }
});
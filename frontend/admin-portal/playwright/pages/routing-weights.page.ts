import type { Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";

export class RoutingWeightsPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/models/weights");
  }

  saveButtons(): Locator {
    return this.page.getByRole("button", { name: /Save routing weights for/i });
  }

  async expectLoaded(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Dynamic Model Routing", exact: true })).toBeVisible();
    await expect
      .poll(() => this.saveButtons().count(), {
        timeout: 15_000,
        message: "Expected routing weight controls to render",
      })
      .toBeGreaterThan(0);
  }
}
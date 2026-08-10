import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export class TracesPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/traces");
  }

  async expectLoaded(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Replay Explorer" })).toBeVisible();
    await expect(this.page.getByRole("search", { name: "Trace search filters" })).toBeVisible();
  }
}
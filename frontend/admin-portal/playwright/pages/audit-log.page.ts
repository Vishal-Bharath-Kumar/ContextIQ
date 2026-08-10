import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export class AuditLogPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/audit-log");
  }

  async expectLoaded(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Audit Log" })).toBeVisible();
    await expect(this.page.getByRole("button", { name: "Apply" })).toBeVisible();
  }

  async filterByAction(action: string): Promise<void> {
    await this.page.getByLabel("Filter by action").fill(action);
    await this.page.getByRole("button", { name: "Apply" }).click({ noWaitAfter: true });
  }
}
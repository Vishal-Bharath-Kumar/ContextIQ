import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export class PoliciesPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/policies");
  }

  async expectListLoaded(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Policies" })).toBeVisible();
    await expect(this.page.getByRole("link", { name: /New Policy/i })).toBeVisible();
  }

  async openNewPolicy(): Promise<void> {
    await this.page.getByRole("link", { name: /New Policy/i }).click();
  }

  async expectNewPolicyForm(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "New Policy" })).toBeVisible();
    await expect(this.page.getByLabel("Name")).toBeVisible();
    await expect(this.page.getByLabel("Version")).toBeVisible();
  }
}
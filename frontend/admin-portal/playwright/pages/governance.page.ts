import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export class GovernancePage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/governance");
  }

  async expectLoaded(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Governance Settings", exact: true })).toBeVisible();
  }

  async openComplianceTab(): Promise<void> {
    await this.page.getByRole("button", { name: "Compliance Standards" }).click();
  }

  async openRbacTab(): Promise<void> {
    await this.page.getByRole("button", { name: "RBAC & Permissions" }).click();
  }

  async openPatternTab(): Promise<void> {
    await this.page.getByRole("button", { name: "Pattern Detection" }).click();
  }

  async openRiskTab(): Promise<void> {
    await this.page.getByRole("button", { name: "Risk Scoring" }).click();
  }
}
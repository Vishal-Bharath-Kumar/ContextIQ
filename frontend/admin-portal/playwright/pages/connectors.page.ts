import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export class ConnectorsPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/connectors");
  }

  async openAddConnector(): Promise<void> {
    await this.page.getByRole("link", { name: /Add Connector/i }).click();
  }

  async expectListLoaded(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Connectors" })).toBeVisible();
    await expect(this.page.getByRole("button", { name: /Test connector connection/i }).first()).toBeVisible();
    await expect(this.page.getByRole("button", { name: /Sync connector now/i }).first()).toBeVisible();
  }

  async expectWizardOpen(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Add Connector" })).toBeVisible();
    await expect(this.page.getByText("Connector Type")).toBeVisible();
    await expect(this.page.getByRole("button", { name: "Next" })).toBeVisible();
  }
}
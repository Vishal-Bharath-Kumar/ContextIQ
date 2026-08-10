import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export class ModelsPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/models");
  }

  async expectListLoaded(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Models" })).toBeVisible();
    await expect(this.page.getByRole("link", { name: "Install Model" })).toBeVisible();
    await expect(this.page.getByRole("link", { name: "Register Model" })).toBeVisible();
  }

  async openRegisterModel(): Promise<void> {
    await this.page.getByRole("link", { name: "Register Model" }).click();
  }

  async openInstallModel(): Promise<void> {
    await this.page.getByRole("link", { name: "Install Model" }).click();
  }

  async expectRegisterForm(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Register Model" })).toBeVisible();
    await expect(this.page.getByLabel("Model ID")).toBeVisible();
    await expect(this.page.getByRole("button", { name: "Register Model" })).toBeVisible();
  }

  async expectInstallForm(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Install Model" })).toBeVisible();
    await expect(this.page.getByLabel("Provider Type")).toBeVisible();
  }
}
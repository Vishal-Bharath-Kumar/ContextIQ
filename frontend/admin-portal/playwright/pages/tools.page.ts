import type { Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";

export class ToolsPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/tools");
  }

  async expectListLoaded(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Tool Registry" })).toBeVisible();
    await expect(this.page.getByRole("link", { name: /Register Tool/i })).toBeVisible();
  }

  async openRegisterTool(): Promise<void> {
    await this.page.goto("/tools/add");
  }

  editButtons(): Locator {
    return this.page.getByRole("link", { name: /Edit /i });
  }

  async openFirstEditTool(): Promise<void> {
    const firstEditButton = this.editButtons().first();
    const href = await firstEditButton.getAttribute("href");

    if (!href) {
      throw new Error("Expected first tool edit link to have an href");
    }

    await this.page.goto(href);
  }

  async expectRegisterForm(): Promise<void> {
    await expect(this.page.getByRole("heading", { name: "Register Tool" })).toBeVisible();
    await expect(this.page.getByLabel("Tool Name")).toBeVisible();
    await expect(this.page.getByLabel("Input Schema (JSON)")).toBeVisible();
  }
}
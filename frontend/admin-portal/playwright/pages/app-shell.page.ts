import type { Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";

export class AppShellPage {
  constructor(private readonly page: Page) {}

  navLink(label: string): Locator {
    return this.page.getByLabel("Primary").getByRole("link", { name: label, exact: true });
  }

  async goTo(label: string): Promise<void> {
    const link = this.navLink(label);
    const href = await link.getAttribute("href");

    if (!href) {
      await link.click({ noWaitAfter: true });
      return;
    }

    const expectedPath = new URL(href, this.page.url()).pathname;
    await this.page.goto(expectedPath);
    await expect
      .poll(() => new URL(this.page.url()).pathname, {
        timeout: 15_000,
        message: `Expected navigation to ${expectedPath}`,
      })
      .toBe(expectedPath);
  }

  async expectHeading(name: string | RegExp): Promise<void> {
    const heading =
      typeof name === "string"
        ? this.page.getByRole("heading", { name, exact: true })
        : this.page.getByRole("heading", { name });

    await expect(heading).toBeVisible();
  }

  async signOut(): Promise<void> {
    await this.page.getByRole("button", { name: "Sign out" }).click();
  }
}
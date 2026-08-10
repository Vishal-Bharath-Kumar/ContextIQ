import { AppShellPage } from "../pages/app-shell.page";
import type { AdminPortalTestArgs } from "../fixtures/adminPortal";
import { test, expect } from "../fixtures/adminPortal";

type LocalDevUser = {
  firstName: string;
  lastName: string;
  username: string;
  email: string;
  password: string;
};

function buildLocalDevUser(prefix: string): LocalDevUser {
  const unique = `${Date.now()}-${Math.floor(Math.random() * 100000)}`;

  return {
    firstName: "Playwright",
    lastName: prefix,
    username: `${prefix.toLowerCase()}-${unique}`,
    email: `${prefix.toLowerCase()}-${unique}@contextiq.dev`,
    password: "ContextIQ123!",
  };
}

async function registerLocalDevUser(
  page: AdminPortalTestArgs["page"],
  user: LocalDevUser,
  role: "admin" | "developer" | "platform_engineer",
): Promise<void> {
  await page.goto("/register");
  await page.getByLabel("First name").fill(user.firstName);
  await page.getByLabel("Last name").fill(user.lastName);
  await page.getByLabel("Username").fill(user.username);
  await page.getByLabel("Email").fill(user.email);
  await page.locator("#password").fill(user.password);
  await page.getByLabel("Confirm password").fill(user.password);
  await page.getByLabel("User role").selectOption(role);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/login\?registered=1/);
  await expect(page.getByText("Account created. Sign in with your new username and password.")).toBeVisible();
  await expect(page.locator("#username")).toHaveValue(user.username);
}

async function loginAsLocalDevUser(
  page: AdminPortalTestArgs["page"],
  user: LocalDevUser,
): Promise<void> {
  await page.goto("/login");
  await page.locator("#username").fill(user.username);
  await page.locator("#password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect
    .poll(() => new URL(page.url()).pathname, {
      timeout: 15_000,
      message: "Expected successful sign-in to leave the login route",
    })
    .not.toBe("/login");
}

async function setStoredRoles(
  page: AdminPortalTestArgs["page"],
  roles: string[],
): Promise<void> {
  await page.evaluate((nextRoles) => {
    const raw = sessionStorage.getItem("admin_user");
    if (!raw) {
      throw new Error("Expected an authenticated session in sessionStorage");
    }

    const session = JSON.parse(raw) as {
      token: string;
      user: { id: string; email: string; roles: string[]; name?: string };
    };

    session.user.roles = nextRoles;
    sessionStorage.setItem("admin_user", JSON.stringify(session));
  }, roles);
}

test.describe("admin portal auth", () => {
  test("loads the public login page", async ({ page }: AdminPortalTestArgs) => {
    await page.goto("/login");

    await expect(page.getByRole("heading", { name: "ContextIQ", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  test("loads the public registration page", async ({ page }: AdminPortalTestArgs) => {
    await page.goto("/register");

    await expect(page.getByRole("heading", { name: "Create account", exact: true })).toBeVisible();
    await expect(page.getByLabel("Username")).toBeVisible();
  });

  test("loads the forbidden page", async ({ page }: AdminPortalTestArgs) => {
    await page.goto("/403");

    await expect(page.getByRole("heading", { name: /403 .*Access Denied/i })).toBeVisible();
    await expect(page.getByRole("link", { name: "Go to home page" })).toBeVisible();
  });

  test("registers a new developer account and signs in with it", async ({ page }: AdminPortalTestArgs) => {
    const user = buildLocalDevUser("Developer");

    await registerLocalDevUser(page, user, "developer");
    await loginAsLocalDevUser(page, user);

    await expect(page.getByRole("heading", { name: /Welcome back/i })).toBeVisible({ timeout: 15_000 });
  });

  test("redirects a developer away from platform-engineer routes", async ({ page }: AdminPortalTestArgs) => {
    const user = buildLocalDevUser("DeveloperRole");

    await registerLocalDevUser(page, user, "developer");
    await loginAsLocalDevUser(page, user);

    await page.goto("/tools");
    await expect(page).toHaveURL(/\/403$/);
    await expect(page.getByRole("heading", { name: /403 .*Access Denied/i })).toBeVisible();

    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Welcome back/i })).toBeVisible({ timeout: 15_000 });
  });

  test("allows a platform engineer into tool routes but blocks policy routes", async ({ page }: AdminPortalTestArgs) => {
    const user = buildLocalDevUser("PlatformEngineer");

    await registerLocalDevUser(page, user, "platform_engineer");
    await loginAsLocalDevUser(page, user);

    await page.goto("/tools");
    await expect(page.getByRole("heading", { name: "Tool Registry" })).toBeVisible({ timeout: 15_000 });

    await page.goto("/policies");
    await expect(page).toHaveURL(/\/403$/);
    await expect(page.getByRole("heading", { name: /403 .*Access Denied/i })).toBeVisible();
  });

  test("allows a simulated security-officer session into policy routes and blocks tool routes", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    await setStoredRoles(page, ["security_officer"]);

    await page.goto("/policies");
    await expect(page.getByRole("heading", { name: "Policies" })).toBeVisible({ timeout: 15_000 });

    await page.goto("/governance");
    await expect(page.getByRole("heading", { name: "Governance Settings", exact: true })).toBeVisible({ timeout: 15_000 });

    await page.goto("/tools");
    await expect(page).toHaveURL(/\/403$/);
    await expect(page.getByRole("heading", { name: /403 .*Access Denied/i })).toBeVisible();
  });

  test("allows a simulated auditor session into trace routes and blocks policy routes", async ({ page, loginAsAdmin }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    await setStoredRoles(page, ["auditor"]);

    await page.goto("/traces");
    await expect(page.getByRole("heading", { name: "Replay Explorer" })).toBeVisible({ timeout: 15_000 });

    await page.goto("/audit-log");
    await expect(page.getByRole("heading", { name: "Audit Log" })).toBeVisible({ timeout: 15_000 });

    await page.goto("/policies");
    await expect(page).toHaveURL(/\/403$/);
    await expect(page.getByRole("heading", { name: /403 .*Access Denied/i })).toBeVisible();
  });

  test("signs in with the local dev admin and signs out", async ({ page, loginAsAdmin, baseURL }: AdminPortalTestArgs) => {
    await loginAsAdmin();
    const shell = new AppShellPage(page);
    await shell.expectHeading(/Welcome back/i);

    await shell.signOut();
    await expect(page).toHaveURL(`${baseURL}/login`);
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
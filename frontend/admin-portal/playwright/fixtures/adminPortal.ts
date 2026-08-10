import type { APIRequestContext, Page } from "@playwright/test";
import { test as base, expect } from "@playwright/test";

type AdminPortalFixtures = {
  loginAsAdmin: () => Promise<void>;
};

export type AdminPortalTestArgs = {
  page: Page;
  loginAsAdmin: () => Promise<void>;
  baseURL?: string;
};

type StoredSession = {
  token: string;
  user: {
    id: string;
    email: string;
    roles: string[];
    name?: string;
  };
};

function decodeJwtPayload(token: string): Record<string, unknown> {
  const [, payload] = token.split(".");
  if (!payload) {
    throw new Error("Malformed JWT returned from dev-login");
  }

  const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  return JSON.parse(atob(padded)) as Record<string, unknown>;
}

function buildStoredSession(token: string): StoredSession {
  const claims = decodeJwtPayload(token);
  const realmRoles = (claims.realm_access as { roles?: string[] } | undefined)?.roles ?? [];

  return {
    token,
    user: {
      id: String(claims.sub ?? ""),
      email: String(claims.email ?? claims.preferred_username ?? ""),
      roles: realmRoles,
      name: (claims.name as string | undefined) ?? (claims.preferred_username as string | undefined),
    },
  };
}

async function loginViaDevEndpoint(
  request: APIRequestContext,
  baseURL: string,
): Promise<{ access_token: string }> {
  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await request.post(`${baseURL}/api/auth/dev-login`, {
        data: { username: "admin", password: "admin" },
      });

      if (response.ok()) {
        return (await response.json()) as { access_token: string };
      }

      lastError = new Error(`dev-login returned ${response.status()} on attempt ${attempt}`);
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }

  throw lastError ?? new Error("dev-login failed after retries");
}

export const test = base.extend<AdminPortalFixtures>({
  loginAsAdmin: async ({ page, baseURL, request }, use) => {
    await use(async () => {
      if (!baseURL) {
        throw new Error("Playwright baseURL is required for admin login fixture");
      }

      const loginData = await loginViaDevEndpoint(request, baseURL);
      const session = buildStoredSession(loginData.access_token);

      await page.addInitScript((storedSession) => {
        if (sessionStorage.getItem("__pw_admin_seeded")) {
          return;
        }

        sessionStorage.setItem("admin_user", JSON.stringify(storedSession));
        sessionStorage.setItem("__pw_admin_seeded", "1");
      }, session);

      await page.goto(`${baseURL}/`);

      await expect
        .poll(() => new URL(page.url()).pathname, {
          timeout: 15_000,
          message: "Expected seeded admin session to bypass the login route",
        })
        .not.toBe("/login");

      await expect(page.getByRole("heading", { name: /Welcome back/i })).toBeVisible({ timeout: 15_000 });
    });
  },
});

export { expect };
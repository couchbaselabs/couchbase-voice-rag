import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/**
 * Couchbase-dependent routes that the Playwright backend cannot serve
 * (no live cluster) get intercepted at the page layer with realistic
 * happy-path responses. Auth routes go through to the real FastAPI
 * process so the httpOnly cookie + ``GET /api/auth/me`` flow is
 * exercised end-to-end.
 */
async function stubCouchbaseRoutes(page: Page): Promise<void> {
  await page.route("**/api/settings/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ initialized: true }),
    });
  });
  await page.route("**/api/documents", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });
  await page.route("**/api/chat/sessions", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });
  await page.route(/\/api\/chat\/sessions\/[^/]+$/, async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Session not found" }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true }),
      });
    }
  });
}

test.describe("smoke", () => {
  test.beforeEach(async ({ page }) => {
    await stubCouchbaseRoutes(page);
  });

  test("login page passes axe a11y scan", async ({ page }) => {
    await page.goto("/login");
    await expect(
      page.getByRole("heading", { name: /couchbase realtime voice rag/i })
    ).toBeVisible();

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations).toEqual([]);
  });

  test("chat page passes axe a11y scan", async ({ page }) => {
    // Log in first so the cookie is present and /chat renders.
    await page.goto("/login");
    await page.getByLabel(/username/i).fill("e2e");
    await page.getByLabel(/password/i).fill("e2e-password-1234");
    await page.getByRole("button", { name: /login/i }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole("button", { name: /new chat/i })).toBeVisible();

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations).toEqual([]);
  });

  test("login → new chat → logout round trip", async ({ page, context }) => {
    await page.goto("/login");

    await page.getByLabel(/username/i).fill("e2e");
    await page.getByLabel(/password/i).fill("e2e-password-1234");

    const loginResp = page.waitForResponse(
      (r) => r.url().includes("/api/auth/login") && r.request().method() === "POST",
      { timeout: 10_000 }
    );
    await page.getByRole("button", { name: /login/i }).click();
    const login = await loginResp;
    expect(login.status()).toBe(200);

    // Phase F3 regression guard: the backend must issue an httpOnly cookie.
    const cookies = await context.cookies();
    const tokenCookie = cookies.find((c) => c.name === "token");
    expect(tokenCookie, "backend must set an httpOnly `token` cookie").toBeTruthy();
    expect(tokenCookie?.httpOnly).toBe(true);

    // Chat page loads after /api/auth/me returns 200 with the new cookie.
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole("button", { name: /new chat/i })).toBeVisible();
    await expect(page.getByText(/logged in as e2e/i)).toBeVisible();

    // Starting a new chat assigns a session id; we can observe that by the
    // "New Chat" button staying functional and the sidebar re-rendering.
    await page.getByRole("button", { name: /new chat/i }).click();

    // Logout lives inside the sidebar footer popover that opens on
    // the "Logged in as <user>" button -- open the menu first, then
    // click the Logout menuitem.
    await page.getByRole("button", { name: /logged in as e2e/i }).click();
    await page.getByRole("menuitem", { name: /logout/i }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
});

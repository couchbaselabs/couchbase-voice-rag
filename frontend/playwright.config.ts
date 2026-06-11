import os from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const TMP_DIR = process.env.E2E_TMP_DIR ?? path.join(os.tmpdir(), "couchbase-rag-e2e");
const APP_USERS_FILE = path.join(TMP_DIR, "app_users.json");

const FRONTEND_PORT = Number(process.env.PLAYWRIGHT_FRONTEND_PORT ?? 53001);
const BACKEND_PORT = Number(process.env.PLAYWRIGHT_BACKEND_PORT ?? 58001);

const BACKEND_ENV: Record<string, string> = {
  JWT_SECRET: "e2e-test-secret-at-least-32-characters-long",
  // Empty CB_CONNECTION_STRING keeps the backend alive without Couchbase —
  // Couchbase-dependent routes are intercepted by page.route() in tests.
  CB_CONNECTION_STRING: "",
  APP_USERS: "",
  APP_USERS_FILE,
  DEEPGRAM_API_KEY: "",
  TAVILY_API_KEY: "",
  // Backend needs AZURE_OPENAI_ENDPOINT + OPENAI_API_KEY to import, but
  // no route in the smoke flow actually calls them.
  AZURE_OPENAI_ENDPOINT: "https://example.openai.azure.com",
  OPENAI_API_KEY: "e2e-unused",
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      // Backend: seed the E2E user into the tmp users file, then boot FastAPI.
      command: [
        `mkdir -p ${TMP_DIR}`,
        "uv run python scripts/seed_e2e_user.py",
        `uv run uvicorn main:app --port ${BACKEND_PORT}`,
      ].join(" && "),
      cwd: path.join(__dirname, "..", "backend"),
      url: `http://localhost:${BACKEND_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: BACKEND_ENV,
    },
    {
      command: `pnpm run dev --port ${FRONTEND_PORT}`,
      cwd: __dirname,
      url: `http://localhost:${FRONTEND_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        NEXT_PUBLIC_API_URL: `http://localhost:${BACKEND_PORT}`,
      },
    },
  ],
});

import { defineConfig, devices } from "@playwright/test";
import path from "path";

// End-to-end coverage across the full patient and provider journeys —
// see docs/phase10a-e2e-test-suite.md. This REPLACES the manual browser
// verification every prior epic in this project relied on ad hoc.
//
// Deliberately self-contained ("zero setup", matching this project's own
// philosophy for SQLite/fakeredis/etc): `webServer` below starts BOTH the
// real FastAPI backend and the real Next.js frontend as actual child
// processes — these tests exercise the genuine HTTP/DB/Redis stack, not
// mocks. A throwaway SQLite DB and fakeredis keep this from touching a
// real dev database or requiring a real Redis server; `REPORT_DELIVERY_SYNC`
// /`ALERTING_SYNC`/`RETENTION_SYNC`/`RATE_LIMIT_ENABLED=0` mirror the exact
// same env vars backend/tests/conftest.py sets for the same reasons
// (deterministic, in-process job execution; no rate-limit flakiness from
// registering many accounts across specs).
const E2E_DB_PATH = path.join(__dirname, "..", "backend", ".e2e-test.db");
const E2E_UPLOAD_DIR = path.join(__dirname, "..", "backend", ".e2e-test-uploads");

const BACKEND_ENV = {
  DATABASE_URL: `sqlite:///${E2E_DB_PATH}`,
  REDIS_FAKE: "1",
  RATE_LIMIT_ENABLED: "0",
  EMBEDDING_FAKE: "1",
  ALERTING_SYNC: "1",
  RETENTION_SYNC: "1",
  REPORT_DELIVERY_SYNC: "1",
  SYMPTOM_PHOTO_UPLOAD_DIR: E2E_UPLOAD_DIR,
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // shared backend DB — specs run serially to avoid cross-test interference
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"]],
  globalSetup: require.resolve("./e2e/global-setup"),
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Port 8020 (not the README's usual 8000 example) — deliberately: this
  // suite must not collide with a real dev backend a developer might
  // already have running locally on 8000.
  webServer: [
    {
      command: "../backend/.venv/bin/uvicorn app.main:app --port 8020",
      cwd: "../backend",
      url: "http://127.0.0.1:8020/health",
      timeout: 60_000,
      reuseExistingServer: false,
      env: BACKEND_ENV,
    },
    {
      command: "npm run dev",
      cwd: ".",
      url: "http://localhost:3000",
      timeout: 60_000,
      reuseExistingServer: false,
      env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8020" },
    },
  ],
});

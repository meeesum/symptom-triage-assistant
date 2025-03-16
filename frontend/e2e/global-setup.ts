import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";

// Runs once before the whole suite. Does its own migration + admin
// bootstrap independently of the `webServer` processes in
// playwright.config.ts (rather than assuming the backend's own startup
// lifespan has already run migrations by the time this executes) — this
// is what lets `npx playwright test` be self-contained regardless of
// exactly when Playwright starts the webServer vs. globalSetup relative
// to each other.
//
// Deletes any stale DB file from a previous run first: this suite isn't
// per-file isolated (specs share one backend/DB, matching how the real
// app behaves — see playwright.config.ts's `fullyParallel: false`), so a
// leftover DB from an interrupted previous run would carry over stale
// state (e.g. an admin account whose password doesn't match what this
// run expects).
export const ADMIN_EMAIL = "e2e-admin@example.com";
export const ADMIN_PASSWORD = "e2e-admin-password-123";

async function globalSetup() {
  const backendDir = path.join(__dirname, "..", "..", "backend");
  const dbPath = path.join(backendDir, ".e2e-test.db");
  const uploadDir = path.join(backendDir, ".e2e-test-uploads");

  if (fs.existsSync(dbPath)) fs.rmSync(dbPath);
  if (fs.existsSync(uploadDir)) fs.rmSync(uploadDir, { recursive: true });

  const env = {
    ...process.env,
    DATABASE_URL: `sqlite:///${dbPath}`,
    REDIS_FAKE: "1",
    SYMPTOM_PHOTO_UPLOAD_DIR: uploadDir,
  };
  const pythonBin = path.join(backendDir, ".venv", "bin", "python3");

  execFileSync(pythonBin, ["scripts/migrate.py"], { cwd: backendDir, env, stdio: "inherit" });

  // create_admin.py prompts for a password via getpass(), which falls
  // back to reading a line from stdin when there's no real TTY attached
  // (exactly this case) — piping the password in is the non-interactive
  // equivalent of what a real deployment operator would type.
  execFileSync(pythonBin, ["scripts/create_admin.py", ADMIN_EMAIL], {
    cwd: backendDir,
    env,
    input: `${ADMIN_PASSWORD}\n`,
    stdio: ["pipe", "inherit", "inherit"],
  });
}

export default globalSetup;

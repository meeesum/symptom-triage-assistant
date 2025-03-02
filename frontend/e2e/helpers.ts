import { APIRequestContext, Page, expect } from "@playwright/test";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./global-setup";

export const API_BASE = "http://127.0.0.1:8020"; // matches playwright.config.ts's webServer
export const TEST_PASSWORD = "correct-horse-battery-staple";

let emailCounter = 0;
export function randomEmail(prefix: string): string {
  emailCounter += 1;
  return `${prefix}-${Date.now()}-${emailCounter}@example.com`;
}

// --- API-layer setup helpers -------------------------------------------
//
// Playwright's own guidance (and this suite's own judgment): use the API
// directly for SETUP that isn't itself under test (registering a fixture
// account, promoting a role, assigning a panel), and drive the UI only
// for the actual behavior a spec is verifying. Doing every setup step
// through the UI would make these tests slow AND would make a genuine UI
// regression in, say, the login form, spuriously fail unrelated specs
// that only needed a logged-in user as a precondition.

export async function apiRegisterPatient(
  request: APIRequestContext,
  email: string,
  password: string = TEST_PASSWORD
): Promise<string> {
  const res = await request.post(`${API_BASE}/auth/register`, {
    data: { email, password },
  });
  expect(res.ok(), `register ${email} failed: ${await res.text()}`).toBeTruthy();
  return (await res.json()).access_token as string;
}

export async function apiLogin(
  request: APIRequestContext,
  email: string,
  password: string = TEST_PASSWORD
): Promise<string> {
  const res = await request.post(`${API_BASE}/auth/login`, {
    data: { email, password },
  });
  expect(res.ok(), `login ${email} failed: ${await res.text()}`).toBeTruthy();
  return (await res.json()).access_token as string;
}

export async function adminToken(request: APIRequestContext): Promise<string> {
  return apiLogin(request, ADMIN_EMAIL, ADMIN_PASSWORD);
}

async function findUserId(
  request: APIRequestContext,
  admin: string,
  email: string
): Promise<number> {
  const res = await request.get(`${API_BASE}/admin/users`, {
    headers: { Authorization: `Bearer ${admin}` },
  });
  expect(res.ok()).toBeTruthy();
  const users: { id: number; email: string }[] = await res.json();
  const user = users.find((u) => u.email === email);
  if (!user) throw new Error(`user ${email} not found in /admin/users`);
  return user.id;
}

// Registers a fresh patient, promotes it to `role` via the real admin
// endpoint (exercising the actual promotion path, not a DB shortcut),
// and returns a fresh token carrying the new role — a token minted
// before promotion keeps its stale role claim until refreshed, same
// caveat the backend's own test suite documents.
export async function apiRegisterAndPromote(
  request: APIRequestContext,
  role: "provider" | "org_admin" | "admin"
): Promise<{ email: string; userId: number; token: string }> {
  const email = randomEmail(role);
  await apiRegisterPatient(request, email);
  const admin = await adminToken(request);
  const userId = await findUserId(request, admin, email);
  const patchRes = await request.patch(`${API_BASE}/admin/users/${userId}/role`, {
    headers: { Authorization: `Bearer ${admin}` },
    data: { role },
  });
  expect(patchRes.ok(), `promote ${email} to ${role} failed: ${await patchRes.text()}`).toBeTruthy();
  const token = await apiLogin(request, email);
  return { email, userId, token };
}

export async function apiAssignPanel(
  request: APIRequestContext,
  providerId: number,
  patientId: number
): Promise<void> {
  const admin = await adminToken(request);
  const res = await request.post(`${API_BASE}/panel/assignments`, {
    headers: { Authorization: `Bearer ${admin}` },
    data: { provider_id: providerId, patient_id: patientId },
  });
  expect(res.ok(), `panel assignment failed: ${await res.text()}`).toBeTruthy();
}

export async function apiSubmitTriage(
  request: APIRequestContext,
  token: string,
  text: string
): Promise<{ tier: string; audit_record_id: number | null }> {
  const res = await request.post(`${API_BASE}/triage/intake`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { text },
  });
  expect(res.ok(), `triage intake failed: ${await res.text()}`).toBeTruthy();
  return res.json();
}

// --- UI-layer helpers ----------------------------------------------------

export async function uiRegister(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: "Need an account? Register" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.locator(".navbar-role")).toBeVisible();
}

export async function uiLogin(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  // The login form redirects on success — wait for the navbar's
  // logged-in state rather than a fixed URL, since patients land on "/"
  // and everyone else lands on "/audit".
  await expect(page.locator(".navbar-role")).toBeVisible();
}

// Sets localStorage auth state directly from an API-minted token,
// skipping the login FORM entirely — used by specs whose subject is a
// role/page other than login itself (e.g. the provider/admin journeys),
// where going through the UI login form on every spec would be pure
// overhead unrelated to what's being tested. auth.ts's own localStorage
// keys are duplicated here deliberately (not imported) since e2e specs
// intentionally don't share code with the app under test.
export async function setAuthState(
  page: Page,
  token: string,
  role: string,
  refreshToken = "e2e-fake-refresh-token"
): Promise<void> {
  await page.addInitScript(
    ([t, r, rt]) => {
      localStorage.setItem("triage_auth_token", t);
      localStorage.setItem("triage_auth_refresh_token", rt);
      localStorage.setItem("triage_auth_role", r);
    },
    [token, role, refreshToken]
  );
}

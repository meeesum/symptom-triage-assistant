import { test, expect } from "@playwright/test";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./global-setup";
import { apiRegisterPatient, randomEmail, TEST_PASSWORD, uiLogin } from "./helpers";

// Admin journey: role assignment is admin-controlled (registration only
// ever creates patients — see docs/phase4b-auth-rbac.md), so this is the
// ONLY path that promotes a patient to provider in this project. Driven
// through the real /admin UI, not the API, since the UI's dropdown
// interaction is specifically what's under test here (the other specs
// use the API for promotion because that's setup, not the subject).

test.describe("admin journey", () => {
  test("logs in and promotes a patient to provider via the /admin dropdown", async ({
    page,
    request,
  }) => {
    const patientEmail = randomEmail("promote-me");
    await apiRegisterPatient(request, patientEmail, TEST_PASSWORD);

    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "User Management" })).toBeVisible();

    const row = page.locator("tr", { hasText: patientEmail });
    await expect(row).toBeVisible();
    await expect(row).toContainText("patient");

    await row.getByRole("combobox").selectOption("provider");

    // Persisted server-side, not just local UI state — reload and
    // confirm the promotion survived.
    await page.reload();
    const reloadedRow = page.locator("tr", { hasText: patientEmail });
    await expect(reloadedRow).toContainText("provider");
  });

  test("the role dropdown offers org_admin, not just provider/admin", async ({ page }) => {
    // Regression test for a real bug: the dropdown's option list omitted
    // org_admin entirely (see the ROLES fix in app/admin/page.tsx) — an
    // admin had no way to assign that role through this UI at all, even
    // though the backend has accepted it since the multi-tenancy epic.
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.goto("/admin");
    const anyRow = page.locator("tbody tr").first();
    await expect(anyRow).toBeVisible();
    const options = await anyRow.locator("select option").allTextContents();
    expect(options).toEqual(["patient", "provider", "org_admin", "admin"]);
  });
});

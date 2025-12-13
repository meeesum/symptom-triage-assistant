import { test, expect } from "@playwright/test";
import path from "path";
import {
  API_BASE,
  apiAssignPanel,
  apiRegisterAndPromote,
  apiRegisterPatient,
  apiSubmitTriage,
  randomEmail,
  setAuthState,
  TEST_PASSWORD,
} from "./helpers";

// Provider journey: sees only their own panel's records on the audit
// trail and analytics dashboard, plus anonymous ones — the panel-scoping
// rule established in docs/phase7a-patient-panels.md, exercised here
// through the real UI rather than just the backend test suite.

test.describe("provider journey", () => {
  test("sees a panel patient's emergency triage on the audit trail and analytics", async ({
    page,
    request,
  }) => {
    const { userId: providerId, token: providerToken } = await apiRegisterAndPromote(
      request,
      "provider"
    );
    const patientEmail = randomEmail("panel-patient");
    const patientToken = await apiRegisterPatient(request, patientEmail);

    // Find the patient's user id via the same admin listing helper the
    // provider-promotion path already uses.
    const adminEmail = "e2e-admin@example.com";
    const adminRes = await request.post(`${API_BASE}/auth/login`, {
      data: { email: adminEmail, password: "e2e-admin-password-123" },
    });
    const adminTok = (await adminRes.json()).access_token;
    const usersRes = await request.get(`${API_BASE}/admin/users`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    });
    const users: { id: number; email: string }[] = await usersRes.json();
    const patientId = users.find((u) => u.email === patientEmail)!.id;

    await apiAssignPanel(request, providerId, patientId);

    const { audit_record_id } = await apiSubmitTriage(
      request,
      patientToken,
      "sudden severe chest pain and I'm sweating"
    );
    expect(audit_record_id).not.toBeNull();

    // Upload a real photo as the patient, ahead of time, so the
    // provider's read-only gallery has something real to show.
    await request.post(`${API_BASE}/audit/${audit_record_id}/photos`, {
      headers: { Authorization: `Bearer ${patientToken}` },
      multipart: {
        file: {
          name: "rash.jpg",
          mimeType: "image/jpeg",
          buffer: require("fs").readFileSync(path.join(__dirname, "fixtures", "test-rash.jpg")),
        },
      },
    });

    await setAuthState(page, providerToken, "provider");
    await page.goto("/audit");

    await expect(page.getByRole("heading", { name: "Provider Audit Trail" })).toBeVisible();
    const row = page.locator("tbody tr", { hasText: "chest_pain" });
    await expect(row).toBeVisible();
    await expect(row.locator(".tier-badge")).toHaveClass(/tier-emergency/);

    // The provider's read-only photo gallery on this exact row.
    await row.getByRole("button", { name: "Photos" }).click();
    await expect(row.locator(".photo-gallery-item img")).toBeVisible({ timeout: 10_000 });
    // Read-only for a provider — no delete control, unlike the patient's
    // own gallery in patient-journey.spec.ts.
    await expect(row.locator(".photo-gallery-delete")).toHaveCount(0);

    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Provider Analytics" })).toBeVisible();
    await expect(page.locator(".stat-tiles")).toContainText("triages, last 30d");
  });

  test("does NOT see another provider's panel patient", async ({ page, request }) => {
    const { token: outsiderToken } = await apiRegisterAndPromote(request, "provider");
    const { userId: ownerProviderId } = await apiRegisterAndPromote(request, "provider");

    const patientEmail = randomEmail("private-patient");
    const patientToken = await apiRegisterPatient(request, patientEmail);
    const adminRes = await request.post(`${API_BASE}/auth/login`, {
      data: { email: "e2e-admin@example.com", password: "e2e-admin-password-123" },
    });
    const adminTok = (await adminRes.json()).access_token;
    const usersRes = await request.get(`${API_BASE}/admin/users`, {
      headers: { Authorization: `Bearer ${adminTok}` },
    });
    const users: { id: number; email: string }[] = await usersRes.json();
    const patientId = users.find((u) => u.email === patientEmail)!.id;
    await apiAssignPanel(request, ownerProviderId, patientId);

    const { audit_record_id } = await apiSubmitTriage(
      request,
      patientToken,
      "a mild headache that started gradually"
    );
    expect(audit_record_id).not.toBeNull();

    await setAuthState(page, outsiderToken, "provider");
    await page.goto("/audit");
    await expect(page.getByRole("heading", { name: "Provider Audit Trail" })).toBeVisible();
    await expect(page.locator("tbody")).not.toContainText("headache");
  });
});

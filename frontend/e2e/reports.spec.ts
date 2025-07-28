import { test, expect } from "@playwright/test";
import { apiRegisterAndPromote, setAuthState } from "./helpers";

// Reporting exports — see docs/phase9d-reporting-exports.md. Also
// exercises the org_admin /audit and /analytics page-gate fix from that
// same epic, since an org_admin reaching /analytics at all is a
// precondition for this whole flow.

test.describe("reporting exports", () => {
  test("org_admin can reach the dashboard, subscribe, and trigger a report send", async ({
    page,
    request,
  }) => {
    const { token } = await apiRegisterAndPromote(request, "org_admin");
    await setAuthState(page, token, "org_admin");

    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Provider Analytics" })).toBeVisible();

    const panel = page.locator(".report-subscription-panel");
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("Scheduled reports");

    await panel.getByRole("button", { name: "Subscribe" }).click();
    await expect(panel).toContainText("Subscription saved.");
    await expect(panel).toContainText("Subscribed (weekly, pdf)");

    await panel.getByRole("button", { name: "Send now" }).click();
    await expect(panel).toContainText("Report queued for delivery.");
  });

  test("Export CSV and Export PDF report trigger real downloads", async ({ page, request }) => {
    const { token } = await apiRegisterAndPromote(request, "org_admin");
    await setAuthState(page, token, "org_admin");
    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Provider Analytics" })).toBeVisible();

    const [csvDownload] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Export CSV" }).click(),
    ]);
    expect(csvDownload.suggestedFilename()).toBe("triage_audit_export.csv");

    const [pdfDownload] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Export PDF report" }).click(),
    ]);
    expect(pdfDownload.suggestedFilename()).toBe("triage_analytics_report.pdf");
  });
});

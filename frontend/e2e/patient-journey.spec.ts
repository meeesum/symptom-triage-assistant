import { test, expect } from "@playwright/test";
import { randomEmail, TEST_PASSWORD, uiRegister } from "./helpers";

// Full patient journey: register through the real UI form, submit a
// self-care symptom and an emergency one, and attach a real photo to a
// completed result — the exact set of things every prior epic in this
// project verified by hand in the browser (see docs/phase*.md's "Live
// verification" sections). This spec is what makes that repeatable.

test.describe("patient journey", () => {
  test("registers, gets a self-care decision, then an emergency decision", async ({ page }) => {
    const email = randomEmail("patient");
    await uiRegister(page, email, TEST_PASSWORD);

    // Patients land on "/" (the triage chat) after registering.
    await expect(page).toHaveURL("/");
    await expect(page.getByRole("heading", { name: "Symptom Triage Assistant" })).toBeVisible();

    // --- Self-care path -------------------------------------------------
    // Includes severity ("mild") and onset ("started suddenly") explicitly
    // — the real UI always sets allow_follow_up: true (see TriageChat.tsx),
    // so a bare "I have a mild cough" with no onset would correctly get a
    // clarifying follow-up question instead of an immediate decision (the
    // multi-turn confidence check working as designed, not a bug). Onset
    // matters for which rule matches, not just whether one does: a
    // GRADUAL onset for a mild cough matches rules.yaml's
    // persistent_mild_symptoms rule (routine tier) before it ever reaches
    // the self_care fallback — "started suddenly" avoids that and lands
    // on default_mild_acute (self_care) instead, which is what this test
    // actually means to exercise.
    await page
      .getByPlaceholder("Describe your symptoms…")
      .fill("I have a mild cough that started suddenly");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    const firstResult = page.locator(".result-bubble").first();
    await expect(firstResult).toBeVisible({ timeout: 15_000 });
    await expect(firstResult.locator(".tier-badge")).toHaveClass(/tier-self_care/);
    await expect(firstResult.locator(".understood")).toContainText("cough");

    // --- Emergency path (fast path — no RAG, should be immediate) ------
    await page
      .getByPlaceholder("Describe your symptoms…")
      .fill("sudden severe chest pain and I'm sweating");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    const emergencyResult = page.locator(".result-bubble").nth(1);
    await expect(emergencyResult).toBeVisible({ timeout: 15_000 });
    await expect(emergencyResult.locator(".tier-badge")).toHaveClass(/tier-emergency/);
    await expect(emergencyResult.locator(".emergency-callout")).toBeVisible();
    await expect(emergencyResult.locator(".understood")).toContainText("chest pain");
    await expect(emergencyResult.locator(".understood")).toContainText("sweating");
  });

  test("an ambiguous message gets a follow-up question, and the answer completes the decision", async ({
    page,
  }) => {
    const email = randomEmail("patient-followup");
    await uiRegister(page, email, TEST_PASSWORD);

    await page.getByPlaceholder("Describe your symptoms…").fill("I don't feel great");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    const followUp = page.locator(".follow-up-bubble").first();
    await expect(followUp).toBeVisible({ timeout: 15_000 });

    // The input placeholder changes once a follow-up is pending — a
    // concrete, checkable signal the multi-turn flow (not just a
    // decision) is actually active.
    await expect(page.getByPlaceholder("Answer the question above…")).toBeVisible();
    await page
      .getByPlaceholder("Answer the question above…")
      .fill("a mild rash that started gradually a couple days ago");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    const result = page.locator(".result-bubble").first();
    await expect(result).toBeVisible({ timeout: 15_000 });
    await expect(result.locator(".understood")).toContainText("rash");
  });

  test("a photo can be attached to a completed triage result and appears in the gallery", async ({
    page,
  }) => {
    const email = randomEmail("patient-photo");
    await uiRegister(page, email, TEST_PASSWORD);

    // Same reasoning as the self-care test above: includes severity and
    // onset so it resolves immediately instead of prompting a follow-up.
    await page
      .getByPlaceholder("Describe your symptoms…")
      .fill("a mild rash on my arm that's been going on for a few days");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    const result = page.locator(".result-bubble").first();
    await expect(result).toBeVisible({ timeout: 15_000 });

    // The Photos control only renders once the response carries a real
    // audit_record_id (see components/PhotoGallery.tsx) — this alone is
    // a regression check that /triage/intake's response actually
    // includes it, on top of what the upload itself proves below.
    const photosToggle = result.getByRole("button", { name: "Photos" });
    await expect(photosToggle).toBeVisible();
    await photosToggle.click();

    await expect(result.getByText("No photos attached.")).toBeVisible();

    // A real file upload through the actual <input type="file"> — the
    // one piece of this project's manual verification that couldn't be
    // exercised through the browser-automation tool used during
    // development (no file-picker support there); Playwright closes
    // that real gap.
    const fixturePath = require("path").join(__dirname, "fixtures", "test-rash.jpg");
    await result.locator('input[type="file"]').setInputFiles(fixturePath);

    await expect(result.locator(".photo-gallery-item img")).toBeVisible({ timeout: 10_000 });
    await expect(result.getByText("No photos attached.")).not.toBeVisible();
  });
});

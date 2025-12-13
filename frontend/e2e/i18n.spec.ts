import { test, expect } from "@playwright/test";
import { randomEmail, TEST_PASSWORD, uiRegister } from "./helpers";

// English/Spanish coverage — see docs/phase9b-internationalization.md.
// The backend half (Spanish symptom extraction, guidance translation,
// KB retrieval) already has thorough pytest coverage; this spec is the
// missing piece — proving the LANGUAGE SWITCH itself works end to end in
// a real browser and that a Spanish submission renders Spanish UI.

test.describe("internationalization", () => {
  test("switching to Español translates the visible UI immediately", async ({ page }) => {
    const email = randomEmail("i18n-patient");
    await uiRegister(page, email, TEST_PASSWORD);

    await expect(page.getByRole("heading", { name: "Symptom Triage Assistant" })).toBeVisible();
    await expect(page.getByPlaceholder("Describe your symptoms…")).toBeVisible();

    await page.getByLabel("Language").selectOption("es");

    await expect(page.getByPlaceholder("Describe tus síntomas…")).toBeVisible();
    await expect(page.getByRole("link", { name: "Triaje" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Enviar" })).toBeVisible();
  });

  test("a Spanish emergency message gets a Spanish tier badge and guidance", async ({ page }) => {
    const email = randomEmail("i18n-emergency");
    await uiRegister(page, email, TEST_PASSWORD);
    await page.getByLabel("Language").selectOption("es");

    await page
      .getByPlaceholder("Describe tus síntomas…")
      .fill("de repente tengo dolor en el pecho, es severo, y estoy sudando");
    await page.getByRole("button", { name: "Enviar" }).click();

    const result = page.locator(".result-bubble").first();
    await expect(result).toBeVisible({ timeout: 15_000 });
    await expect(result.locator(".tier-badge")).toContainText("Emergencia");
    await expect(result.locator(".guidance-text")).toContainText("servicios de emergencia");
  });
});

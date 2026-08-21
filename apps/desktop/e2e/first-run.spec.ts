/**
 * FA-017.6 Part 40: a real-binary E2E covering the first-run hero (zero
 * managed roots) and its transition into the ordinary organize flow. No
 * mocked FileAgent business logic -- the real compiled Tauri binary and
 * the real Python sidecar/SQLite-backed store, exactly like every other
 * existing spec.
 *
 * This spec's own app-data root is shared with every other spec file
 * within one wdio invocation (see wdio.conf.ts) -- it must therefore be
 * the FIRST spec to add a root for its own first-run assertions to be
 * meaningful. "first-run" sorts alphabetically before every other
 * existing spec file name (golden-path/history-undo/partial-result), so
 * this holds under the default glob-order execution; verified directly
 * in isolation regardless (see FA-017.5/FA-017.4's own established
 * discipline for this exact harness constraint).
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

function seedFixtureFolder(): string {
  const root = mkdtempSync(join(tmpdir(), "file-agent-e2e-first-run-"));
  writeFileSync(join(root, "invoice.pdf"), "demo pdf content -- invoice");
  return root;
}

describe("FA-017.6 first-run hero", () => {
  let fixtureRoot: string;

  before(async () => {
    fixtureRoot = seedFixtureFolder();
  });

  it("shows the first-run hero with the final title, explanation, workflow stages, and trust copy", async () => {
    const heading = await browser.$("#managed-roots-heading");
    await heading.waitForDisplayed({ timeout: 30000 });

    const title = await browser.$("p*=Organiza tus archivos sin perder el control");
    await title.waitForDisplayed({ timeout: 15000 });

    const bodyText = await browser.execute(() => document.body.innerText);
    expect(bodyText).toContain(
      "Elige una carpeta. FileAgent analizará los archivos y te mostrará los cambios antes de organizar.",
    );
    expect(bodyText).toContain("Elige una carpeta");
    expect(bodyText).toContain("Revisa los cambios");
    expect(bodyText).toContain("Organiza");
    expect(bodyText).toContain("Revisa antes de organizar");
    expect(bodyText).toContain("No reemplazamos archivos existentes");
    expect(bodyText).toContain("Puedes deshacer cambios");

    const cta = await browser.$("button=Elegir carpeta");
    await cta.waitForDisplayed({ timeout: 15000 });
  });

  it("workflow stages are not interactive", async () => {
    const stageButtons = await browser.$$("button=Elige una carpeta");
    expect(stageButtons).toHaveLength(0);
    const stageButtonsRevisa = await browser.$$("button=Revisa los cambios");
    expect(stageButtonsRevisa).toHaveLength(0);
  });

  it("choosing a folder makes the hero disappear and the root row appear, with Analizar remaining an explicit click", async () => {
    await browser.execute((path: string) => {
      (window as unknown as { __E2E_PICK_FOLDER_OVERRIDE__?: string }).__E2E_PICK_FOLDER_OVERRIDE__ =
        path;
    }, fixtureRoot);

    const cta = await browser.$("button=Elegir carpeta");
    await cta.click();

    const fixtureFolderName = fixtureRoot.split(/[\\/]/).pop()!;
    const analyzeButton = await browser.$(
      `//li[contains(., "${fixtureFolderName}")]//button[text()="Analizar"]`,
    );
    await analyzeButton.waitForDisplayed({ timeout: 15000 });

    // The hero is gone -- a root now exists.
    const heroTitle = await browser.$("p*=Organiza tus archivos sin perder el control");
    expect(await heroTitle.isExisting()).toBe(false);

    // No automatic mutation/navigation occurred just from adding a root
    // -- still on the Roots screen (not Plan/Results), and "Analizar"
    // remains a required, separate, explicit click (verified by the next
    // test still needing to click it to reach Plan).
    const rootsHeading = await browser.$("#managed-roots-heading");
    expect(await rootsHeading.isDisplayed()).toBe(true);
    const planHeadingNotYet = await browser.$("#plan-heading");
    expect(await planHeadingNotYet.isExisting()).toBe(false);
  });

  it("clicking Analizar reaches the Plan screen", async () => {
    const fixtureFolderName = fixtureRoot.split(/[\\/]/).pop()!;
    const analyzeButton = await browser.$(
      `//li[contains(., "${fixtureFolderName}")]//button[text()="Analizar"]`,
    );
    await analyzeButton.click();

    const planHeading = await browser.$("#plan-heading");
    await planHeading.waitForDisplayed({ timeout: 20000 });
  });
});

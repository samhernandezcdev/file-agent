/**
 * FA-017.5 Part 37: a real-binary E2E covering the redesigned compact
 * History list -> HistoryDetailScreen -> per-item Undo flow end to end.
 * No mocked FileAgent business logic anywhere -- the real compiled Tauri
 * binary and the real Python sidecar/SQLite-backed store, exactly like
 * golden-path.spec.ts/partial-result.spec.ts.
 *
 * Deliberately a separate, minimal spec file -- never an extension of
 * golden-path.spec.ts -- matching FA-017.4's own established discipline
 * for adding new E2E coverage.
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

function seedFixtureFolder(): string {
  const root = mkdtempSync(join(tmpdir(), "file-agent-e2e-history-undo-"));
  writeFileSync(join(root, "invoice.pdf"), "demo pdf content -- invoice");
  // Deliberately does NOT pre-create Documents/ -- the missing-folder
  // attention is what this spec's own "prepare" step needs to resolve
  // first, exactly like the golden path's own first conflict.
  return root;
}

describe("FA-017.5 History -> detail -> Undo", () => {
  let fixtureRoot: string;

  before(async () => {
    fixtureRoot = seedFixtureFolder();
  });

  it("organizes one file end to end", async () => {
    await browser.execute((path: string) => {
      (window as unknown as { __E2E_PICK_FOLDER_OVERRIDE__?: string }).__E2E_PICK_FOLDER_OVERRIDE__ =
        path;
    }, fixtureRoot);

    // This spec may run in the same shared, persistent app-data root as
    // other spec files within one wdio run -- the Roots screen renders
    // "Elegir una carpeta" only while the roots list is empty, and
    // "Agregar carpeta" once at least one root already exists, and
    // briefly renders neither while managed_roots.list is still loading.
    const managedRootsHeading = await browser.$("#managed-roots-heading");
    await managedRootsHeading.waitForDisplayed({ timeout: 30000 });
    await browser.waitUntil(
      async () =>
        (await browser.$("button=Agregar carpeta").then((el) => el.isExisting())) ||
        (await browser.$("button=Elegir una carpeta").then((el) => el.isExisting())),
      { timeout: 20000, timeoutMsg: "neither add-root affordance appeared" },
    );
    const addRootButton = (await browser.$("button=Agregar carpeta").then((el) => el.isExisting()))
      ? await browser.$("button=Agregar carpeta")
      : await browser.$("button=Elegir una carpeta");
    await addRootButton.click();

    const fixtureFolderName = fixtureRoot.split(/[\\/]/).pop()!;
    const analyzeButton = await browser.$(
      `//li[contains(., "${fixtureFolderName}")]//button[text()="Analizar"]`,
    );
    await analyzeButton.waitForDisplayed({ timeout: 15000 });
    await analyzeButton.click();

    const planHeading = await browser.$("#plan-heading");
    await planHeading.waitForDisplayed({ timeout: 20000 });

    const prepareButton = await browser.$("button=Preparar carpeta");
    await prepareButton.waitForDisplayed({ timeout: 15000 });
    await prepareButton.click();
    const documentsResult = await browser.$("strong*=Documents — Preparada");
    await documentsResult.waitForDisplayed({ timeout: 20000 });

    const reanalyzeButton = await browser.$("button=Analizar de nuevo");
    await reanalyzeButton.waitForDisplayed({ timeout: 15000 });
    await reanalyzeButton.click();

    const selectAll = await browser.$('[aria-label="Seleccionar todos los listos"]');
    await selectAll.waitForDisplayed({ timeout: 15000 });
    await selectAll.click();

    const organizeButton = await browser.$('button*=Organizar');
    await browser.waitUntil(async () => organizeButton.isEnabled(), { timeout: 5000 });
    await organizeButton.click();

    const resultsHeading = await browser.$("#apply-results-heading");
    await resultsHeading.waitForDisplayed({ timeout: 20000 });
  });

  it("shows a compact History card with no file rows or Deshacer affordance", async () => {
    const viewHistoryButton = await browser.$("button=Ver historial");
    await viewHistoryButton.click();

    const historyHeading = await browser.$("#history-heading");
    await historyHeading.waitForDisplayed({ timeout: 15000 });

    const listBodyText = await browser.execute(() => document.body.innerText);
    expect(listBodyText).not.toContain("invoice.pdf");
    const deshacerButtons = await browser.$$("button=Deshacer");
    expect(deshacerButtons).toHaveLength(0);

    const detailsButton = await browser.$("button=Ver detalles");
    await detailsButton.waitForDisplayed({ timeout: 15000 });
  });

  it("opens the detail screen and shows the organized file with its original fact", async () => {
    const detailsButton = await browser.$("button=Ver detalles");
    await detailsButton.click();

    const detailHeading = await browser.$("#history-detail-heading");
    await detailHeading.waitForDisplayed({ timeout: 15000 });

    const detailBodyText = await browser.execute(() => document.body.innerText);
    expect(detailBodyText).toContain("invoice.pdf");
    expect(detailBodyText).toContain("Organizado");
    expect(detailBodyText).toContain("→");
  });

  it("invokes Undo, confirms, and shows the successful result", async () => {
    const undoButton = await browser.$("button=Deshacer");
    await undoButton.waitForDisplayed({ timeout: 15000 });
    await undoButton.click();

    // `*=text` resolves to WebdriverIO's partial-LINK-text strategy
    // (anchor elements only) -- the AlertDialog title is not an anchor,
    // so this is tag-scoped instead (mirrors golden-path.spec.ts's own
    // established fix for the identical class of selector bug).
    const dialogTitle = await browser.$("h2*=¿Deshacer este cambio?");
    await dialogTitle.waitForDisplayed({ timeout: 15000 });

    const confirmButton = await browser.$("button=Sí, deshacer");
    await confirmButton.waitForDisplayed({ timeout: 15000 });
    await confirmButton.click();

    // The confirmation control disappears once the decision is made (the
    // AlertDialog closes on confirm) -- same assertion golden-path.spec.ts
    // already relies on.
    await confirmButton.waitForExist({ reverse: true, timeout: 15000 });

    const doneText = await browser.$("span*=Cambio deshecho");
    await doneText.waitForDisplayed({ timeout: 20000 });

    const noSuchButtons = await browser.$$("button=Deshacer");
    expect(noSuchButtons).toHaveLength(0);

    // The original historical fact remains -- Undo never rewrites the
    // past.
    const detailBodyText = await browser.execute(() => document.body.innerText);
    expect(detailBodyText).toContain("Organizado");
    expect(detailBodyText).toContain("invoice.pdf");
  });

  it("returns to History and reflects the recovery, without an app restart", async () => {
    const backLink = await browser.$("button=← Historial");
    await backLink.click();

    const historyHeading = await browser.$("#history-heading");
    await historyHeading.waitForDisplayed({ timeout: 15000 });

    const bodyText = await browser.execute(() => document.body.innerText);
    expect(bodyText).toContain("Cambios deshechos");

    // Reopen detail -- consistent, still no crash, still shows the
    // original fact plus the now-durable recovery state.
    const detailsButton = await browser.$("button=Ver detalles");
    await detailsButton.click();
    const detailHeading = await browser.$("#history-detail-heading");
    await detailHeading.waitForDisplayed({ timeout: 15000 });
    const detailBodyText = await browser.execute(() => document.body.innerText);
    expect(detailBodyText).toContain("Cambio deshecho");
    expect(detailBodyText).toContain("Organizado");
  });
});

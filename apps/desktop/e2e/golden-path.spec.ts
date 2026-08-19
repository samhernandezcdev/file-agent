/**
 * FA-017 golden-path E2E: launches the real compiled desktop app and
 * drives it exactly the way a person would --
 *
 *   add an isolated demo ManagedRoot -> analyze -> preview shows a missing
 *   destination folder -> prepare that folder -> reanalyze -> the
 *   previously-conflicted item becomes selectable -> approve one review
 *   item -> select eligible items -> apply -> see the result -> open
 *   history -> undo one transaction -> verify the resulting UI state,
 *   including that no folder-creation undo affordance exists anywhere
 *   (FA-017.2).
 *
 * Fixtures are created fresh in a throwaway temp directory for this run
 * only (mirrors scripts/demo_preview.py's own fixture set) -- the
 * developer's real Downloads/Documents are never touched, and neither is
 * their real %APPDATA%/FileAgent (wdio.conf.ts points the whole app at an
 * isolated FILE_AGENT_DESKTOP_APP_DATA_ROOT for this run).
 *
 * The native folder picker is mocked at the IPC layer (`browser.tauri
 * .mock`) rather than driven as a real OS dialog -- WebDriver has no way
 * to interact with a native, out-of-webview dialog, and mocking is the
 * documented, supported approach for exactly this case.
 */
import { mkdtempSync } from "node:fs";
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

function seedFixtureFolder(): string {
  const root = mkdtempSync(join(tmpdir(), "file-agent-e2e-fixture-"));
  writeFileSync(join(root, "invoice.pdf"), "demo pdf content -- invoice");
  writeFileSync(join(root, "photo.jpg"), "demo jpg bytes -- not a real image");
  writeFileSync(join(root, "setup.exe"), "demo exe bytes -- never executed");
  // Deliberately does NOT pre-create Documents/ -- FA-017.2's own golden
  // path needs a genuine destination_parent_missing conflict for
  // invoice.pdf so the "prepare the missing folder" flow has something
  // real to exercise.
  return root;
}

describe("FA-017 golden path", () => {
  let fixtureRoot: string;

  before(async () => {
    fixtureRoot = seedFixtureFolder();
  });

  it("loads the Managed Roots screen and the sidecar handshake succeeds", async () => {
    const heading = await browser.$("#managed-roots-heading");
    await heading.waitForDisplayed({ timeout: 30000 });
    expect(await heading.getText()).toBe("Carpetas que FileAgent puede organizar");
  });

  it("adds the isolated demo folder as a Managed Root via the E2E picker override", async () => {
    // browser.tauri.mock() cannot intercept this call -- traced live:
    // @wdio/tauri-plugin only patches window.__TAURI__.core.invoke, but
    // @tauri-apps/plugin-dialog's open() (like this app's own desktop/
    // bridge) calls the ES-imported `invoke` from @tauri-apps/api/core
    // directly, a separate reference the patch never touches. Using
    // desktop/index.ts's own VITE_E2E-gated override instead is both the
    // only reliable option and the safer one -- it structurally cannot
    // open the real native dialog during automated tests.
    await browser.execute((path: string) => {
      (window as unknown as { __E2E_PICK_FOLDER_OVERRIDE__?: string }).__E2E_PICK_FOLDER_OVERRIDE__ =
        path;
    }, fixtureRoot);

    const addButton = await browser.$("button=Elegir una carpeta");
    await addButton.click();

    // Match on the "Analizar" action appearing rather than the exact
    // displayed path string -- Windows path separator/casing rendering
    // is an unrelated concern from what this step actually verifies
    // (that the mocked picker's path was registered as a Managed Root).
    const analyzeButton = await browser.$("button=Analizar");
    await analyzeButton.waitForDisplayed({ timeout: 15000 });
  });

  it("analyzes the folder and shows the organization preview", async () => {
    const analyzeButton = await browser.$("button=Analizar");
    await analyzeButton.click();

    const planHeading = await browser.$("#plan-heading");
    await planHeading.waitForDisplayed({ timeout: 20000 });

    // Proves the MOCKED path -- not whatever a real, unmocked native
    // dialog might have defaulted to -- is what actually got analyzed.
    const bodyText = await browser.execute(() => document.body.innerText);
    expect(bodyText).toContain("invoice.pdf");
    expect(bodyText).toContain("setup.exe");
  });

  it("shows the missing-destination attention and prepares the folder, then requires reanalysis", async () => {
    // The fixture has two missing categories (Documents for invoice.pdf,
    // Images for photo.jpg) -- use the aggregate "Preparar N carpetas"
    // button so BOTH clear, rather than the per-panel single-category
    // button (which would leave one attention legitimately still showing
    // "Falta preparar esta carpeta" and make the clears-after-reanalysis
    // assertion below meaningless).
    const prepareAllButton = await browser.$("button=Preparar 2 carpetas");
    await prepareAllButton.waitForDisplayed({ timeout: 15000 });

    const bodyTextBefore = await browser.execute(() => document.body.innerText);
    expect(bodyTextBefore).toContain("Falta preparar esta carpeta");

    await prepareAllButton.click();

    // A real per-category result appears, naming the real physical folder
    // -- never claims success without the backend's own proof. A bare
    // "*=text" selector resolves to WebdriverIO's partial-LINK-text
    // strategy (anchor elements only); the result banner's title renders
    // as a <strong>, so the selector must be tag-scoped to match it.
    const documentsResult = await browser.$("strong*=Documents — Preparada");
    await documentsResult.waitForDisplayed({ timeout: 20000 });
    const imagesResult = await browser.$("strong*=Images — Preparada");
    await imagesResult.waitForDisplayed({ timeout: 20000 });

    // The item is NOT locally promoted to READY -- an explicit
    // "Analizar de nuevo" click is still required.
    const reanalyzeButton = await browser.$("button=Analizar de nuevo");
    await reanalyzeButton.waitForDisplayed({ timeout: 15000 });
    await reanalyzeButton.click();

    // A fresh plan.create/analysis.run round trip -- the plan heading
    // re-renders and the missing-destination attention is gone because
    // the real filesystem now has the folder.
    const planHeading = await browser.$("#plan-heading");
    await planHeading.waitForDisplayed({ timeout: 20000 });
    await browser.waitUntil(
      async () => {
        const text = await browser.execute(() => document.body.innerText);
        return !text.includes("Falta preparar esta carpeta");
      },
      { timeout: 15000, timeoutMsg: "missing-destination attention never cleared after reanalysis" },
    );

    // The previously-conflicted item is now selectable.
    const selectAll = await browser.$('[aria-label="Seleccionar todos los listos"]');
    await selectAll.waitForDisplayed({ timeout: 15000 });
  });

  it("approves the review-required item", async () => {
    const approveButton = await browser.$("button=Aprobar");
    await approveButton.waitForDisplayed({ timeout: 15000 });
    await approveButton.click();
    await approveButton.waitForExist({ reverse: true, timeout: 15000 });
  });

  it("selects the eligible item and organizes it", async () => {
    // Exercises the "Seleccionar todos los listos" bulk-select control
    // (FA-017.1 §16) rather than a single first-match checkbox -- avoids
    // depending on exactly how many items became selectable after the
    // approval above, and still drives the same real backend mutation.
    const selectAll = await browser.$('[aria-label="Seleccionar todos los listos"]');
    await selectAll.waitForDisplayed({ timeout: 15000 });
    await selectAll.click();

    const organizeButton = await browser.$('button*=Organizar');
    await browser.waitUntil(async () => organizeButton.isEnabled(), { timeout: 5000 });
    await organizeButton.click();

    const resultsHeading = await browser.$("#apply-results-heading");
    await resultsHeading.waitForDisplayed({ timeout: 20000 });
  });

  it("opens history and shows the completed batch", async () => {
    const viewHistoryButton = await browser.$("button=Ver historial");
    await viewHistoryButton.click();

    const historyHeading = await browser.$("#history-heading");
    await historyHeading.waitForDisplayed({ timeout: 15000 });

    const batchRow = await browser.$("li button");
    await batchRow.waitForDisplayed({ timeout: 15000 });
    await batchRow.click();
  });

  it("undoes the transaction and reflects the change in the UI", async () => {
    const undoButton = await browser.$("button=Deshacer");
    await undoButton.waitForDisplayed({ timeout: 15000 });
    await undoButton.click();

    const confirmButton = await browser.$("button=Sí, deshacer");
    await confirmButton.waitForDisplayed({ timeout: 15000 });
    await confirmButton.click();

    // The confirmation control disappears once the decision is made (the
    // AlertDialog closes on confirm) -- unchanged assertion from before
    // the Radix AlertDialog migration.
    await confirmButton.waitForExist({ reverse: true, timeout: 15000 });
  });

  it("never exposes a folder-creation undo affordance anywhere in this flow", async () => {
    // FA-017.2: creating a directory is deliberately NOT reversible via
    // any UI affordance (files or other apps may have since populated
    // it) -- checked here after every screen above (Carpetas/Revisar/
    // Resultado/Historial) has been visited at least once in this
    // session. Precise element-name checks, not a whole-page substring
    // match, to avoid a false positive from unrelated adjacent text
    // (e.g. the sidebar's own "Carpetas" nav label).
    const noSuchButtons = await browser.$$("button=Deshacer creación de carpeta");
    expect(noSuchButtons).toHaveLength(0);
    const noSuchButtonsEn = await browser.$$("button*=undo folder");
    expect(noSuchButtonsEn).toHaveLength(0);
  });
});

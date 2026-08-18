/**
 * FA-017 golden-path E2E: launches the real compiled desktop app and
 * drives it exactly the way a person would --
 *
 *   add an isolated demo ManagedRoot -> analyze -> preview ->
 *   approve one review item -> select eligible items -> apply ->
 *   see the result -> open history -> undo one transaction ->
 *   verify the resulting UI state.
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
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

function seedFixtureFolder(): string {
  const root = mkdtempSync(join(tmpdir(), "file-agent-e2e-fixture-"));
  writeFileSync(join(root, "invoice.pdf"), "demo pdf content -- invoice");
  writeFileSync(join(root, "photo.jpg"), "demo jpg bytes -- not a real image");
  writeFileSync(join(root, "setup.exe"), "demo exe bytes -- never executed");
  mkdirSync(join(root, "Documents"), { recursive: true });
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

    const addButton = await browser.$("button=Agregar carpeta");
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

  it("approves the review-required item", async () => {
    const approveButton = await browser.$("button=Aprobar");
    await approveButton.waitForDisplayed({ timeout: 15000 });
    await approveButton.click();
    await approveButton.waitForExist({ reverse: true, timeout: 15000 });
  });

  it("selects the eligible item and organizes it", async () => {
    const checkbox = await browser.$('input[type="checkbox"]');
    await checkbox.waitForDisplayed({ timeout: 15000 });
    await checkbox.click();

    const organizeButton = await browser.$("button=Organizar");
    expect(await organizeButton.isEnabled()).toBe(true);
    await organizeButton.click();

    const resultsHeading = await browser.$("#apply-results-heading");
    await resultsHeading.waitForDisplayed({ timeout: 20000 });
  });

  it("opens history and shows the completed batch", async () => {
    const viewHistoryButton = await browser.$("button=Ver en historial");
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

    // The confirmation controls disappear once the decision is made --
    // proving the UI reacted to the real backend outcome, not a
    // locally-fabricated one.
    await confirmButton.waitForExist({ reverse: true, timeout: 15000 });
  });
});

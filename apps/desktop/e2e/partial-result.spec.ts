/**
 * FA-017.4 §11 / Implementation Round 1 Part 25: a deterministic,
 * product-flow-only partial/none-applied apply result, exercised end to
 * end against the real compiled desktop app -- no test-only backend
 * behavior, no fixture-order fragility.
 *
 * The technique: seed a source file, prepare its destination folder
 * through the real product flow, reanalyze so it becomes READY, then --
 * BEFORE organizing -- place a real, conflicting file at the
 * already-prepared destination path with `fs.writeFileSync` (the same
 * class of primitive the golden path already uses for initial fixture
 * seeding, just applied mid-flow instead of only at setup). This
 * simulates a genuine external event (another process, or the user,
 * writing to the folder between analysis and apply). TransactionEngine's
 * own live destination-readiness re-check at apply time -- never cached
 * from the plan -- then genuinely, deterministically rejects the item
 * with destination_already_exists, exactly the same TOCTOU class already
 * covered at the unit level for `inspect_leaf`/`verify_source_identity`.
 *
 * Deliberately a separate, minimal spec file -- never an extension of
 * golden-path.spec.ts -- per FA-017.4 Design Round 2 §11's explicit
 * instruction, so this scenario can never destabilize the golden path's
 * own fixture or timing.
 */
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

function seedFixtureFolder(): string {
  const root = mkdtempSync(join(tmpdir(), "file-agent-e2e-partial-"));
  writeFileSync(join(root, "invoice.pdf"), "demo pdf content -- invoice");
  // Deliberately does NOT pre-create Documents/ -- the missing-folder
  // attention is what this spec's own "prepare" step needs to resolve
  // first, exactly like the golden path's own first conflict.
  return root;
}

describe("FA-017.4 deterministic partial apply result", () => {
  let fixtureRoot: string;

  before(async () => {
    fixtureRoot = seedFixtureFolder();
  });

  it("adds the isolated demo folder, analyzes it, and prepares the missing Documents folder", async () => {
    await browser.execute((path: string) => {
      (window as unknown as { __E2E_PICK_FOLDER_OVERRIDE__?: string }).__E2E_PICK_FOLDER_OVERRIDE__ =
        path;
    }, fixtureRoot);

    // This spec runs in a freshly (re)started app process -- wait for the
    // sidecar handshake/first managed_roots.list round trip to complete
    // (same generous timeout golden-path.spec.ts's own first test uses)
    // before polling for either add-root affordance below.
    const managedRootsHeading = await browser.$("#managed-roots-heading");
    await managedRootsHeading.waitForDisplayed({ timeout: 30000 });

    // This spec runs in the same shared, persistent app-data root as
    // golden-path.spec.ts within one wdio run (see wdio.conf.ts's single
    // FILE_AGENT_DESKTOP_APP_DATA_ROOT) -- the Roots screen renders
    // "Elegir carpeta" only while the roots list is empty, and
    // "Agregar carpeta" once at least one root already exists. Poll for
    // whichever add-root affordance appears first rather than checking
    // once, so this spec is correct regardless of run order or load
    // timing.
    await browser.waitUntil(
      async () =>
        (await browser.$("button=Agregar carpeta").then((el) => el.isExisting())) ||
        (await browser.$("button=Elegir carpeta").then((el) => el.isExisting())),
      { timeout: 20000, timeoutMsg: "neither add-root affordance appeared" },
    );
    const addRootButton = (await browser.$("button=Agregar carpeta").then((el) => el.isExisting()))
      ? await browser.$("button=Agregar carpeta")
      : await browser.$("button=Elegir carpeta");
    await addRootButton.click();

    // This spec's root is not necessarily the only one in the shared
    // store (golden-path.spec.ts's own root may already be listed) --
    // scope to the list item whose displayed path contains this spec's
    // own distinctive fixture-folder name (the mkdtemp-generated suffix
    // is a single path segment, unaffected by separator/casing
    // rendering) rather than assuming any particular list order.
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
  });

  it("reanalyzes so the file becomes READY, then a real conflicting file appears at the destination before organizing", async () => {
    const reanalyzeButton = await browser.$("button=Analizar de nuevo");
    await reanalyzeButton.waitForDisplayed({ timeout: 15000 });
    await reanalyzeButton.click();

    const selectAll = await browser.$('[aria-label="Seleccionar todos los listos"]');
    await selectAll.waitForDisplayed({ timeout: 15000 });

    // The real filesystem now has Documents/ (created by "Preparar
    // carpeta" above) -- place a genuine conflicting file there, mid-flow,
    // before the item is ever selected or organized. This is a real
    // external event, not a fixture-seeding trick: the plan the UI is
    // currently showing was computed before this write happened.
    mkdirSync(join(fixtureRoot, "Documents"), { recursive: true });
    writeFileSync(join(fixtureRoot, "Documents", "invoice.pdf"), "an unrelated, already-existing file");
  });

  it("organizing genuinely, deterministically rejects the item with the real destination-conflict reason", async () => {
    const selectAll = await browser.$('[aria-label="Seleccionar todos los listos"]');
    await selectAll.click();

    const organizeButton = await browser.$('button*=Organizar');
    await browser.waitUntil(async () => organizeButton.isEnabled(), { timeout: 5000 });
    await organizeButton.click();

    const resultsHeading = await browser.$("#apply-results-heading");
    await resultsHeading.waitForDisplayed({ timeout: 20000 });

    // Expand the per-item detail (starts collapsed) to reveal the real,
    // truthful reason -- never a bare/generic failure.
    const detailsToggle = await browser.$("button=Ver detalles");
    await detailsToggle.waitForDisplayed({ timeout: 15000 });
    await detailsToggle.click();

    const resultsBodyText = await browser.execute(() => document.body.innerText);
    expect(resultsBodyText).toContain("No se organizó");
    expect(resultsBodyText).toContain("Ya existe un archivo con ese nombre en la carpeta de destino.");
    expect(resultsBodyText).not.toContain("not_applied");
    expect(resultsBodyText).not.toMatch(/\bapplied\b/);

    // FA-017.4 Part 13/14: a partial/none-applied result promotes
    // "Analizar de nuevo" to the primary action (not "Ver historial").
    const reanalyzeButton = await browser.$("button=Analizar de nuevo");
    await reanalyzeButton.waitForDisplayed({ timeout: 15000 });
    await reanalyzeButton.click();

    // Direct same-root reanalysis -- back on this exact folder's context
    // (never the roots list). The freshly re-scanned folder now
    // genuinely has a real, already-existing file at invoice.pdf's
    // proposed destination (the conflicting file planted above) --
    // PolicyEngine truthfully re-classifies it as needing no further
    // action, so the plan screen's own NOTHING_ACTIONABLE state (not the
    // ordinary "#plan-heading" plan view) is the correct, honest
    // rendering here. Assert on the context strip (present on both plan
    // renderings) plus the truthful empty-state copy, rather than
    // assuming the ordinary plan heading -- this is a real, meaningful
    // end state, not a shortcut around it.
    const changeFolderLink = await browser.$("button=Cambiar carpeta");
    await changeFolderLink.waitForDisplayed({ timeout: 20000 });
    const bodyText = await browser.execute(() => document.body.innerText);
    expect(bodyText).toContain("No hay nada que organizar en este momento.");
  });
});

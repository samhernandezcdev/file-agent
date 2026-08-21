/**
 * FA-017.6 Part 41: a real-binary E2E proving the compact sticky context
 * bar and sticky action footer remain visible and functional while
 * scrolling a genuinely long Plan file list -- no mocked FileAgent
 * business logic, real fixture files, no test-only production behavior.
 * Deliberately a separate, minimal spec file (matches FA-017.4/FA-017.5's
 * own established "one scenario per file" discipline).
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const FILE_COUNT = 25;

function seedFixtureFolder(): string {
  const root = mkdtempSync(join(tmpdir(), "file-agent-e2e-long-plan-"));
  // All the same extension -- lands in exactly one destination category
  // (Documents), so only a single "Preparar carpeta" step is needed,
  // keeping this spec focused on scroll ergonomics rather than
  // multi-category destination setup (already covered elsewhere).
  for (let i = 0; i < FILE_COUNT; i += 1) {
    writeFileSync(join(root, `file-${String(i).padStart(2, "0")}.pdf`), `demo pdf content ${i}`);
  }
  return root;
}

describe("FA-017.6 long Plan scroll ergonomics", () => {
  let fixtureRoot: string;

  before(async () => {
    fixtureRoot = seedFixtureFolder();
  });

  it("prepares the single missing destination folder for all 25 files", async () => {
    await browser.execute((path: string) => {
      (window as unknown as { __E2E_PICK_FOLDER_OVERRIDE__?: string }).__E2E_PICK_FOLDER_OVERRIDE__ =
        path;
    }, fixtureRoot);

    const managedRootsHeading = await browser.$("#managed-roots-heading");
    await managedRootsHeading.waitForDisplayed({ timeout: 30000 });
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

  it("reanalyzes so all 25 files become READY", async () => {
    const reanalyzeButton = await browser.$("button=Analizar de nuevo");
    await reanalyzeButton.waitForDisplayed({ timeout: 15000 });
    await reanalyzeButton.click();

    const bodyText = await browser.waitUntil(
      async () => {
        const text = await browser.execute(() => document.body.innerText);
        return text.includes(`${FILE_COUNT} listos`) ? text : false;
      },
      { timeout: 20000, timeoutMsg: "compact context bar never showed all 25 as listos" },
    );
    expect(bodyText).toContain(`${FILE_COUNT} listos`);
  });

  it("selects all, scrolls deep into the list, and the sticky context/action surfaces remain visible", async () => {
    const selectAll = await browser.$('[aria-label="Seleccionar todos los listos"]');
    await selectAll.waitForDisplayed({ timeout: 15000 });
    await selectAll.click();

    const organizeButton = await browser.$(`button=Organizar ${FILE_COUNT} archivos`);
    await organizeButton.waitForDisplayed({ timeout: 15000 });

    // Scroll the real single scroll ancestor (`main`) all the way down --
    // proves there is exactly one intentional scroll container (no
    // nested overflow to scroll instead) and that the sticky surfaces
    // are still displayed after scrolling past the full AnalysisSummary
    // and the whole 25-row file list.
    await browser.execute(() => {
      const main = document.querySelector("main");
      if (main) main.scrollTop = main.scrollHeight;
    });

    const contextBar = await browser.$(`p*=${FILE_COUNT} listos`);
    expect(await contextBar.isDisplayed()).toBe(true);

    const organizeButtonAfterScroll = await browser.$(`button=Organizar ${FILE_COUNT} archivos`);
    expect(await organizeButtonAfterScroll.isDisplayed()).toBe(true);

    // Exactly one Organize control exists in the whole document.
    const allOrganizeButtons = await browser.$$(`button=Organizar ${FILE_COUNT} archivos`);
    expect(allOrganizeButtons).toHaveLength(1);
  });

  it("at the app's minimum window size, sticky header and footer stay non-overlapping and multiple rows stay visible", async () => {
    // The E2E harness launches at exactly src-tauri/tauri.conf.json's
    // configured width/height (960x600), which is ALSO that config's
    // minWidth/minHeight -- i.e. this run is already at the smallest
    // window the app permits. There is no smaller "short window" case
    // to additionally construct via browser.setWindowSize(): shrinking
    // below minHeight is not a state a real user can ever reach, so
    // asserting geometry at this already-minimum size *is* the
    // short-window case the design's §21/§42 asks for.
    const geometry = await browser.execute(() => {
      const rows = Array.from(
        document.querySelectorAll('[aria-label="Archivos analizados"] .min-h-11'),
      );
      const header = document.querySelector(".sticky.top-0");
      const footer = document.querySelector(".sticky.bottom-0");
      // DOMRect's top/bottom/etc. are prototype getters, not own
      // enumerable properties -- they do not survive the structured
      // clone back out of browser.execute, so copy them into a plain
      // object explicitly.
      const rect = (el: Element | null) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height };
      };
      const visibleRows = rows.filter((row) => {
        const r = row.getBoundingClientRect();
        return r.height > 0 && r.top >= 0 && r.bottom <= window.innerHeight;
      });
      return {
        windowHeight: window.innerHeight,
        header: rect(header),
        footer: rect(footer),
        visibleRowCount: visibleRows.length,
      };
    });

    expect(geometry.header).not.toBeNull();
    expect(geometry.footer).not.toBeNull();
    // Both sticky surfaces are within the viewport and do not overlap
    // each other (header's bottom edge sits above the footer's top edge).
    expect(geometry.header!.bottom).toBeLessThanOrEqual(geometry.footer!.top);
    // More than a trivial 2-3 rows remain viewable between them.
    expect(geometry.visibleRowCount).toBeGreaterThan(3);
  });

  it("organizes without scrolling back, reaching Results", async () => {
    const organizeButton = await browser.$(`button=Organizar ${FILE_COUNT} archivos`);
    await organizeButton.click();

    const resultsHeading = await browser.$("#apply-results-heading");
    await resultsHeading.waitForDisplayed({ timeout: 20000 });
  });
});

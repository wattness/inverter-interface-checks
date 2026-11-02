import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import path from "node:path";

const require = createRequire(process.env.SPACE_PLAYWRIGHT_PACKAGE ?? import.meta.url);
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../", import.meta.url));
const output = path.resolve(process.env.SPACE_TEST_OUTPUT ?? path.join(root, ".test-output"));
await mkdir(output, { recursive: true });
const manifest = JSON.parse(await readFile(path.join(root, "manifest.json"), "utf8"));
const original = await readFile(path.join(root, manifest.platforms[0].original.path));
const fixed = await readFile(path.join(root, manifest.platforms[0].fixed.path));
const allowed = new Set([
  "index.html", "style.css", "app.mjs", "report-core.mjs", "report-worker.mjs", "manifest.json", "README.md",
  ...manifest.platforms.flatMap((p) => [p.original.path, p.fixed.path]),
  manifest.checker.wheel.path, manifest.native_validation.path,
]);
const types = { ".html": "text/html", ".css": "text/css", ".mjs": "text/javascript", ".json": "application/json", ".md": "text/plain" };
const server = createServer(async (req, res) => {
  const name = new URL(req.url, "http://localhost").pathname.slice(1) || "index.html";
  if (!allowed.has(name) || !["GET", "HEAD"].includes(req.method)) { res.writeHead(404); res.end(); return; }
  try {
    const bytes = await readFile(path.join(root, name));
    res.writeHead(200, { "Content-Type": types[path.extname(name)] ?? "application/octet-stream", "Cache-Control": "no-store" });
    res.end(req.method === "HEAD" ? undefined : bytes);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise((resolve, reject) => { server.once("error", reject); server.listen(Number(process.env.SPACE_TEST_PORT ?? 0), "127.0.0.1", resolve); });
const address = "http://127.0.0.1:" + server.address().port;
const browser = await chromium.launch({
  headless: true,
  ...(process.env.SPACE_BROWSER_CHANNEL ? { channel: process.env.SPACE_BROWSER_CHANNEL } : {}),
  args: ["--use-mock-keychain", "--disable-background-networking"],
});
const results = [];
let currentPage;
async function check(name, callback) {
  try { await callback(); results.push({ name, ok: true }); console.log("PASS " + name); }
  catch (error) { results.push({ name, ok: false, error: error.message }); throw error; }
}
async function visible(page, selector) {
  await page.locator(selector).waitFor({ state: "visible", timeout: 8000 });
}
async function openReport(page, bytes, name = "report.json") {
  await page.getByRole("tab", { name: "Your report" }).click();
  await page.locator("#report-file").setInputFiles({ name, mimeType: "application/json", buffer: bytes });
}
async function errorReport(page, bytes, pattern, name = "report.json") {
  await openReport(page, bytes, name);
  await visible(page, "#report-error");
  assert.match(await page.locator("#report-error").innerText(), pattern);
  assert.equal(await page.locator("#report-content").isVisible(), false);
}
async function pasteReport(page, bytes) {
  const input = page.locator("#report-text");
  const text = bytes.toString("utf8");
  try { await input.fill(text, { timeout: 5000 }); }
  catch (error) {
    // Touch Chromium can time out after inserting the complete textarea value.
    if (error.name !== "TimeoutError" || await input.inputValue() !== text) throw error;
  }
  assert.equal(await input.inputValue(), text);
  await page.locator("#inspect-text").click();
  await visible(page, "#report-content");
  assert.match(await page.locator("#report-outcome").innerText(), /Reported pass/);
  assert.equal(await page.locator("#report-table tbody tr").count(), 24);
}
try {
  for (const theme of ["light", "dark"]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: theme, acceptDownloads: true });
    const page = await context.newPage();
    currentPage = page;
    const errors = [];
    const requests = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => requests.push({ url: request.url(), method: request.method() }));
    await page.goto(address);
    await visible(page, "#comparison-content");
    await check(theme + ": source-backed default comparison", async () => {
      assert.equal(await page.locator("#changed-count").innerText(), "3");
      assert.equal(await page.locator("#unchanged-count").innerText(), "21");
      assert.equal(await page.locator("#case-count").innerText(), "24");
      assert.equal(await page.locator("#comparison-table tbody tr").count(), 3);
      assert.match(await page.locator("#original-source").getAttribute("href"), /5e2396cef/);
      assert.match(await page.locator("#fixed-source").getAttribute("href"), /0489b0f2/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    });
    await page.screenshot({ path: path.join(output, "desktop-" + theme + ".png"), fullPage: true });
    await check(theme + ": platform changes and all control cases", async () => {
      for (const platform of manifest.platforms) {
        await page.locator("#platform").selectOption(platform.id);
        await visible(page, "#comparison-content");
        assert.equal(await page.locator("#changed-count").innerText(), "3");
        await page.locator("#case-filter").selectOption("all");
        assert.equal(await page.locator("#comparison-table tbody tr").count(), 24);
        await page.locator("#case-filter").selectOption("unchanged");
        assert.equal(await page.locator("#comparison-table tbody tr").count(), 21);
      }
      await page.locator("#platform").selectOption("linux-x64");
      await visible(page, "#comparison-content");
      await page.locator("#case-filter").selectOption("changed");
      await page.locator("#comparison-table .case-button").first().click();
      await visible(page, "#comparison-detail");
      assert.match(await page.locator("#comparison-detail").innerText(), /Same-instance valid recheck/);
      assert.match(await page.locator("#comparison-detail").innerText(), /LastErrorMessage/);
    });
    await page.screenshot({ path: path.join(output, "case-detail-" + theme + ".png"), fullPage: true });
    await check(theme + ": original download is byte-identical", async () => {
      const downloading = page.waitForEvent("download");
      await page.locator("#download-original").click();
      const download = await downloading;
      const bytes = await readFile(await download.path());
      assert.equal(createHash("sha256").update(bytes).digest("hex"), manifest.platforms[0].original.sha256);
    });
    await check(theme + ": local report, exact download and no outbound data", async () => {
      const start = requests.length;
      await openReport(page, fixed);
      await visible(page, "#report-content");
      assert.match(await page.locator("#report-outcome").innerText(), /Reported pass/);
      assert.equal(await page.locator("#report-table tbody tr").count(), 24);
      assert.equal(requests.slice(start).some((r) => r.method !== "GET" || !r.url.startsWith(address)), false);
      assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
      assert.equal(await page.evaluate(() => document.cookie), "");
      const downloading = page.waitForEvent("download");
      await page.locator("#download-user").click();
      assert.deepEqual(await readFile(await (await downloading).path()), fixed);
    });
    await page.screenshot({ path: path.join(output, "local-report-" + theme + ".png"), fullPage: true });
    await check(theme + ": original failures stay failures", async () => {
      await openReport(page, original);
      await visible(page, "#report-content");
      assert.match(await page.locator("#report-outcome").innerText(), /Reported failures/);
      assert.match(await page.locator("#report-metrics").innerText(), /3/);
      await page.locator("#report-table .case-button").nth(5).click();
      assert.match(await page.locator("#report-detail").innerText(), /Return code/);
    });
    await check(theme + ": invalid input clears a prior pass", async () => {
      await errorReport(page, Buffer.from('{"ok":true}'), /report\/2/);
      await errorReport(page, Buffer.from('{"schema":"x","schema":"y"}'), /Duplicate/);
      await errorReport(page, Buffer.from("[".repeat(65) + "0" + "]".repeat(65)), /nesting/);
      await errorReport(page, Buffer.from('{"value":1e400}'), /Nonfinite/);
      await errorReport(page, Buffer.alloc(2 * 1024 * 1024 + 1, 32), /2 MB/);
      await errorReport(page, Buffer.from([0xff, 0xfe, 0x80]), /encoded|decode|encoding/i);
      await errorReport(page, Buffer.from("MZ"), /JSON report/, "model.dll");
    });
    await check(theme + ": report and filename text cannot execute HTML", async () => {
      const fake = JSON.parse(fixed);
      fake.metadata.metadata.ModelName = '<img src="https://example.invalid/trace" onerror="window.reportXss=1">';
      fake.cases[0].case.id = "defaults";
      const start = requests.length;
      await openReport(page, Buffer.from(JSON.stringify(fake)), "<svg onload=window.reportXss=1>.json");
      await visible(page, "#report-content");
      await page.locator("#pane-report .metadata-block summary").click();
      assert.equal(await page.locator("#pane-report img, #pane-report svg, #pane-report iframe").count(), 0);
      assert.equal(await page.evaluate(() => window.reportXss), undefined);
      assert.match(await page.locator("#report-name").innerText(), /<svg/);
      assert.equal(requests.slice(start).some((r) => r.method !== "GET" || !r.url.startsWith(address)), false);
    });
    await check(theme + ": keyboard tabs and install guidance", async () => {
      await page.getByRole("tab", { name: "Your report" }).focus();
      await page.keyboard.press("ArrowRight");
      assert.equal(await page.getByRole("tab", { name: "Run locally" }).getAttribute("aria-selected"), "true");
      assert.match(await page.locator("#local-commands").innerText(), /python3.12/);
      await page.locator("#command-platform").selectOption("windows");
      assert.match(await page.locator("#local-commands").innerText(), /py -3.12/);
      assert.match(await page.locator("#local-commands").innerText(), /GFM_Battery_OpenIBR.dll/);
      assert.equal(await page.locator("#wheel-hash").innerText(), manifest.checker.wheel.sha256);
      const downloading = page.waitForEvent("download");
      await page.locator("#download-wheel").click();
      const bytes = await readFile(await (await downloading).path());
      assert.equal(createHash("sha256").update(bytes).digest("hex"), manifest.checker.wheel.sha256);
      await page.keyboard.press("Home");
      await page.getByRole("tab", { name: "Release comparison" }).click();
      assert.equal(await page.locator("#pane-comparison").isVisible(), true);
    });
    await check(theme + ": no console faults or third-party page requests", async () => {
      assert.deepEqual(errors, []);
      assert.equal(requests.some((r) => !r.url.startsWith(address)), false);
    });
    await context.close();
  }
  for (const width of [390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 844 }, colorScheme: "light", isMobile: true, hasTouch: true });
    const page = await context.newPage();
    currentPage = page;
    await page.goto(address);
    await visible(page, "#comparison-content");
    await check("mobile " + width + ": controls and layout", async () => {
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.equal(await page.locator("#comparison-table tbody tr").count(), 3);
      await page.locator("#comparison-table .case-button").first().click();
      assert.equal(await page.locator("#comparison-detail").isVisible(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.getByRole("tab", { name: "Your report" }).click();
      await page.locator(".paste-block summary").click();
      await pasteReport(page, fixed);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.getByRole("tab", { name: "Run locally" }).click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    });
    await page.getByRole("tab", { name: "Release comparison" }).click();
    await page.locator("#comparison-detail .button").click();
    await page.screenshot({ path: path.join(output, "mobile-" + width + ".png"), fullPage: true });
    await context.close();
  }
  const context = await browser.newContext({ viewport: { width: 1100, height: 900 } });
  const page = await context.newPage();
  currentPage = page;
  await page.route("**/reports/linux-x64-original.json", async (route) => {
    await route.fulfill({ contentType: "application/json", body: original.toString("utf8").replace('"schema"', '"schemx"') });
  });
  await page.goto(address);
  await check("tampered release evidence cannot display a comparison", async () => {
    await visible(page, "#comparison-error");
    assert.match(await page.locator("#comparison-error").innerText(), /SHA-256/);
    assert.equal(await page.locator("#comparison-content").isVisible(), false);
  });
  await context.close();
} catch (error) {
  if (currentPage && !currentPage.isClosed()) await currentPage.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  console.error(error);
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, "browser-results.json"), JSON.stringify({ ok: results.every((r) => r.ok), results }, null, 2) + "\n");
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}

const assert = require("node:assert/strict");
const { execFileSync, spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..", "..");
const python = process.env.PYTHON_EXE || path.join(root, ".venv", "Scripts", "python.exe");
const browserPath = process.env.PLAYWRIGHT_BROWSER_PATH
  || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const port = 9127;
const baseURL = `http://127.0.0.1:${port}`;
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "preventivi-playwright-"));
const dataPath = path.join(tempRoot, "data.json");
const env = { ...process.env, SQLITE_DB_PATH: path.join(tempRoot, "e2e.sqlite3") };
let server;
let browser;
let fixtures;
let serverLogs = "";

function pythonRun(args) {
  execFileSync(python, args, { cwd: root, env, stdio: "inherit" });
}

async function waitForServer() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (server.exitCode !== null) {
      throw new Error(`Il server Django si e arrestato (codice ${server.exitCode}).\n${serverLogs}`);
    }
    try {
      const response = await fetch(`${baseURL}/accesso/`);
      if (response.ok) return;
    } catch (_) {
      // Il server non e ancora pronto.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Il server Django Playwright non si e avviato in tempo.\n${serverLogs}`);
}

async function authenticatedPage() {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  const failedRequests = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));
  await page.goto(`${baseURL}/accesso/`);
  await page.getByLabel("Nome utente").fill(fixtures.username);
  await page.getByLabel("Password").fill(fixtures.password);
  await page.getByRole("button", { name: "Entra" }).click();
  await page.waitForURL(`${baseURL}/`);
  return { context, page, runtimeErrors, failedRequests };
}

async function runTest(name, callback) {
  const session = await authenticatedPage();
  try {
    await callback(session.page);
    assert.deepEqual(session.runtimeErrors, [], `Errori runtime: ${session.runtimeErrors.join(" | ")}`);
    assert.deepEqual(session.failedRequests, [], `Richieste fallite: ${session.failedRequests.join(" | ")}`);
    process.stdout.write(`PASS ${name}\n`);
  } finally {
    await session.context.close();
  }
}

async function main() {
  pythonRun(["manage.py", "migrate", "--noinput", "--verbosity", "0"]);
  pythonRun(["manage.py", "seed_initial_data", "--verbosity", "0"]);
  pythonRun([path.join("tests", "playwright", "prepare_data.py"), dataPath]);
  fixtures = JSON.parse(fs.readFileSync(dataPath, "utf8"));

  server = spawn(
    python,
    ["manage.py", "runserver", `127.0.0.1:${port}`, "--noreload"],
    { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] },
  );
  server.stdout.on("data", (chunk) => { serverLogs += chunk.toString(); });
  server.stderr.on("data", (chunk) => { serverLogs += chunk.toString(); });
  await waitForServer();
  browser = await chromium.launch({ headless: true, executablePath: browserPath });

  await runTest("quantita non valida visibile dopo risposta HTMX 422", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/articoli/`);
    await page.getByRole("button", { name: "Aggiungi articolo" }).click();
    const form = page.locator('form[action$="/articoli/aggiungi/"]');
    await form.locator('input[name="code"]').fill("PW-ERR");
    await form.locator('input[name="quantity"]').fill("0");
    await form.locator('select[name="material"]').selectOption({ index: 1 });
    await form.locator('input[name="weight_kg"]').fill("1.500");
    await form.evaluate((element) => { element.noValidate = true; });
    const responsePromise = page.waitForResponse(
      (response) => response.url().endsWith("/articoli/aggiungi/") && response.status() === 422,
    );
    await form.getByRole("button", { name: "Salva articolo" }).click();
    await responsePromise;
    await page.locator(".field.has-error").filter({ hasText: "Quantità" }).waitFor();
    assert.match(await page.locator(".messages").innerText(), /Articolo non aggiunto/i);
    assert.equal(await form.locator('input[name="quantity"]').getAttribute("min"), "1");
  });

  await runTest("articolo completo, doppio clic, persistenza, duplicazione ed eliminazione", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/articoli/`);
    const add = page.getByRole("button", { name: "Aggiungi articolo" });
    await add.evaluate((button) => { button.click(); button.click(); });
    assert.equal(await page.locator("[data-new-article]").count(), 1, "Il doppio clic deve creare una sola bozza.");

    const form = page.locator("[data-new-article] form");
    await form.locator('input[name="code"]').fill("PW-COMPLETO");
    await form.locator('input[name="quantity"]').fill("3");
    await form.locator('input[name="description"]').fill("Descrizione tecnica molto lunga per verificare il comportamento responsive senza troncamenti");
    await form.locator('select[name="material"]').selectOption({ index: 1 });
    await form.locator('input[name="weight_kg"]').fill("2.750");
    await form.getByRole("button", { name: "Salva articolo" }).click();
    await page.getByText(/PW-COMPLETO aggiunto/i).waitFor();
    assert.equal(await page.getByText("PW-COMPLETO", { exact: true }).count(), 1);

    await page.reload();
    const article = page.locator("details[data-article-card]").filter({ hasText: "PW-COMPLETO" });
    await article.locator(":scope > summary").click();
    assert.equal(await article.locator('input[name$="-quantity"]').inputValue(), "3");
    assert.match(await article.innerText(), /2,750 kg/);

    page.once("dialog", (dialog) => dialog.accept());
    await article.getByRole("button", { name: "Duplica" }).click();
    await page.getByText("PW-COMPLETO-COPIA", { exact: true }).waitFor();
    const copy = page.locator("details[data-article-card]").filter({ hasText: "PW-COMPLETO-COPIA" });
    await copy.locator(":scope > summary").click();
    page.once("dialog", (dialog) => dialog.accept());
    await copy.getByRole("button", { name: "Elimina articolo" }).click();
    await page.getByText(/PW-COMPLETO-COPIA rimosso/i).waitFor();
    assert.equal(await page.getByText("PW-COMPLETO-COPIA", { exact: true }).count(), 0);

    await article.locator(":scope > summary").click();
    page.once("dialog", (dialog) => dialog.accept());
    await article.getByRole("button", { name: "Elimina articolo" }).click();
    await page.getByText(/PW-COMPLETO rimosso/i).waitFor();
  });

  await runTest("operatori zero produce un messaggio comprensibile", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/lavorazioni/`);
    const activePhase = page.locator("details.phase-card.active").first();
    const addPanel = activePhase.locator("details.add-panel");
    await addPanel.evaluate((element) => { element.open = true; });
    const form = addPanel.locator("form");
    const resource = form.locator('select[name$="-resource"]');
    if (await resource.count()) await resource.selectOption({ index: 1 });
    await form.locator('input[name$="-working_minutes"]').fill("10");
    await form.locator('input[name$="-setup_minutes"]').fill("0");
    await form.locator('input[name$="-operators_snapshot"]').fill("0");
    await form.evaluate((element) => { element.noValidate = true; });
    await form.getByRole("button", { name: "Aggiungi operazione" }).click();
    await page.locator(".message.error").waitFor();
    assert.match(await page.locator(".message.error").innerText(), /Operatori.*maggiore o uguale a 1/i);
  });

  await runTest("rimozione pericolosa richiede conferma contestuale", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/lavorazioni/`);
    const row = page.locator("details.phase-card.active tbody tr").first();
    const dialogText = new Promise((resolve) => page.once("dialog", async (dialog) => {
      const message = dialog.message();
      await dialog.dismiss();
      resolve(message);
    }));
    await row.getByRole("button", { name: "Rimuovi" }).click();
    assert.match(await dialogText, /Saldatura/i);
    await page.waitForTimeout(100);
    assert.equal(await row.count(), 1, "L'operazione non deve essere eliminata dopo Annulla.");
  });

  await runTest("preventivo archiviato e realmente in sola lettura", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.archived_quote}/dati/`);
    assert.match(await page.locator(".alert.warning").innerText(), /sola lettura/i);
    assert.equal(await page.getByRole("button", { name: "Salva e continua" }).count(), 0);
    assert.equal(await page.locator("fieldset[disabled]").count(), 1);

    const result = await page.evaluate(async ({ quoteId }) => {
      const token = document.querySelector('[name="csrfmiddlewaretoken"]').value;
      const body = new URLSearchParams({
        csrfmiddlewaretoken: token,
        feasibility: "internal",
        offered_price: "999",
      });
      const response = await fetch(`/preventivi/${quoteId}/riepilogo/`, {
        method: "POST",
        headers: { "X-CSRFToken": token },
        body,
      });
      return { status: response.status, text: await response.text() };
    }, { quoteId: fixtures.archived_quote });
    assert.equal(result.status, 200);
    assert.match(result.text, /non puo essere modificato/i);
    assert.match(result.text, /EUR 100[,.]00/i);
  });

  await runTest("costo orario zero blocca il completamento", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.zero_cost_quote}/riepilogo/`);
    assert.match(await page.locator(".alert.error").innerText(), /costo orario/i);
    assert.equal(await page.getByRole("button", { name: "Segna come completato" }).isDisabled(), true);
  });

  await runTest("selezione e deselezione di una lavorazione", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/lavorazioni/`);
    const inactive = page.locator("details.phase-card.inactive").first();
    const phaseId = await inactive.getAttribute("id");
    await inactive.locator(":scope > summary").click();
    await inactive.getByLabel("Sì, attiva").check();
    await inactive.getByRole("button", { name: "Salva fase" }).click();
    const active = page.locator(`#${phaseId}.phase-card.active`);
    await active.waitFor();
    assert.equal(await active.getByLabel("Sì, attiva").isChecked(), true);

    await active.getByLabel("No, non attiva").check();
    await active.getByRole("button", { name: "Salva fase" }).click();
    const restored = page.locator(`#${phaseId}.phase-card.inactive`);
    await restored.waitFor();
    assert.equal(await restored.getAttribute("open"), null);
  });

  await runTest("navigazione da tastiera, focus visibile e label collegate", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/articoli/`);
    for (let index = 0; index < 6; index += 1) await page.keyboard.press("Tab");
    const focus = await page.evaluate(() => {
      const active = document.activeElement;
      const style = getComputedStyle(active);
      const missingLabels = Array.from(document.querySelectorAll("input:not([type=hidden]), select, textarea"))
        .filter((control) => control.offsetParent !== null && !control.labels?.length)
        .map((control) => control.name);
      return { tag: active.tagName, outline: style.outlineStyle, missingLabels };
    });
    assert.notEqual(focus.tag, "BODY");
    assert.notEqual(focus.outline, "none");
    assert.deepEqual(focus.missingLabels, []);
  });

  await runTest("fasi inattive compatte e apribili anche su schermo piccolo", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/lavorazioni/`);
    assert.equal(await page.locator("details.phase-card").count(), 22);
    assert.equal(await page.locator("details.phase-card[open]").count(), 1);
    assert.equal(await page.locator("details.phase-card:not([open])").count(), 21);
    const firstInactive = page.locator("details.phase-card.inactive").first();
    await firstInactive.locator(":scope > summary").click();
    assert.equal(await firstInactive.getAttribute("open"), "");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    assert.equal(await page.locator("details.phase-card:not([open])").count(), 21);
  });
}

main()
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  })
  .finally(async () => {
    if (browser) await browser.close();
    if (server) server.kill();
    fs.rmSync(tempRoot, { recursive: true, force: true });
  });

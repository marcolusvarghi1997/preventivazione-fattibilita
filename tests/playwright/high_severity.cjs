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
const visualAuditDir = process.env.VISUAL_AUDIT_DIR || "";
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

async function authenticatedPage(credentials = fixtures) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  const failedRequests = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));
  await page.goto(`${baseURL}/accesso/`);
  await page.getByLabel("Nome utente").fill(credentials.username);
  await page.getByLabel("Password").fill(credentials.password);
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

async function runAdminTest(name, callback) {
  const session = await authenticatedPage({ username: fixtures.admin_username, password: fixtures.password });
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
  if (visualAuditDir) fs.mkdirSync(visualAuditDir, { recursive: true });
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

  await runTest("cliente selezionabile con click e referente filtrato", async (page) => {
    await page.goto(`${baseURL}/preventivi/nuovo/`);
    const search = page.getByRole("combobox", { name: "Cliente" });
    await search.click();
    const list = page.locator("[data-client-results]");
    const scrollSizes = await list.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    }));
    assert.ok(scrollSizes.scrollHeight > scrollSizes.clientHeight, "L’elenco completo deve poter scorrere.");
    await search.fill("amministrazione@playwright.example");
    const result = page.locator("[data-client-result]").filter({ hasText: fixtures.client_name });
    await result.waitFor();
    assert.equal(await page.locator("[data-client-result]").count(), 1, "La ricerca deve mostrare solo i clienti corrispondenti.");
    assert.equal(await search.getAttribute("aria-expanded"), "true");
    await result.click();
    assert.equal(await search.inputValue(), fixtures.client_name);
    assert.notEqual(await page.locator("[data-client-id]").inputValue(), "");
    assert.equal(await page.locator("[data-contact-name]").inputValue(), fixtures.contact_name);
    assert.equal(await page.locator("[data-contact-email]").inputValue(), fixtures.contact_email);
    assert.match(await page.locator("[data-contact-state]").innerText(), /Referente Unico/);
    assert.equal(await page.getByRole("option", { name: /Referente Unico/ }).count(), 1);
    assert.equal(await page.getByText("Inserimento libero").count(), 0);

    const heights = await page.locator("#id_date, [data-client-search], [data-open-client-dialog], [data-contact-select], [data-open-contact-dialog]")
      .evaluateAll((elements) => elements.map((element) => Math.round(element.getBoundingClientRect().height)));
    assert.equal(new Set(heights).size, 1, `Altezze controlli non uniformi: ${heights.join(", ")}`);
    const cardWidth = await page.locator("[data-client-general]").evaluate((element) => element.getBoundingClientRect().width);
    assert.ok(cardWidth <= 1040, `Il modulo è ancora troppo largo: ${cardWidth}px`);
  });

  await runTest("fattibilita segmentata, compatta e adattata alla pagina", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/articoli/`);
    const selector = page.locator("details[data-article-card]").first().locator(".field-feasibility");
    const labels = selector.locator("label");
    assert.equal(await labels.count(), 3);
    const geometry = await labels.evaluateAll((elements) => elements.map((element) => {
      const box = element.getBoundingClientRect();
      return {
        x: Math.round(box.x),
        y: Math.round(box.y),
        color: getComputedStyle(element).backgroundColor,
        value: element.querySelector("input").value,
      };
    }));
    assert.deepEqual(geometry.map((entry) => entry.value), ["internal", "to_check", "not_feasible"]);
    assert.equal(new Set(geometry.map((entry) => entry.y)).size, 1, "Nella pagina Articoli i segmenti devono essere in riga.");
    assert.ok(geometry[0].x < geometry[1].x && geometry[1].x < geometry[2].x);
    assert.equal(new Set(geometry.map((entry) => entry.color)).size, 3, "Le tre fattibilità devono avere colori distinti.");
    assert.ok(await selector.evaluate((element) => element.getBoundingClientRect().width <= 570));
    assert.equal(await selector.locator('input[type="radio"]').first().evaluate((element) => element.getBoundingClientRect().width <= 1), true);
    const articleTrack = selector.locator("ul, div[id]").first();
    const articleInitialTransform = await articleTrack.evaluate((element) => getComputedStyle(element, "::before").transform);
    const articleCurrentIndex = await labels.evaluateAll((elements) => elements.findIndex((element) => element.querySelector("input").checked));
    await labels.nth((articleCurrentIndex + 1) % 3).click();
    assert.match(
      await articleTrack.evaluate((element) => getComputedStyle(element, "::before").transitionProperty),
      /transform/,
    );
    await page.waitForTimeout(280);
    assert.notEqual(
      await articleTrack.evaluate((element) => getComputedStyle(element, "::before").transform),
      articleInitialTransform,
      "Nella pagina Articoli l’indicatore deve scorrere orizzontalmente.",
    );

    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/riepilogo/`);
    const summarySelector = page.locator(".summary-card .field-feasibility");
    const summaryLabels = summarySelector.locator("label");
    const summaryGeometry = await summaryLabels.evaluateAll((elements) => elements.map((element) => {
      const box = element.getBoundingClientRect();
      return { x: Math.round(box.x), y: Math.round(box.y) };
    }));
    assert.equal(new Set(summaryGeometry.map((entry) => entry.x)).size, 1, "Nel riepilogo i segmenti devono essere in colonna.");
    assert.ok(summaryGeometry[0].y < summaryGeometry[1].y && summaryGeometry[1].y < summaryGeometry[2].y);
    assert.ok(await summarySelector.evaluate((element) => element.getBoundingClientRect().width <= 250));
    const summaryTrack = summarySelector.locator("ul, div[id]").first();
    const summaryInitialTransform = await summaryTrack.evaluate((element) => getComputedStyle(element, "::before").transform);
    const summaryCurrentIndex = await summaryLabels.evaluateAll((elements) => elements.findIndex((element) => element.querySelector("input").checked));
    await summaryLabels.nth((summaryCurrentIndex + 1) % 3).click();
    await page.waitForTimeout(280);
    assert.notEqual(
      await summaryTrack.evaluate((element) => getComputedStyle(element, "::before").transform),
      summaryInitialTransform,
      "Nel riepilogo l’indicatore deve scorrere verticalmente.",
    );
  });

  await runTest("nuovo referente associato al cliente selezionato", async (page) => {
    await page.goto(`${baseURL}/preventivi/nuovo/`);
    const search = page.getByRole("combobox", { name: "Cliente" });
    await search.fill("Altro Cliente");
    await page.locator("[data-client-result]").filter({ hasText: "Altro Cliente" }).click();
    const select = page.locator("[data-contact-select]");
    assert.equal(await select.locator("option").count(), 1);
    assert.match(await page.locator("[data-contact-state]").innerText(), /Nessun referente registrato/i);

    await page.getByRole("button", { name: "Nuovo referente" }).click();
    const dialog = page.locator("[data-contact-dialog]");
    await dialog.getByLabel("Nome referente").fill("Referente Altro");
    await dialog.getByLabel("Email").fill("referente.altro@example.com");
    await dialog.getByLabel("Telefono").fill("011 123456");
    await dialog.getByRole("button", { name: "Registra e seleziona" }).click();
    await dialog.waitFor({ state: "hidden" });
    assert.equal(await page.locator("[data-contact-name]").inputValue(), "Referente Altro");
    assert.equal(await select.locator("option", { hasText: "Referente Altro" }).count(), 1);
  });

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
    await form.locator('[name="description"]').fill("Descrizione tecnica molto lunga per verificare il comportamento responsive senza troncamenti");
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
    const materialAlignment = await article.locator(".material-table tbody tr").first().evaluate((row) => {
      const rowBox = row.getBoundingClientRect();
      const buttonBox = row.querySelector(".row-actions").getBoundingClientRect();
      return {
        rowCenter: rowBox.top + rowBox.height / 2,
        actionsCenter: buttonBox.top + buttonBox.height / 2,
      };
    });
    assert.ok(Math.abs(materialAlignment.rowCenter - materialAlignment.actionsCenter) <= 2, "I pulsanti materiale devono essere centrati verticalmente.");

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
    assert.match(result.text, /€ 100,00/i);
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
    await inactive.getByLabel(/^Attiva /).check();
    const active = page.locator(`#${phaseId}.phase-card.active`);
    await active.waitFor();
    assert.equal(await active.getByLabel(/^Attiva /).isChecked(), true);

    await active.getByLabel(/^Attiva /).uncheck();
    const restored = page.locator(`#${phaseId}.phase-card.inactive`);
    await restored.waitFor();
    assert.equal(await restored.getAttribute("open"), null);
  });

  await runTest("costo condizionale stabile, con virgola e valore persistente", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/articoli/`);
    const article = page.locator("details[data-article-card]").first();
    if ((await article.getAttribute("open")) === null) await article.locator(":scope > summary").click();
    const extras = article.locator("details.article-extras");
    await extras.locator(":scope > summary").click();
    const toggle = article.locator("[data-extra-toggle]").first();
    const cost = article.locator("[data-extra-cost]").first();
    const wrapper = cost.locator("xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' conditional-field ')][1]");
    const heightBefore = (await wrapper.boundingBox()).height;
    assert.equal(await cost.isDisabled(), true);
    await toggle.check();
    const heightAfter = (await wrapper.boundingBox()).height;
    assert.ok(Math.abs(heightBefore - heightAfter) <= 2, `Altezza cambiata: ${heightBefore} -> ${heightAfter}`);
    assert.equal(await cost.isEnabled(), true);
    assert.equal(await cost.evaluate((element) => element === document.activeElement), true);
    await cost.fill("46,20");
    await cost.press("Tab");
    assert.equal(await cost.inputValue(), "46,20");
    await article.getByRole("button", { name: "Salva modifiche articolo" }).click();
    await page.getByText(/Articolo aggiornato/i).waitFor();
    const updatedArticle = page.locator("details[data-article-card]").first();
    if ((await updatedArticle.getAttribute("open")) === null) await updatedArticle.locator(":scope > summary").click();
    await updatedArticle.locator("details.article-extras > summary").click();
    assert.equal(await updatedArticle.locator("[data-extra-toggle]").first().isChecked(), true);
    assert.equal(await updatedArticle.locator("[data-extra-cost]").first().inputValue(), "46,20");
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

  await runTest("nessun overflow globale ai viewport richiesti e zoom 125%", async (page) => {
    const routes = [
      `/preventivi/${fixtures.main_quote}/dati/`,
      `/preventivi/${fixtures.main_quote}/articoli/`,
      `/preventivi/${fixtures.main_quote}/lavorazioni/`,
      `/preventivi/${fixtures.main_quote}/riepilogo/`,
    ];
    for (const width of [1440, 1280, 1024, 768, 480, 360]) {
      await page.setViewportSize({ width, height: 900 });
      for (const route of routes) {
        await page.goto(`${baseURL}${route}`);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        assert.ok(overflow <= 1, `${route} ha overflow di ${overflow}px a ${width}px`);
        if (visualAuditDir && (width === 1440 || width === 360)) {
          const section = route.includes("/articoli/") ? "articoli" : route.includes("/lavorazioni/") ? "lavorazioni" : route.includes("/riepilogo/") ? "riepilogo" : "dati";
          await page.screenshot({ path: path.join(visualAuditDir, `${width}-${section}.png`), fullPage: true });
        }
      }
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/riepilogo/`);
    await page.evaluate(() => { document.body.style.zoom = "1.25"; });
    const zoomOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(zoomOverflow <= 1, `Overflow a zoom 125%: ${zoomOverflow}px`);
  });

  await runAdminTest("Jazzmin usa override mirati e liste allineate", async (page) => {
    await page.goto(`${baseURL}/admin/rete/`);
    await page.getByRole("heading", { name: "Gestione rete locale" }).waitFor();
    await page.getByRole("heading", { name: "Informazioni di rete" }).waitFor();
    await page.getByRole("heading", { name: "PC rilevati" }).waitFor();
    assert.match(await page.locator(".large-status").innerText(), /in attesa|Nessuna richiesta/i);

    await page.goto(`${baseURL}/admin/`);
    assert.equal(await page.locator('link[href*="admin-overrides.css"]').count(), 1);
    await page.goto(`${baseURL}/admin/quotes/quote/`);
    await page.locator("#result_list").waitFor();
    const alignment = await page.locator("#result_list tbody td").first().evaluate((cell) => getComputedStyle(cell).verticalAlign);
    assert.equal(alignment, "middle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `Overflow admin: ${overflow}px`);
    if (visualAuditDir) await page.screenshot({ path: path.join(visualAuditDir, "admin-lista-preventivi.png"), fullPage: true });
    await page.goto(`${baseURL}/admin/catalog/material/add/`);
    await page.getByLabel("Nome").fill("Materiale Admin Browser");
    await page.getByLabel("Costo corrente al kg").fill("2,50");
    await page.getByRole("button", { name: /Salva$/ }).click();
    await page.waitForURL(/\/admin\/catalog\/material\/$/);
    assert.match(await page.locator("body").innerText(), /Materiale Admin Browser/);
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

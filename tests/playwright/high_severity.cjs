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

  await runTest("dashboard con selezione multipla solo per archiviazione", async (page) => {
    await page.goto(`${baseURL}/`);
    const rows = page.locator("tbody tr");
    assert.ok(await rows.count() <= 20, "La dashboard non deve mostrare più di 20 preventivi.");
    const checkboxes = page.locator("[data-quote-checkbox]");
    assert.ok(await checkboxes.count() >= 2, "Servono più preventivi selezionabili per l'azione multipla.");
    assert.equal(await checkboxes.first().isHidden(), true, "Le checkbox non devono comparire subito.");
    await page.getByRole("button", { name: "Archivia multipli" }).click();
    assert.equal(await checkboxes.first().isVisible(), true);
    const selectAll = page.locator("[data-select-all-quotes]");
    const archiveButton = page.getByRole("button", { name: "Archivia selezionati" });
    assert.equal(await page.getByRole("button", { name: "Archivia tutti" }).isVisible(), true);
    assert.equal(await archiveButton.isDisabled(), true);
    await rows.first().click();
    assert.equal(await checkboxes.first().isChecked(), true, "Il clic sulla riga deve selezionare il preventivo.");
    const currentUrl = page.url();
    await rows.first().locator(".row-arrow").click();
    assert.equal(await checkboxes.first().isChecked(), false, "Anche il clic sulla freccia deve cambiare la selezione.");
    assert.equal(page.url(), currentUrl, "In modalità multipla la riga non deve aprire il preventivo.");
    await selectAll.check();
    assert.equal(await checkboxes.evaluateAll((elements) => elements.every((element) => element.checked)), true);
    assert.equal(await archiveButton.isEnabled(), true);
    assert.match(await page.locator("[data-bulk-selection-status]").innerText(), /preventivi selezionati/);
    await checkboxes.first().uncheck();
    assert.equal(await selectAll.evaluate((element) => element.indeterminate), true);
    assert.equal(await page.getByRole("button", { name: /Elimina selezionati/i }).count(), 0);
    const dashboardCheckboxAlignment = await checkboxes.first().evaluate((element) => {
      const checkbox = element.getBoundingClientRect();
      const cell = element.closest("td").getBoundingClientRect();
      return Math.abs((checkbox.top + checkbox.height / 2) - (cell.top + cell.height / 2));
    });
    assert.ok(dashboardCheckboxAlignment <= 1, "La checkbox dashboard deve essere centrata verticalmente.");
    await page.getByRole("button", { name: "Archivia multipli" }).click();
    assert.equal(await checkboxes.first().isHidden(), true);
  });

  await runTest("ricerca con ripristino multiplo in due passaggi", async (page) => {
    await page.goto(`${baseURL}/preventivi/cerca/?status=archived`);
    assert.ok(await page.locator("tbody tr").count() <= 50, "La ricerca non deve mostrare più di 50 risultati.");
    const filterAlignment = await page.locator(".search-filter-grid").evaluate((element) => {
      const controls = Array.from(element.querySelectorAll("input:not([type=hidden]), select, .search-filter-actions .button"));
      const boxes = controls.map((control) => control.getBoundingClientRect());
      return {
        heights: boxes.map((box) => Math.round(box.height)),
        centers: boxes.map((box) => Math.round((box.top + box.height / 2) * 10) / 10),
        viewportWidth: window.innerWidth,
        columns: getComputedStyle(element).gridTemplateColumns,
      };
    });
    assert.equal(new Set(filterAlignment.heights).size, 1, `Altezze filtri non uniformi: ${filterAlignment.heights.join(", ")}`);
    assert.ok(
      Math.max(...filterAlignment.centers) - Math.min(...filterAlignment.centers) <= 1,
      `Filtri non centrati verticalmente a ${filterAlignment.viewportWidth}px (${filterAlignment.columns}): ${filterAlignment.centers.join(", ")}`,
    );
    const archivedRow = page.locator("tbody tr").filter({ hasText: "ARCH-01" });
    assert.match(await archivedRow.innerText(), /Archiviato/);
    assert.doesNotMatch(await archivedRow.innerText(), /Bozza/);
    const checkbox = archivedRow.locator("[data-quote-checkbox]");
    assert.equal(await checkbox.isHidden(), true);
    await page.getByRole("button", { name: "Ripristina multipli" }).click();
    assert.equal(await checkbox.isVisible(), true);
    assert.equal(await page.getByRole("button", { name: "Ripristina selezionati" }).isDisabled(), true);
    assert.equal(await page.getByRole("button", { name: "Ripristina tutti" }).isVisible(), true);
    await archivedRow.click();
    assert.equal(await checkbox.isChecked(), true, "Il clic sulla riga deve selezionare il preventivo da ripristinare.");
    await archivedRow.click();
    assert.equal(await checkbox.isChecked(), false, "Un secondo clic sulla riga deve deselezionarlo.");
    await checkbox.check();
    assert.equal(await page.getByRole("button", { name: "Ripristina selezionati" }).isEnabled(), true);
    const searchCheckboxAlignment = await checkbox.evaluate((element) => {
      const checkboxBox = element.getBoundingClientRect();
      const cell = element.closest("td").getBoundingClientRect();
      return Math.abs((checkboxBox.top + checkboxBox.height / 2) - (cell.top + cell.height / 2));
    });
    assert.ok(searchCheckboxAlignment <= 1, "La checkbox ricerca deve essere centrata verticalmente.");
    await page.getByRole("button", { name: "Ripristina multipli" }).click();
    assert.equal(await checkbox.isHidden(), true);
  });

  await runAdminTest("gestione LAN richiede identita IP e MAC verificata", async (page) => {
    await page.goto(`${baseURL}/admin/rete/`);
    assert.match(await page.locator(".lan-control").innerText(), /sia l’IP sia il MAC/);
    const verified = page.locator(".lan-access-table tbody tr").filter({ hasText: "192.168.1.201" });
    assert.match(await verified.innerText(), /02:11:22:33:44:55/);
    assert.equal(await verified.getByRole("button", { name: "Sì" }).isEnabled(), true);
    const unverified = page.locator(".lan-access-table tbody tr").filter({ hasText: "192.168.1.202" });
    assert.match(await unverified.innerText(), /Non rilevato/);
    assert.equal(await unverified.getByRole("button", { name: "Sì" }).isDisabled(), true);
  });

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
    assert.equal(await page.locator("[data-contact-state]").isHidden(), true);
    assert.equal(await page.getByRole("option", { name: /Referente Unico/ }).count(), 1);
    assert.equal(await page.getByText("Inserimento libero").count(), 0);
    await search.fill(fixtures.client_without_preferred);
    await page.locator("[data-client-result]").filter({ hasText: fixtures.client_without_preferred }).click();
    assert.equal(await page.locator("[data-contact-id]").inputValue(), "");
    assert.equal(await page.locator("[data-contact-select]").inputValue(), "");

    const heights = await page.locator("#id_date, [data-client-search], [data-open-client-dialog], [data-contact-select], [data-open-contact-dialog]")
      .evaluateAll((elements) => elements.map((element) => Math.round(element.getBoundingClientRect().height)));
    assert.equal(new Set(heights).size, 1, `Altezze controlli non uniformi: ${heights.join(", ")}`);
    const cardWidth = await page.locator("[data-client-general]").evaluate((element) => element.getBoundingClientRect().width);
    assert.ok(cardWidth <= 1040, `Il modulo è ancora troppo largo: ${cardWidth}px`);
  });

  await runTest("fattibilita segmentata, compatta e adattata alla pagina", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/articoli/`);
    const stepAlignment = await page.locator(".steps > a").first().evaluate((step) => {
      const stepBox = step.getBoundingClientRect();
      const children = Array.from(step.children).map((child) => child.getBoundingClientRect());
      const contentTop = Math.min(...children.map((box) => box.top));
      const contentBottom = Math.max(...children.map((box) => box.bottom));
      return {
        stepCenter: stepBox.top + stepBox.height / 2,
        contentCenter: contentTop + (contentBottom - contentTop) / 2,
      };
    });
    assert.ok(
      Math.abs(stepAlignment.stepCenter - stepAlignment.contentCenter) <= 2,
      "Le scritte della navigazione devono essere centrate verticalmente.",
    );
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
    assert.equal(new Set(geometry.map((entry) => entry.x)).size, 1, "Nella pagina Articoli i segmenti devono essere in colonna.");
    assert.ok(geometry[0].y < geometry[1].y && geometry[1].y < geometry[2].y);
    const essentialFields = await selector.locator("xpath=ancestor::*[contains(@class, 'article-core-fields')]").evaluate((element) => {
      const quantity = element.querySelector(".field-quantity").getBoundingClientRect();
      const feasibility = element.querySelector(".field-feasibility").getBoundingClientRect();
      return {quantityHeight: quantity.height, feasibilityHeight: feasibility.height, quantityTop: quantity.top, feasibilityTop: feasibility.top};
    });
    assert.ok(Math.abs(essentialFields.quantityTop - essentialFields.feasibilityTop) <= 1);
    assert.ok(Math.abs(essentialFields.quantityHeight - essentialFields.feasibilityHeight) <= 1);
    assert.equal(new Set(geometry.map((entry) => entry.color)).size, 3, "Le tre Fattibilità devono avere colori distinti.");
    assert.ok(await selector.evaluate((element) => element.getBoundingClientRect().width <= 570));
    assert.equal(await selector.locator('input[type="radio"]').first().evaluate((element) => element.getBoundingClientRect().width <= 1), true);
    const articleTrack = selector.locator("ul, div[id]").first();
    assert.equal(
      await articleTrack.evaluate((element) => getComputedStyle(element).borderTopWidth),
      "0px",
      "Il selettore Articoli non deve avere un bordo esterno.",
    );
    const articleInitialTransform = await articleTrack.evaluate((element) => getComputedStyle(element, "::before").transform);
    const articleCurrentIndex = await labels.evaluateAll((elements) => elements.findIndex((element) => element.querySelector("input").checked));
    await labels.nth((articleCurrentIndex + 1) % 3).click();
    assert.match(
      await articleTrack.evaluate((element) => getComputedStyle(element, "::before").transitionProperty),
      /transform/,
    );
    await page.waitForTimeout(320);
    assert.notEqual(
      await articleTrack.evaluate((element) => getComputedStyle(element, "::before").transform),
      articleInitialTransform,
      "Nella pagina Articoli la barra deve scorrere orizzontalmente.",
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
    assert.equal(
      await summaryTrack.evaluate((element) => getComputedStyle(element).borderTopWidth),
      "0px",
      "Il selettore Riepilogo non deve avere un bordo esterno.",
    );
    const summaryInitialTransform = await summaryTrack.evaluate((element) => getComputedStyle(element, "::before").transform);
    const summaryCurrentIndex = await summaryLabels.evaluateAll((elements) => elements.findIndex((element) => element.querySelector("input").checked));
    await summaryLabels.nth((summaryCurrentIndex + 1) % 3).click();
    await page.waitForTimeout(320);
    assert.notEqual(
      await summaryTrack.evaluate((element) => getComputedStyle(element, "::before").transform),
      summaryInitialTransform,
      "Nel riepilogo la barra deve scorrere verticalmente.",
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
    const loadForm = page.locator('form[action$="/articoli/aggiungi/"]');
    await loadForm.locator('input[name="code"]').fill("PW-ERR");
    await loadForm.locator('input[name="revision"]').fill("00");
    await loadForm.getByRole("button", { name: "Carica articolo" }).click();
    const article = page.locator("details[data-article-card]").filter({ hasText: "PW-ERR" });
    await article.waitFor();
    await article.evaluate((element) => { element.open = true; });
    const form = article.locator("form.article-edit-form");
    await form.locator('input[name$="-quantity"]').fill("0");
    await form.evaluate((element) => { element.noValidate = true; });
    const responsePromise = page.waitForResponse(
      (response) => response.url().endsWith("/modifica/") && response.status() === 422,
    );
    await form.getByRole("button", { name: "Salva modifiche articolo" }).click();
    await responsePromise;
    await page.locator(".field.has-error").filter({ hasText: "Quantità" }).waitFor();
    assert.match(await page.locator(".messages").innerText(), /Articolo non aggiornato/i);
    assert.equal(await page.locator('.field.has-error input[name$="-quantity"]').getAttribute("min"), "1");
    const invalidArticle = page.locator("details[data-article-card]").filter({ hasText: "PW-ERR" });
    page.once("dialog", (dialog) => dialog.accept());
    await invalidArticle.getByRole("button", { name: "Elimina articolo" }).click();
    await page.getByText(/PW-ERR rimosso/i).waitFor();
  });

  await runTest("articolo completo, doppio clic, persistenza, duplicazione ed eliminazione", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/articoli/`);
    const add = page.getByRole("button", { name: "Aggiungi articolo" });
    await add.evaluate((button) => { button.click(); button.click(); });
    assert.equal(await page.locator("[data-new-article]").count(), 1, "Il doppio clic deve creare una sola bozza.");

    const form = page.locator("[data-new-article] form");
    assert.equal(
      await form.locator(".article-load-section").evaluate((element) => getComputedStyle(element).borderBottomWidth),
      "0px",
    );
    assert.equal(
      await form.locator(".article-save-bar").evaluate((element) => getComputedStyle(element).borderTopWidth),
      "0px",
    );
    await form.locator('input[name="code"]').fill("PW-COMPLETO");
    await form.locator('input[name="revision"]').fill("00");
    assert.equal(await form.locator('input[name="quantity"], [name="description"], select[name="material"]').count(), 0);
    await form.getByRole("button", { name: "Carica articolo" }).click();
    let article = page.locator("details[data-article-card]").filter({ hasText: "PW-COMPLETO" });
    await article.waitFor();
    const orderedCards = page.locator("details[data-article-card]");
    const orderedCardCount = await orderedCards.count();
    assert.equal(
      (await orderedCards.first().locator(".article-index").innerText()).trim(),
      String(orderedCardCount).padStart(2, "0"),
      "L'articolo nuovo in testa deve mantenere il numero progressivo più alto.",
    );
    assert.equal(
      (await orderedCards.last().locator(".article-index").innerText()).trim(),
      "01",
      "L'articolo più vecchio in fondo deve restare il numero 1.",
    );
    await article.evaluate((element) => { element.open = true; });
    let editForm = article.locator("form.article-edit-form");
    await article.locator("details.article-secondary").first().evaluate((element) => { element.open = true; });
    assert.equal(await article.getByRole("button", { name: "Converti misure" }).count(), 0);
    await editForm.locator('input[name$="-length_mm"]').fill("25,4");
    const dimensionHint = editForm.locator(".field-length_mm [data-dimension-conversions]");
    assert.match(await dimensionHint.innerText(), /2,540 cm/);
    assert.match(await dimensionHint.innerText(), /1,000 in/);
    await editForm.locator('input[name$="-quantity"]').fill("3");
    await editForm.locator('[name$="-description"]').fill("Descrizione tecnica molto lunga per verificare il comportamento responsive senza troncamenti");
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/modifica/")),
      editForm.getByRole("button", { name: "Salva modifiche articolo" }).click(),
    ]);
    await page.waitForTimeout(100);
    article = page.locator("details[data-article-card]").filter({ hasText: "PW-COMPLETO" });
    await article.waitFor();
    await article.evaluate((element) => { element.open = true; });
    const addMaterial = article.locator("details.add-panel");
    await addMaterial.evaluate((element) => { element.open = true; });
    await addMaterial.locator('select[name$="-material"]').selectOption({ index: 1 });
    await addMaterial.locator('input[name$="-weight_kg"]').fill("2.750");
    await addMaterial.getByRole("button", { name: "Aggiungi materiale" }).click();
    await page.locator("details[data-article-card]").filter({ hasText: "PW-COMPLETO" }).locator(".material-table tbody tr").waitFor({ state: "attached" });
    assert.equal(await page.getByText("PW-COMPLETO", { exact: true }).count(), 2);

    await page.reload();
    article = page.locator("details[data-article-card]").filter({ hasText: "PW-COMPLETO" });
    if ((await article.getAttribute("open")) === null) await article.locator(":scope > summary").click();
    assert.equal(await article.locator('input[name$="-quantity"]').inputValue(), "3");
    assert.equal(await article.locator('input[name$="-length_mm"]').inputValue(), "25,400");
    assert.equal(await article.locator(".material-value-control--suffix input").inputValue(), "2,750");
    assert.equal(await article.locator(".material-value-control--suffix span").innerText(), "kg");
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
    const copy = page.locator("details[data-article-card]").filter({ hasText: "PW-COMPLETO-COPIA" });
    await copy.waitFor();
    if ((await copy.getAttribute("open")) === null) await copy.locator(":scope > summary").click();
    page.once("dialog", (dialog) => dialog.accept());
    await copy.getByRole("button", { name: "Elimina articolo" }).click();
    await page.getByText(/PW-COMPLETO-COPIA rimosso/i).waitFor();
    assert.equal(await page.getByText("PW-COMPLETO-COPIA", { exact: true }).count(), 0);

    if ((await article.getAttribute("open")) === null) await article.locator(":scope > summary").click();
    page.once("dialog", (dialog) => dialog.accept());
    await article.getByRole("button", { name: "Elimina articolo" }).click();
    await page.getByText(/PW-COMPLETO rimosso/i).waitFor();
  });

  await runTest("ricerca e caricamento dell'ultima versione articolo", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.version_quote}/articoli/`);
    await page.getByRole("button", { name: "Aggiungi articolo" }).click();
    const form = page.locator("[data-new-article] form");
    await form.locator('input[name="code"]').focus();
    assert.equal(await form.locator("[data-article-result]").count(), 0);
    assert.equal(await form.locator("[data-article-results]").isHidden(), true);
    await form.locator('input[name="code"]').fill("PW-01");
    const result = form.locator("[data-article-result]").filter({ hasText: "PW-01 · Rev. 00" });
    await result.waitFor();
    const autocompleteLayout = await form.evaluate((element) => {
      const input = element.querySelector("[data-article-code]").getBoundingClientRect();
      const results = element.querySelector("[data-article-results]").getBoundingClientRect();
      const card = element.closest(".draft-card");
      return {
        inputLeft: Math.round(input.left),
        inputRight: Math.round(input.right),
        resultsLeft: Math.round(results.left),
        resultsRight: Math.round(results.right),
        cardOverflow: getComputedStyle(card).overflow,
      };
    });
    assert.equal(autocompleteLayout.resultsLeft, autocompleteLayout.inputLeft);
    assert.equal(autocompleteLayout.resultsRight, autocompleteLayout.inputRight);
    assert.equal(autocompleteLayout.cardOverflow, "visible");
    assert.doesNotMatch(await result.innerText(), /Versione/i);
    assert.match(await result.innerText(), /\d{2}\/\d{2}\/\d{4}$/);
    await result.click();
    assert.equal(await form.locator("[data-article-version-status]").count(), 0);
    assert.notEqual(await form.locator('input[name="source_version_id"]').inputValue(), "");
    assert.equal(await form.locator('input[name="revision"]').inputValue(), "00");
    assert.equal(await form.locator('input[name="quantity"], [name="description"], select[name="material"]').count(), 0);
    const invalidFields = await form.evaluate((element) => Array.from(element.elements)
      .filter((field) => typeof field.checkValidity === "function" && !field.checkValidity())
      .map((field) => ({ name: field.name, value: field.value, message: field.validationMessage })));
    assert.deepEqual(invalidFields, [], `Campi non validi dopo la selezione: ${JSON.stringify(invalidFields)}`);
    await form.getByRole("button", { name: "Carica articolo" }).click();
    const article = page.locator("details[data-article-card]").filter({ hasText: "PW-01" });
    await article.waitFor();
    assert.match(await page.locator("details[data-article-card]").first().locator(":scope > summary").innerText(), /PW-01/);
    assert.match(await article.locator(":scope > summary").innerText(), /Rev\. 00/);
    assert.doesNotMatch(await article.locator(":scope > summary").innerText(), /versione/i);
    await page.getByRole("link", { name: "Continua", exact: true }).click();
    await page.locator(".item-banner").filter({ hasText: "PW-01" }).waitFor();
    assert.match(await page.locator(".item-banner").innerText(), /PW-01[\s\S]*Rev\. 00/);
    assert.doesNotMatch(await page.locator(".item-banner").innerText(), /versione/i);
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
    assert.equal(await inactive.getAttribute("open"), null, "Una fase inattiva non deve aprirsi cliccando la scheda.");
    await inactive.getByLabel(/^Attiva /).check();
    const active = page.locator(`#${phaseId}.phase-card.active`);
    await active.waitFor();
    assert.equal(await active.getByLabel(/^Attiva /).isChecked(), true);
    assert.equal(await page.locator(".message.success").count(), 0, "Il tick non deve mostrare conferme ridondanti.");

    const workspaceAlignment = await page.locator(".work-workspace").evaluate((workspace) => {
      const heading = workspace.querySelector(".page-heading").getBoundingClientRect();
      const banner = workspace.querySelector(".item-banner").getBoundingClientRect();
      const actions = workspace.querySelector(".wizard-actions").getBoundingClientRect();
      return {
        headingLeft: Math.round(heading.left),
        bannerLeft: Math.round(banner.left),
        bannerRight: Math.round(banner.right),
        actionsRight: Math.round(actions.right),
      };
    });
    assert.equal(workspaceAlignment.headingLeft, workspaceAlignment.bannerLeft, "Titolo e articolo devono partire dallo stesso asse.");
    assert.equal(workspaceAlignment.bannerRight, workspaceAlignment.actionsRight, "Articolo e azioni devono terminare sullo stesso asse.");

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
    const saveArticle = article.getByRole("button", { name: "Salva modifiche articolo" });
    await saveArticle.scrollIntoViewIfNeeded();
    const scrollBeforeSave = await page.evaluate(() => window.scrollY);
    await saveArticle.click();
    const savedMessage = page.locator(".message.success").filter({ hasText: "Modifiche articolo salvate correttamente." });
    await savedMessage.waitFor();
    await page.waitForTimeout(100);
    const scrollAfterSave = await page.evaluate(() => window.scrollY);
    assert.ok(
      Math.abs(scrollAfterSave - scrollBeforeSave) <= 3,
      `La pagina si è spostata dopo il salvataggio: ${scrollBeforeSave} -> ${scrollAfterSave}`,
    );
    assert.notEqual(await savedMessage.evaluate((element) => getComputedStyle(element).backgroundColor), "rgba(0, 0, 0, 0)");
    const updatedArticle = page.locator("details[data-article-card]").first();
    assert.notEqual(await updatedArticle.getAttribute("open"), null, "L'articolo salvato deve restare aperto.");
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

  await runTest("fasi inattive compatte e non apribili anche su schermo piccolo", async (page) => {
    await page.goto(`${baseURL}/preventivi/${fixtures.main_quote}/lavorazioni/`);
    assert.equal(await page.locator("details.phase-card").count(), 22);
    assert.equal(await page.locator("details.phase-card[open]").count(), 1);
    assert.equal(await page.locator("details.phase-card:not([open])").count(), 21);
    const firstInactive = page.locator("details.phase-card.inactive").first();
    await firstInactive.locator(":scope > summary").click();
    assert.equal(await firstInactive.getAttribute("open"), null);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    assert.equal(await page.locator("details.phase-card:not([open])").count(), 21);
    await page.locator("details.phase-card.inactive").first().locator(":scope > summary").click();
    assert.equal(await page.locator("details.phase-card.inactive").first().getAttribute("open"), null);
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
    await page.goto(`${baseURL}/admin/quotes/quoteitem/`);
    await page.locator("#result_list").waitFor();
    assert.match(await page.locator("body").innerText(), /Storico articoli/i);
    assert.match(await page.locator("#result_list thead").innerText(), /CODICE[\s\S]*REVISIONE[\s\S]*DATA ARTICOLO[\s\S]*VERSIONE SORGENTE/i);
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

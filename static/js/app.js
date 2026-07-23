const uniqueDraftIds = (root, index) => {
  const ids = new Map();
  root.querySelectorAll("[id]").forEach((element) => {
    const oldId = element.id;
    const newId = `${oldId}-draft-${index}`;
    ids.set(oldId, newId);
    element.id = newId;
  });
  root.querySelectorAll("label[for]").forEach((label) => {
    if (ids.has(label.htmlFor)) label.htmlFor = ids.get(label.htmlFor);
  });
};

const syncDisclosure = (details) => {
  const summary = details.querySelector(":scope > summary");
  if (summary) summary.setAttribute("aria-expanded", String(details.open));
};

const initDisclosures = (root = document) => {
  root.querySelectorAll("details").forEach(syncDisclosure);
};

const dismissToast = (toast) => {
  if (!toast || toast.classList.contains("is-leaving")) return;
  toast.classList.add("is-leaving");
  window.setTimeout(() => {
    const region = toast.closest(".toast-region");
    toast.remove();
    if (region && !region.querySelector("[data-toast]")) region.remove();
  }, 180);
};

const initToasts = (root = document) => {
  root.querySelectorAll("[data-toast]:not([data-toast-ready])").forEach((toast) => {
    toast.dataset.toastReady = "true";
    const duration = toast.classList.contains("error") ? 8000 : 4800;
    window.setTimeout(() => dismissToast(toast), duration);
  });
};

const readJsonData = (id, fallback) => {
  const element = document.getElementById(id);
  if (!element) return fallback;
  try { return JSON.parse(element.textContent); } catch (_error) { return fallback; }
};

let clientsData = readJsonData("clients-data", []);
let contactsData = readJsonData("contacts-data", []);

const normalizeSearch = (value) => String(value || "").trim().toLocaleLowerCase("it");

const formatDecimalText = (value, places = 2) => {
  const raw = String(value || "").trim().replace(/\s/g, "");
  if (!raw) return "";
  const lastComma = raw.lastIndexOf(",");
  const lastPoint = raw.lastIndexOf(".");
  const separator = Math.max(lastComma, lastPoint);
  let integer = separator >= 0 ? raw.slice(0, separator) : raw;
  let decimals = separator >= 0 ? raw.slice(separator + 1) : "";
  integer = integer.replace(/[.,]/g, "");
  decimals = decimals.replace(/[.,]/g, "");
  if (!/^\d+$/.test(integer) || (decimals && !/^\d+$/.test(decimals))) return raw;
  return `${integer},${decimals.padEnd(places, "0").slice(0, places)}`;
};

const clientSearchText = (client) => [client.name, client.email, client.phone].filter(Boolean).join(" ").toLocaleLowerCase("it");

const hideClientResults = (form) => {
  const input = form?.querySelector("[data-client-search]");
  const results = form?.querySelector("[data-client-results]");
  if (!input || !results) return;
  results.hidden = true;
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("aria-activedescendant");
  delete input.dataset.activeIndex;
};

const clearContactFields = (form) => {
  const contactId = form.querySelector("[data-contact-id]");
  const contactName = form.querySelector("[data-contact-name]");
  const contactEmail = form.querySelector("[data-contact-email]");
  if (contactId) contactId.value = "";
  if (contactName) contactName.value = "";
  if (contactEmail) contactEmail.value = "";
};

const setContactState = (form, message) => {
  const state = form.querySelector("[data-contact-state]");
  if (state) state.textContent = message;
};

const setContactControls = (form, enabled) => {
  const select = form.querySelector("[data-contact-select]");
  const addButton = form.querySelector("[data-open-contact-dialog]");
  if (select) select.disabled = !enabled;
  if (addButton) addButton.disabled = !enabled;
};

const applyContact = (form, contact) => {
  const select = form.querySelector("[data-contact-select]");
  if (select) select.value = contact ? String(contact.id) : "";
  form.querySelector("[data-contact-id]").value = contact ? String(contact.id) : "";
  if (contact) {
    form.querySelector("[data-contact-name]").value = contact.name || "";
    form.querySelector("[data-contact-email]").value = contact.email || "";
    setContactState(form, `${contact.name}${contact.email ? ` · ${contact.email}` : ""}`);
  } else {
    clearContactFields(form);
    setContactState(form, "Nessun referente selezionato.");
  }
};

const populateContacts = (form, clientId, {preserveExisting = true} = {}) => {
  const select = form.querySelector("[data-contact-select]");
  const contactId = form.querySelector("[data-contact-id]");
  if (!select || !contactId) return;
  const hasClient = Boolean(clientId);
  const currentName = normalizeSearch(form.querySelector("[data-contact-name]")?.value);
  const currentEmail = normalizeSearch(form.querySelector("[data-contact-email]")?.value);
  contactId.value = "";
  select.replaceChildren(new Option(hasClient ? "Nessun referente selezionato" : "Seleziona prima un cliente", ""));
  setContactControls(form, hasClient);
  if (!hasClient) {
    clearContactFields(form);
    setContactState(form, "Seleziona prima un cliente.");
    return;
  }
  const contacts = contactsData.filter((contact) => String(contact.client_id) === String(clientId));
  let selectedContact = null;
  contacts.forEach((contact) => {
    const option = new Option(`${contact.name}${contact.email ? ` — ${contact.email}` : ""}`, String(contact.id));
    option.dataset.name = contact.name;
    option.dataset.email = contact.email || "";
    select.add(option);
    if (preserveExisting && normalizeSearch(contact.name) === currentName && normalizeSearch(contact.email) === currentEmail) selectedContact = contact;
  });
  if (!selectedContact && contacts.length === 1 && (!preserveExisting || (!currentName && !currentEmail))) selectedContact = contacts[0];
  if (selectedContact) applyContact(form, selectedContact);
  else setContactState(form, contacts.length ? "Scegli un referente dall’elenco." : "Nessun referente registrato per questo cliente.");
};

const selectClient = (form, client, {preserveContact = false} = {}) => {
  if (!form || !client) return;
  form.querySelector("[data-client-search]").value = client.name;
  form.querySelector("[data-client-id]").value = String(client.id);
  if (!preserveContact) clearContactFields(form);
  populateContacts(form, client.id, {preserveExisting: preserveContact});
  hideClientResults(form);
};

const renderClientResults = (form) => {
  const input = form.querySelector("[data-client-search]");
  const results = form.querySelector("[data-client-results]");
  if (!input || !results) return;
  const query = normalizeSearch(input.value);
  const terms = query.split(/\s+/).filter(Boolean);
  const matches = clientsData.filter((client) => {
    const searchable = clientSearchText(client);
    return terms.every((term) => searchable.includes(term));
  });
  results.replaceChildren();
  matches.forEach((client, index) => {
    const item = document.createElement("li");
    item.id = `client-result-${client.id}`;
    item.setAttribute("role", "option");
    item.dataset.clientResult = String(client.id);
    const name = document.createElement("strong");
    name.textContent = client.name;
    const details = document.createElement("small");
    details.textContent = [client.email, client.phone].filter(Boolean).join(" · ") || "Cliente registrato";
    item.append(name, details);
    item.dataset.resultIndex = String(index);
    results.append(item);
  });
  if (!matches.length) {
    const empty = document.createElement("li");
    empty.className = "autocomplete-empty";
    empty.textContent = "Nessun cliente trovato. Puoi registrarne uno nuovo.";
    results.append(empty);
  }
  results.hidden = false;
  input.setAttribute("aria-expanded", "true");
  delete input.dataset.activeIndex;
  input.removeAttribute("aria-activedescendant");
};

const moveClientResult = (form, direction) => {
  const input = form.querySelector("[data-client-search]");
  const options = Array.from(form.querySelectorAll("[data-client-result]"));
  if (!options.length) return;
  let index = Number.parseInt(input.dataset.activeIndex ?? "-1", 10);
  index = (index + direction + options.length) % options.length;
  options.forEach((option, optionIndex) => option.setAttribute("aria-selected", String(optionIndex === index)));
  input.dataset.activeIndex = String(index);
  input.setAttribute("aria-activedescendant", options[index].id);
  options[index].scrollIntoView({block: "nearest"});
};

const initClientForms = (root = document) => {
  clientsData = readJsonData("clients-data", clientsData);
  contactsData = readJsonData("contacts-data", contactsData);
  root.querySelectorAll("[data-client-general]").forEach((form) => {
    const clientId = form.querySelector("[data-client-id]");
    if (clientId?.value) {
      populateContacts(form, clientId.value, {preserveExisting: true});
    } else {
      populateContacts(form, "", {preserveExisting: true});
    }
  });
};

const syncExtraCosts = (root = document, focusEnabled = false) => {
  root.querySelectorAll("[data-extra-toggle]").forEach((toggle) => {
    const form = toggle.closest("form");
    const cost = form?.querySelector(`[data-extra-cost="${toggle.dataset.extraToggle}"]`);
    const wrapper = cost?.closest(".field");
    if (!cost || !wrapper) return;
    wrapper.classList.add("conditional-field");
    wrapper.classList.toggle("is-disabled", !toggle.checked);
    wrapper.setAttribute("aria-disabled", String(!toggle.checked));
    cost.disabled = !toggle.checked;
    if (focusEnabled && toggle.checked) cost.focus();
  });
};

const initInteractive = (root = document) => {
  initDisclosures(root);
  initToasts(root);
  initClientForms(root);
  syncExtraCosts(root);
};

document.addEventListener("pointerdown", (event) => {
  const clientResult = event.target.closest?.("[data-client-result]");
  if (!clientResult) return;
  event.preventDefault();
  const form = clientResult.closest("[data-client-general]");
  const client = clientsData.find((entry) => String(entry.id) === clientResult.dataset.clientResult);
  selectClient(form, client);
});

document.addEventListener("toggle", (event) => {
  if (event.target instanceof HTMLDetailsElement) syncDisclosure(event.target);
}, true);

document.addEventListener("click", (event) => {
  if (event.target.matches("[data-phase-toggle]")) {
    event.stopPropagation();
    return;
  }

  const dismissButton = event.target.closest("[data-dismiss-toast]");
  if (dismissButton) {
    dismissToast(dismissButton.closest("[data-toast]"));
    return;
  }

  const openClientDialog = event.target.closest("[data-open-client-dialog]");
  if (openClientDialog) {
    document.querySelector("[data-client-dialog]")?.showModal();
    return;
  }

  const openContactDialog = event.target.closest("[data-open-contact-dialog]");
  if (openContactDialog) {
    const generalForm = openContactDialog.closest("[data-client-general]");
    const clientId = generalForm?.querySelector("[data-client-id]")?.value;
    const client = clientsData.find((entry) => String(entry.id) === String(clientId));
    const dialog = document.querySelector("[data-contact-dialog]");
    if (!dialog || !client) return;
    dialog.querySelector("[data-quick-contact-client]").value = String(client.id);
    dialog.querySelector("[data-contact-client-name]").textContent = client.name;
    dialog.showModal();
    dialog.querySelector('input[name$="-name"]')?.focus();
    return;
  }

  const closeClientDialog = event.target.closest("[data-close-client-dialog]");
  if (closeClientDialog) {
    closeClientDialog.closest("dialog")?.close();
    return;
  }

  const closeContactDialog = event.target.closest("[data-close-contact-dialog]");
  if (closeContactDialog) {
    closeContactDialog.closest("dialog")?.close();
    return;
  }

  const copyButton = event.target.closest("[data-copy-text]");
  if (copyButton) {
    const showCopied = () => {
      const original = copyButton.textContent;
      copyButton.textContent = "Copiato";
      window.setTimeout(() => { copyButton.textContent = original; }, 1400);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(copyButton.dataset.copyText).then(showCopied).catch(() => {});
    } else {
      const helper = document.createElement("textarea");
      helper.value = copyButton.dataset.copyText;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.append(helper);
      helper.select();
      if (document.execCommand("copy")) showCopied();
      helper.remove();
    }
    return;
  }

  const addButton = event.target.closest("[data-add-article]");
  if (addButton) {
    if (addButton.dataset.locked) return;
    addButton.dataset.locked = "true";
    addButton.disabled = true;
    const template = document.querySelector("#article-draft-template");
    const container = document.querySelector("#article-drafts");
    if (template && container) {
      const fragment = template.content.cloneNode(true);
      const card = fragment.querySelector("[data-new-article]");
      const index = container.querySelectorAll("[data-new-article]").length + 1;
      uniqueDraftIds(card, index);
      container.append(fragment);
      const appended = container.querySelectorAll("[data-new-article]")[index - 1];
      syncDisclosure(appended);
      syncExtraCosts(appended);
      window.htmx?.process(appended);
      appended.querySelector('input[name="code"]')?.focus();
    }
    window.setTimeout(() => {
      addButton.disabled = false;
      delete addButton.dataset.locked;
    }, 350);
    return;
  }

  const removeButton = event.target.closest("[data-remove-draft]");
  if (removeButton) {
    const card = removeButton.closest("[data-new-article]");
    const dirty = Array.from(card.querySelectorAll("input, select, textarea")).some((field) => {
      if (field.type === "hidden") return false;
      return field.value && field.value !== "1";
    });
    if (!dirty || window.confirm("Scartare questo articolo non ancora salvato? I dati inseriti andranno persi.")) card.remove();
    return;
  }

  const filterButton = event.target.closest("[data-phase-filter]");
  if (filterButton) {
    const onlyActive = filterButton.getAttribute("aria-pressed") !== "true";
    filterButton.setAttribute("aria-pressed", String(onlyActive));
    filterButton.textContent = onlyActive ? "Mostra tutte" : "Mostra solo attive";
    filterButton.closest(".item-work").querySelectorAll(".phase-card.inactive").forEach((card) => {
      card.hidden = onlyActive;
    });
  }
});

document.addEventListener("input", (event) => {
  if (event.target.matches("[data-client-search]")) {
    const form = event.target.closest("[data-client-general]");
    const hidden = form?.querySelector("[data-client-id]");
    if (hidden?.value) {
      const selected = clientsData.find((client) => String(client.id) === String(hidden.value));
      if (normalizeSearch(selected?.name) !== normalizeSearch(event.target.value)) {
        hidden.value = "";
        clearContactFields(form);
        populateContacts(form, "", {preserveExisting: false});
      }
    }
    renderClientResults(form);
    return;
  }

  if (event.target.matches('[name$="working_minutes"], [name$="setup_minutes"]')) {
    event.target.closest("[data-time-operation-form]")?.querySelector('[name$="working_minutes"]')?.setCustomValidity("");
  }

  const card = event.target.closest("[data-new-article]");
  if (!card) return;
  const code = card.querySelector('input[name="code"]')?.value.trim();
  const description = card.querySelector('[name="description"]')?.value.trim();
  const title = card.querySelector(".article-summary strong");
  const subtitle = card.querySelector(".article-summary small");
  if (title) title.textContent = code || "Articolo da completare";
  if (subtitle) subtitle.textContent = description || "Inserisci articolo, materiale e peso";
});

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-contact-select]")) {
    const form = event.target.closest("[data-client-general]");
    const contact = contactsData.find((entry) => String(entry.id) === String(event.target.value));
    applyContact(form, contact || null);
    return;
  }

  if (event.target.matches("[data-material-select]")) {
    const costs = readJsonData("material-costs-data", {});
    const costInput = event.target.closest("form")?.querySelector("[data-material-cost]");
    if (costInput) costInput.value = formatDecimalText(costs[event.target.value] ?? "", 2);
    return;
  }

  if (event.target.matches("[data-extra-toggle]")) {
    syncExtraCosts(event.target.closest("form"), true);
    return;
  }

  if (event.target.matches("[data-phase-toggle]")) {
    event.stopPropagation();
    event.target.form?.requestSubmit();
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches("[data-quick-client-form]")) return;
  event.preventDefault();
  const errors = form.querySelector("[data-quick-client-errors]");
  const submitter = event.submitter;
  submitter?.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(form.action, {method: "POST", body: new FormData(form), headers: {"X-Requested-With": "XMLHttpRequest"}});
    const result = await response.json();
    if (!response.ok) {
      errors.hidden = false;
      errors.textContent = Object.values(result.errors || {}).flat().join(" ") || "Controlla i dati inseriti.";
      return;
    }
    clientsData.push(result.client);
    if (result.contact) contactsData.push({...result.contact, client_id: result.client.id});
    const generalForm = document.querySelector("[data-client-general]");
    selectClient(generalForm, result.client);
    form.closest("dialog")?.close();
    form.reset();
    errors.hidden = true;
  } catch (_error) {
    errors.hidden = false;
    errors.textContent = "Registrazione non riuscita. Verifica la connessione e riprova.";
  } finally {
    submitter?.removeAttribute("aria-busy");
    if (submitter) delete submitter.dataset.submitting;
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches("[data-quick-contact-form]")) return;
  event.preventDefault();
  const errors = form.querySelector("[data-quick-contact-errors]");
  const submitter = event.submitter;
  submitter?.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(form.action, {method: "POST", body: new FormData(form), headers: {"X-Requested-With": "XMLHttpRequest"}});
    const result = await response.json();
    if (!response.ok) {
      errors.hidden = false;
      errors.textContent = Object.values(result.errors || {}).flat().join(" ") || "Controlla i dati inseriti.";
      return;
    }
    contactsData.push(result.contact);
    const generalForm = document.querySelector("[data-client-general]");
    populateContacts(generalForm, result.contact.client_id, {preserveExisting: false});
    applyContact(generalForm, result.contact);
    form.closest("dialog")?.close();
    form.reset();
    errors.hidden = true;
  } catch (_error) {
    errors.hidden = false;
    errors.textContent = "Registrazione non riuscita. Verifica la connessione e riprova.";
  } finally {
    submitter?.removeAttribute("aria-busy");
    if (submitter) delete submitter.dataset.submitting;
  }
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches("[data-time-operation-form]")) return;
  const working = form.querySelector('[name$="working_minutes"]');
  const setup = form.querySelector('[name$="setup_minutes"]');
  const greaterThanZero = (value) => /[1-9]/.test(String(value || "").replace(/[.,]/g, ""));
  if (!greaterThanZero(working?.value) && !greaterThanZero(setup?.value)) {
    event.preventDefault();
    working?.setCustomValidity("Inserire almeno un tempo di lavorazione o attrezzaggio maggiore di zero.");
    working?.reportValidity();
  }
});

document.addEventListener("keydown", (event) => {
  if (!event.target.matches("[data-client-search]")) return;
  const form = event.target.closest("[data-client-general]");
  const results = form.querySelector("[data-client-results]");
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (results.hidden) renderClientResults(form);
    moveClientResult(form, event.key === "ArrowDown" ? 1 : -1);
  } else if (event.key === "Enter" && !results.hidden) {
    const options = Array.from(form.querySelectorAll("[data-client-result]"));
    const index = Number.parseInt(event.target.dataset.activeIndex ?? "0", 10);
    const option = options[index];
    if (option) {
      event.preventDefault();
      const client = clientsData.find((entry) => String(entry.id) === option.dataset.clientResult);
      selectClient(form, client);
    }
  } else if (event.key === "Escape") {
    hideClientResults(form);
  }
});

document.addEventListener("focusin", (event) => {
  if (event.target.matches("[data-client-search]")) renderClientResults(event.target.closest("[data-client-general]"));
});

document.addEventListener("focusout", (event) => {
  const form = event.target.closest?.("[data-client-general]");
  if (!form) return;
  window.setTimeout(() => {
    if (!form.contains(document.activeElement)) hideClientResults(form);
  }, 0);
});

document.addEventListener("blur", (event) => {
  if (!event.target.matches("[data-decimal-input]") || !event.target.value.trim()) return;
  const places = Number.parseInt(event.target.dataset.decimalPlaces || "2", 10);
  event.target.value = formatDecimalText(event.target.value, places);
}, true);

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (event.defaultPrevented) return;
  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
    return;
  }
  const submitter = event.submitter;
  if (!(submitter instanceof HTMLButtonElement)) return;
  if (submitter.dataset.submitting) {
    event.preventDefault();
    return;
  }
  submitter.dataset.submitting = "true";
  submitter.setAttribute("aria-busy", "true");
});

const releaseSubmitButtons = () => {
  document.querySelectorAll("button[data-submitting]").forEach((button) => {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    delete button.dataset.submitting;
  });
};

document.body.addEventListener("htmx:configRequest", (event) => {
  const token = document.querySelector("[name=csrfmiddlewaretoken]")?.value;
  if (token) event.detail.headers["X-CSRFToken"] = token;
});

document.body.addEventListener("htmx:beforeSwap", (event) => {
  if (event.detail.xhr.status === 422) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  initInteractive(event.target);
  releaseSubmitButtons();
});
document.body.addEventListener("htmx:responseError", releaseSubmitButtons);
initInteractive();

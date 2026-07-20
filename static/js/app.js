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

document.addEventListener("toggle", (event) => {
  if (event.target instanceof HTMLDetailsElement) syncDisclosure(event.target);
}, true);

document.addEventListener("click", (event) => {
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
  const card = event.target.closest("[data-new-article]");
  if (!card) return;
  const code = card.querySelector('input[name="code"]')?.value.trim();
  const description = card.querySelector('input[name="description"]')?.value.trim();
  const title = card.querySelector(".article-summary strong");
  const subtitle = card.querySelector(".article-summary small");
  if (title) title.textContent = code || "Articolo da completare";
  if (subtitle) subtitle.textContent = description || "Inserisci articolo, materiale e peso";
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
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
  initDisclosures(event.target);
  releaseSubmitButtons();
});
document.body.addEventListener("htmx:responseError", releaseSubmitButtons);
initDisclosures();

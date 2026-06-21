const state = {
  groups: [],
  accounts: [],
  selected: new Set(),
  plan: null,
  campaign: null,
  accountPoll: null,
  images: [],
  history: [],
  savedDraftSelected: null,
};

const elements = {
  connectionDot: document.querySelector("#connection-dot"),
  connectionTitle: document.querySelector("#connection-title"),
  connectionCopy: document.querySelector("#connection-copy"),
  refresh: document.querySelector("#refresh-button"),
  accountSelect: document.querySelector("#account-select"),
  linkAccountButton: document.querySelector("#link-account-button"),
  accountDialog: document.querySelector("#account-dialog"),
  accountQr: document.querySelector("#account-qr"),
  accountLinkStatus: document.querySelector("#account-link-status"),
  selectAll: document.querySelector("#select-all"),
  search: document.querySelector("#group-search"),
  list: document.querySelector("#groups-list"),
  selectionCount: document.querySelector("#selection-count"),
  message: document.querySelector("#message"),
  imageInput: document.querySelector("#image-input"),
  imagePreviews: document.querySelector("#image-previews"),
  repeatCount: document.querySelector("#repeat-count"),
  intervalSelect: document.querySelector("#interval-select"),
  charCount: document.querySelector("#char-count"),
  planBox: document.querySelector("#plan-box"),
  planGroups: document.querySelector("#plan-groups"),
  planImages: document.querySelector("#plan-images"),
  confirmToken: document.querySelector("#confirm-token"),
  planButton: document.querySelector("#plan-button"),
  sendButton: document.querySelector("#send-button"),
  errorBox: document.querySelector("#error-box"),
  resultsEmpty: document.querySelector("#results-empty"),
  resultsTable: document.querySelector("#results-table"),
  dialog: document.querySelector("#confirm-dialog"),
  dialogCount: document.querySelector("#dialog-count"),
  dialogToken: document.querySelector("#dialog-token"),
  confirmSendButton: document.querySelector("#confirm-send-button"),
  dialogTiming: document.querySelector("#dialog-timing"),
  dialogImages: document.querySelector("#dialog-images"),
  logoutButton: document.querySelector("#logout-button"),
  countdownBox: document.querySelector("#countdown-box"),
  countdownLabel: document.querySelector("#countdown-label"),
  countdownValue: document.querySelector("#countdown-value"),
  cancelTimerButton: document.querySelector("#cancel-timer-button"),
  
  // New visual elements
  themeToggle: document.querySelector("#theme-toggle"),
  sunIcon: document.querySelector("#theme-toggle .sun-icon"),
  moonIcon: document.querySelector("#theme-toggle .moon-icon"),
  navBroadcast: document.querySelector("#nav-broadcast"),
  navHistory: document.querySelector("#nav-history"),
  viewTitle: document.querySelector("#view-title"),
  viewSubtitle: document.querySelector("#view-subtitle"),
  broadcastView: document.querySelector("#broadcast-view"),
  historyView: document.querySelector("#history-view"),
  historySearch: document.querySelector("#history-search"),
  historyStatusFilter: document.querySelector("#history-status-filter"),
  historyEmpty: document.querySelector("#history-empty"),
  historyTableWrapper: document.querySelector("#history-table-wrapper"),
  historyTableBody: document.querySelector("#history-table-body"),
};

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  let payload;
  try {
    payload = await response.json();
  } catch (e) {
    if (!response.ok) throw new Error(`Ошибка запроса: ${response.status} ${response.statusText}`);
    throw e;
  }
  if (!response.ok) {
    let msg = "Ошибка запроса";
    if (payload && payload.detail) {
      if (typeof payload.detail === "string") {
        msg = payload.detail;
      } else if (Array.isArray(payload.detail)) {
        msg = payload.detail.map(d => {
          const locStr = d.loc ? d.loc.filter(x => x !== "body").join(".") : "";
          return (locStr ? locStr + ": " : "") + d.msg;
        }).join("; ");
      } else if (typeof payload.detail === "object") {
        msg = JSON.stringify(payload.detail);
      }
    }
    throw new Error(msg);
  }
  return payload;
}

function invalidatePlan() {
  state.plan = null;
  elements.planBox.classList.add("hidden");
  elements.sendButton.disabled = true;
}

function showError(message = "") {
  elements.errorBox.textContent = message;
  elements.errorBox.classList.toggle("hidden", !message);
}

function campaignOptions() {
  const repeatCount = Math.max(1, Math.min(20, Number(elements.repeatCount.value) || 1));
  elements.repeatCount.value = String(repeatCount);
  return {
    repeat_count: repeatCount,
    interval_seconds: repeatCount > 1 ? Number(elements.intervalSelect.value) : 0,
  };
}

function pluralize(number, one, few, many) {
  const mod100 = number % 100;
  const mod10 = number % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function renderImages() {
  elements.imagePreviews.classList.toggle("hidden", state.images.length === 0);
  elements.imagePreviews.innerHTML = state.images.map((image, index) => `
    <div class="image-preview">
      <img src="${image.dataUrl}" alt="">
      <div>
        <strong>${escapeHtml(image.name)}</strong>
        <span>${formatBytes(image.size)}</span>
      </div>
      <button type="button" data-remove-image="${index}"
        aria-label="Удалить изображение">×</button>
    </div>
  `).join("");
  elements.imagePreviews.querySelectorAll("[data-remove-image]").forEach((button) => {
    button.addEventListener("click", () => {
      state.images.splice(Number(button.dataset.removeImage), 1);
      renderImages();
      updateSelection();
    });
  });
}

async function addImages(files) {
  showError();
  const allowed = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
  const total = state.images.reduce((sum, image) => sum + image.size, 0)
    + files.reduce((sum, file) => sum + file.size, 0);
  if (files.some((file) => !allowed.has(file.type))) {
    showError("Разрешены только PNG, JPEG, WebP и GIF.");
    return;
  }
  if (files.some((file) => file.size === 0 || file.size > 8 * 1024 * 1024)) {
    showError("Размер каждого изображения должен быть не более 8 МБ.");
    return;
  }
  if (total > 20 * 1024 * 1024) {
    showError("Суммарный размер изображений не должен превышать 20 МБ.");
    return;
  }
  const additions = await Promise.all(files.map((file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({
      name: file.name,
      size: file.size,
      dataUrl: reader.result,
    });
    reader.onerror = () => reject(new Error(`Не удалось прочитать ${file.name}`));
    reader.readAsDataURL(file);
  })));
  state.images.push(...additions);
  renderImages();
  updateSelection();
}

function updateSelection() {
  const availableCount = state.groups.filter((group) => group.available).length;
  elements.selectionCount.textContent = `${state.selected.size} выбрано`;
  elements.selectAll.checked = availableCount > 0 && state.selected.size === availableCount;
  elements.planButton.disabled = state.selected.size === 0 || !elements.message.value.trim();
  invalidatePlan();
  saveDraft();
}

function renderGroups() {
  const query = elements.search.value.trim().toLocaleLowerCase("ru");
  const visible = state.groups.filter((group) =>
    group.name.toLocaleLowerCase("ru").includes(query)
  );
  elements.list.innerHTML = visible.map((group) => `
    <label class="group-row">
      <input type="checkbox" data-alias="${escapeHtml(group.alias)}"
        ${state.selected.has(group.alias) ? "checked" : ""}
        ${group.available ? "" : "disabled"}>
      <span class="group-name" title="${escapeHtml(group.name)}">${escapeHtml(group.name)}</span>
      <span class="availability ${group.available ? "" : "offline"}"
        title="${group.available ? "Доступна" : "Недоступна"}"></span>
    </label>
  `).join("") || '<div class="empty-state">Группы не найдены.</div>';

  elements.list.querySelectorAll("input[data-alias]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.selected.add(input.dataset.alias);
      else state.selected.delete(input.dataset.alias);
      updateSelection();
    });
  });
}

function renderAccounts(activeNumber) {
  elements.accountSelect.innerHTML = state.accounts.map((number) => `
    <option value="${escapeHtml(number)}" ${number === activeNumber ? "selected" : ""}>
      ${escapeHtml(number)}
    </option>
  `).join("");
  elements.accountSelect.disabled = state.accounts.length < 2;
}

async function loadStatus() {
  elements.refresh.disabled = true;
  showError();
  try {
    const payload = await api("/api/status");
    state.groups = payload.groups;
    state.accounts = payload.accounts || [];
    
    // Apply draft groups selection if restored
    if (state.savedDraftSelected) {
      state.selected = new Set(
        [...state.savedDraftSelected].filter((alias) =>
          state.groups.some((group) => group.alias === alias && group.available)
        )
      );
      state.savedDraftSelected = null;
    } else {
      state.selected = new Set(
        [...state.selected].filter((alias) =>
          state.groups.some((group) => group.alias === alias && group.available)
        )
      );
    }
    
    renderAccounts(payload.active_number);
    elements.connectionDot.className = `status-dot ${payload.connected ? "" : "error"}`;
    elements.connectionTitle.textContent = payload.connected ? "Подключено" : "Нет связи";
    elements.connectionCopy.textContent = payload.message;
    renderGroups();
    updateSelection();
    return payload;
  } catch (error) {
    elements.connectionDot.className = "status-dot error";
    elements.connectionTitle.textContent = "Ошибка";
    elements.connectionCopy.textContent = error.message;
    showError(error.message);
    throw error;
  } finally {
    elements.refresh.disabled = false;
  }
}

async function createPlan() {
  showError();
  elements.planButton.disabled = true;
  try {
    state.plan = await api("/api/plan", {
      method: "POST",
      body: JSON.stringify({
        aliases: [...state.selected],
        message: elements.message.value,
        images: state.images.map((image) => image.dataUrl),
        ...campaignOptions(),
      }),
    });
    elements.planGroups.textContent = `${state.plan.group_count} ${
      pluralize(state.plan.group_count, "группа", "группы", "групп")
    } × ${state.plan.repeat_count}`;
    elements.confirmToken.textContent = state.plan.confirm_token;
    elements.planImages.textContent = String(state.plan.image_count);
    elements.planBox.classList.remove("hidden");
    elements.sendButton.textContent =
      state.plan.repeat_count > 1
        ? `Запустить ${state.plan.repeat_count} ${
          pluralize(state.plan.repeat_count, "отправку", "отправки", "отправок")
        }`
        : `Отправить в ${state.plan.group_count} групп`;
    elements.sendButton.disabled = false;
  } catch (error) {
    showError(error.message);
  } finally {
    if (!state.plan) updateSelection();
  }
}

function renderResults(results) {
  const labels = {
    sent: "Доставлено",
    already_sent: "Уже отправлено",
    delivery_unknown: "Неизвестно",
    failed: "Ошибка",
    not_attempted: "Не отправлено",
  };
  elements.resultsEmpty.classList.add("hidden");
  elements.resultsTable.classList.remove("hidden");
  elements.resultsTable.innerHTML = results.map((result) => {
    const group = state.groups.find((item) => item.alias === result.alias);
    return `
    <div class="result-row">
      <span>Цикл ${result.round_index}: ${escapeHtml(group?.name || result.alias)}</span>
      <span class="result-status ${escapeHtml(result.status)}">
        ${escapeHtml(labels[result.status] || result.status)}
      </span>
    </div>
  `;
  }).join("");
}

function formatCountdown(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return [hours, minutes, remainder]
    .filter((_, index) => hours > 0 || index > 0)
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

function waitInterval(seconds, nextRound) {
  return new Promise((resolve) => {
    const deadline = Date.now() + seconds * 1000;
    elements.countdownLabel.textContent = `Цикл ${nextRound} начнётся через`;
    elements.countdownBox.classList.remove("hidden");
    const tick = () => {
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      elements.countdownValue.textContent = formatCountdown(remaining);
      if (remaining === 0 || state.campaign?.cancelled) {
        clearInterval(timer);
        elements.countdownBox.classList.add("hidden");
        resolve();
      }
    };
    const timer = setInterval(tick, 250);
    tick();
  });
}

function setCampaignControls(disabled) {
  elements.message.disabled = disabled;
  elements.imageInput.disabled = disabled;
  elements.imagePreviews.querySelectorAll("button").forEach((button) => {
    button.disabled = disabled;
  });
  elements.repeatCount.disabled = disabled;
  elements.intervalSelect.disabled = disabled;
  elements.accountSelect.disabled = disabled || state.accounts.length < 2;
  elements.linkAccountButton.disabled = disabled;
  elements.planButton.disabled = disabled;
  elements.sendButton.disabled = disabled;
}

async function runCampaign() {
  if (!state.plan) return;
  elements.dialog.close();
  showError();
  const campaign = {cancelled: false, results: []};
  state.campaign = campaign;
  setCampaignControls(true);
  try {
    for (let round = 1; round <= state.plan.repeat_count; round += 1) {
      if (campaign.cancelled) break;
      const payload = await api("/api/send", {
        method: "POST",
        body: JSON.stringify({
          aliases: [...state.selected],
          message: elements.message.value,
          images: state.images.map((image) => image.dataUrl),
          confirm_token: state.plan.confirm_token,
          retry_unknown: false,
          repeat_count: state.plan.repeat_count,
          interval_seconds: state.plan.interval_seconds,
          round_index: round,
        }),
      });
      campaign.results.push(
        ...payload.results.map((result) => ({...result, round_index: round}))
      );
      renderResults(campaign.results);
      if (!payload.complete) break;
      if (round < state.plan.repeat_count) {
        await waitInterval(state.plan.interval_seconds, round + 1);
      }
    }
  } catch (error) {
    showError(error.message);
  } finally {
    state.campaign = null;
    elements.countdownBox.classList.add("hidden");
    setCampaignControls(false);
    invalidatePlan();
    updateSelection();
  }
}

async function selectAccount(number) {
  showError();
  await api("/api/accounts/select", {
    method: "POST",
    body: JSON.stringify({number}),
  });
  state.selected.clear();
  invalidatePlan();
  await loadStatus();
}

async function openAccountLink() {
  const knownAccounts = new Set(state.accounts);
  elements.accountLinkStatus.textContent = "Создаю QR-код…";
  elements.accountQr.removeAttribute("src");
  elements.accountDialog.showModal();
  try {
    const qr = await api("/api/accounts/link-qr", {
      method: "POST",
      body: "{}",
    });
    elements.accountQr.src = qr.image;
    elements.accountLinkStatus.textContent = "Ожидание сканирования…";
  } catch (error) {
    elements.accountLinkStatus.textContent = error.message;
    return;
  }
  clearInterval(state.accountPoll);
  state.accountPoll = setInterval(async () => {
    try {
      const payload = await api("/api/status");
      const added = (payload.accounts || []).find((number) => !knownAccounts.has(number));
      if (added) {
        clearInterval(state.accountPoll);
        state.accountPoll = null;
        elements.accountLinkStatus.textContent = `Подключён аккаунт ${added}`;
        await selectAccount(added);
        setTimeout(() => elements.accountDialog.close(), 900);
      }
    } catch {
      elements.accountLinkStatus.textContent = "Проверяю подключение…";
    }
  }, 3000);
}

/* ------------------- NEW FEATURES CONTROLLERS ------------------- */

/* 1. Theme Toggle System */
function initTheme() {
  const savedTheme = localStorage.getItem("theme");
  const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const isDark = savedTheme === "dark" || (!savedTheme && systemPrefersDark);
  
  document.documentElement.classList.toggle("dark-theme", isDark);
  updateThemeUI(isDark);
}

function updateThemeUI(isDark) {
  if (isDark) {
    elements.sunIcon.classList.remove("hidden");
    elements.moonIcon.classList.add("hidden");
  } else {
    elements.sunIcon.classList.add("hidden");
    elements.moonIcon.classList.remove("hidden");
  }
}

function toggleTheme() {
  const isDark = document.documentElement.classList.toggle("dark-theme");
  localStorage.setItem("theme", isDark ? "dark" : "light");
  updateThemeUI(isDark);
}

/* 2. View Switcher System */
function switchView(viewName) {
  if (viewName === "broadcast") {
    elements.navBroadcast.classList.add("active");
    elements.navHistory.classList.remove("active");
    elements.broadcastView.classList.remove("hidden");
    elements.historyView.classList.add("hidden");
    elements.viewTitle.textContent = "Новая рассылка";
    elements.viewSubtitle.textContent = "Выберите группы, проверьте сообщение и подтвердите отправку.";
  } else if (viewName === "history") {
    elements.navBroadcast.classList.remove("active");
    elements.navHistory.classList.add("active");
    elements.broadcastView.classList.add("hidden");
    elements.historyView.classList.remove("hidden");
    elements.viewTitle.textContent = "История отправлений";
    elements.viewSubtitle.textContent = "Записи прошлых попыток и текущего сеанса.";
    loadHistory().catch(() => {});
  }
}

/* 3. History Logs Fetching & Filtering */
async function loadHistory() {
  try {
    state.history = await api("/api/history");
    renderHistory();
  } catch (error) {
    showError(error.message);
  }
}

function renderHistory() {
  const query = elements.historySearch.value.trim().toLowerCase();
  const statusFilter = elements.historyStatusFilter.value;
  
  const filtered = state.history.filter((item) => {
    const matchesSearch = !query || 
      item.alias.toLowerCase().includes(query) || 
      item.target_token.toLowerCase().includes(query);
    const matchesStatus = statusFilter === "all" || item.status === statusFilter;
    return matchesSearch && matchesStatus;
  });
  
  const labels = {
    sent: "Доставлено",
    already_sent: "Уже отправлено",
    dispatching: "Отправка...",
    unknown: "Неизвестно",
    failed: "Ошибка",
    not_attempted: "Не отправлено",
  };
  
  if (filtered.length === 0) {
    elements.historyEmpty.classList.remove("hidden");
    elements.historyTableWrapper.classList.add("hidden");
  } else {
    elements.historyEmpty.classList.add("hidden");
    elements.historyTableWrapper.classList.remove("hidden");
    elements.historyTableBody.innerHTML = filtered.map((item) => {
      const dateStr = new Date(item.sent_at * 1000).toLocaleString("ru-RU");
      const isDispatching = item.status === "dispatching";
      const statusClass = `result-status ${item.status} ${isDispatching ? 'pulse-badge' : ''}`;
      return `
        <tr>
          <td>${escapeHtml(dateStr)}</td>
          <td><strong>${escapeHtml(item.alias)}</strong></td>
          <td><code>${escapeHtml(item.target_token)}</code></td>
          <td>
            <span class="${statusClass}">
              ${escapeHtml(labels[item.status] || item.status)}
            </span>
          </td>
        </tr>
      `;
    }).join("");
  }
}

/* 4. Draft Caching / Preservation */
function saveDraft() {
  const draft = {
    message: elements.message.value,
    repeatCount: elements.repeatCount.value,
    interval: elements.intervalSelect.value,
    selected: [...state.selected],
  };
  localStorage.setItem("signal_draft", JSON.stringify(draft));
}

function restoreDraft() {
  try {
    const raw = localStorage.getItem("signal_draft");
    if (!raw) return;
    const draft = JSON.parse(raw);
    if (draft.message) {
      elements.message.value = draft.message;
      elements.charCount.textContent = `${draft.message.length} символов`;
    }
    if (draft.repeatCount) {
      elements.repeatCount.value = draft.repeatCount;
    }
    if (draft.interval) {
      elements.intervalSelect.value = draft.interval;
    }
    if (Array.isArray(draft.selected)) {
      state.savedDraftSelected = new Set(draft.selected);
    }
  } catch (e) {
    console.error("Draft restoration failed:", e);
  }
}

/* ------------------- EVENT LISTENERS ------------------- */

elements.refresh.addEventListener("click", () => {
  loadStatus().catch(() => {});
  if (!elements.historyView.classList.contains("hidden")) {
    loadHistory().catch(() => {});
  }
});
elements.search.addEventListener("input", renderGroups);
elements.selectAll.addEventListener("change", () => {
  state.selected = new Set(
    elements.selectAll.checked
      ? state.groups.filter((group) => group.available).map((group) => group.alias)
      : []
  );
  renderGroups();
  updateSelection();
});
elements.message.addEventListener("input", () => {
  elements.charCount.textContent = `${elements.message.value.length} символов`;
  updateSelection();
});
elements.imageInput.addEventListener("change", async () => {
  try {
    await addImages([...elements.imageInput.files]);
  } catch (error) {
    showError(error.message);
  } finally {
    elements.imageInput.value = "";
  }
});
elements.repeatCount.addEventListener("change", updateSelection);
elements.intervalSelect.addEventListener("change", updateSelection);
elements.planButton.addEventListener("click", createPlan);
elements.sendButton.addEventListener("click", () => {
  elements.dialogCount.textContent = `${state.plan.group_count} ${
    pluralize(state.plan.group_count, "группа", "группы", "групп")
  } × ${state.plan.repeat_count} ${
    pluralize(state.plan.repeat_count, "цикл", "цикла", "циклов")
  }`;
  elements.dialogToken.textContent = state.plan.confirm_token;
  elements.dialogImages.textContent = state.plan.image_count
    ? `${state.plan.image_count} ${
      pluralize(state.plan.image_count, "изображение", "изображения", "изображений")
    }.`
    : "Без изображений.";
  elements.dialogTiming.textContent = state.plan.repeat_count > 1
    ? `Между циклами: ${elements.intervalSelect.selectedOptions[0].textContent}.`
    : "Будет выполнена одна отправка.";
  elements.dialog.showModal();
});
elements.confirmSendButton.addEventListener("click", (event) => {
  event.preventDefault();
  runCampaign();
});
elements.cancelTimerButton.addEventListener("click", () => {
  if (state.campaign) state.campaign.cancelled = true;
});
elements.accountSelect.addEventListener("change", () => {
  selectAccount(elements.accountSelect.value).catch((error) => showError(error.message));
});
elements.linkAccountButton.addEventListener("click", openAccountLink);
elements.accountDialog.addEventListener("close", () => {
  clearInterval(state.accountPoll);
  state.accountPoll = null;
  elements.accountQr.removeAttribute("src");
});
elements.logoutButton.addEventListener("click", async () => {
  await api("/api/logout", {method: "POST", body: "{}"});
  location.href = "/login";
});

// New feature listeners
elements.themeToggle.addEventListener("click", toggleTheme);
elements.navBroadcast.addEventListener("click", () => switchView("broadcast"));
elements.navHistory.addEventListener("click", () => switchView("history"));
elements.historySearch.addEventListener("input", renderHistory);
elements.historyStatusFilter.addEventListener("change", renderHistory);

// Initial setup
initTheme();
restoreDraft();
loadStatus().catch(() => {});

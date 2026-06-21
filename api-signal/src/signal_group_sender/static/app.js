const state = {
  groups: [],
  accounts: [],
  selected: new Set(),
  plan: null,
  campaign: null,
  campaignPoll: null,
  accountPoll: null,
  attachments: [],
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
  attachmentInput: document.querySelector("#attachment-input"),
  attachmentPreviews: document.querySelector("#attachment-previews"),
  repeatCount: document.querySelector("#repeat-count"),
  intervalSelect: document.querySelector("#interval-select"),
  charCount: document.querySelector("#char-count"),
  planBox: document.querySelector("#plan-box"),
  planGroups: document.querySelector("#plan-groups"),
  planAttachments: document.querySelector("#plan-attachments"),
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
  dialogAttachments: document.querySelector("#dialog-attachments"),
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
  toastContainer: document.querySelector("#toast-container"),
  progressContainer: document.querySelector("#progress-container"),
  progressLabel: document.querySelector("#progress-label"),
  progressPercent: document.querySelector("#progress-percent"),
  progressFill: document.querySelector("#progress-fill"),
  statHourly: document.querySelector("#stat-hourly"),
  statDaily: document.querySelector("#stat-daily"),
  statSuccess: document.querySelector("#stat-success"),
  statRemaining: document.querySelector("#stat-remaining"),
};

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

/** Returns a debounced version of fn that fires after `wait` ms of silence. */
function debounce(fn, wait = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
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
  const repeatCount = Math.max(1, Number(elements.repeatCount.value) || 1);
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

function renderAttachmentPreview(attachment) {
  if (attachment.type === "video/mp4") {
    return `<video src="${attachment.dataUrl}" muted playsinline preload="metadata"></video>`;
  }
  return `<img src="${attachment.dataUrl}" alt="">`;
}

function renderAttachments() {
  elements.attachmentPreviews.classList.toggle("hidden", state.attachments.length === 0);
  elements.attachmentPreviews.innerHTML = state.attachments.map((attachment, index) => `
    <div class="image-preview">
      ${renderAttachmentPreview(attachment)}
      <div>
        <strong>${escapeHtml(attachment.name)}</strong>
        <span>${formatBytes(attachment.size)}</span>
      </div>
      <button type="button" data-remove-attachment="${index}"
        aria-label="Удалить вложение">×</button>
    </div>
  `).join("");
  elements.attachmentPreviews.querySelectorAll("[data-remove-attachment]").forEach((button) => {
    button.addEventListener("click", () => {
      state.attachments.splice(Number(button.dataset.removeAttachment), 1);
      renderAttachments();
      updateSelection();
    });
  });
}

async function addAttachments(files) {
  showError();
  const allowed = new Set(["image/png", "image/jpeg", "image/webp", "image/gif", "video/mp4"]);
  if (files.some((file) => !allowed.has(file.type))) {
    showError("Разрешены только PNG, JPEG, WebP, GIF и MP4.");
    return;
  }
  const additions = await Promise.all(files.map((file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({
      name: file.name,
      size: file.size,
      type: file.type,
      dataUrl: reader.result,
    });
    reader.onerror = () => reject(new Error(`Не удалось прочитать ${file.name}`));
    reader.readAsDataURL(file);
  })));
  state.attachments.push(...additions);
  renderAttachments();
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

  // DocumentFragment for batched DOM update — no repeated reflows
  const fragment = document.createDocumentFragment();

  if (visible.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Группы не найдены.";
    fragment.appendChild(empty);
  } else {
    for (const group of visible) {
      const label = document.createElement("label");
      label.className = "group-row";

      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.alias = group.alias;
      input.checked = state.selected.has(group.alias);
      input.disabled = !group.available;
      input.addEventListener("change", () => {
        if (input.checked) state.selected.add(group.alias);
        else state.selected.delete(group.alias);
        updateSelection();
      });

      const nameSpan = document.createElement("span");
      nameSpan.className = "group-name";
      nameSpan.title = group.name;
      nameSpan.textContent = group.name;

      const dot = document.createElement("span");
      dot.className = `availability${group.available ? "" : " offline"}`;
      dot.title = group.available ? "Доступна" : "Недоступна";

      label.appendChild(input);
      label.appendChild(nameSpan);
      label.appendChild(dot);
      fragment.appendChild(label);
    }
  }

  elements.list.replaceChildren(fragment);
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
  elements.refresh.classList.add("refreshing");
  showError();
  try {
    const payload = await api("/api/status");
    state.groups = payload.groups;
    state.accounts = payload.accounts || [];
    
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
    elements.refresh.classList.remove("refreshing");
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
        attachments: state.attachments.map((attachment) => attachment.dataUrl),
        ...campaignOptions(),
      }),
    });
    elements.planGroups.textContent = `${state.plan.group_count} ${
      pluralize(state.plan.group_count, "группа", "группы", "групп")
    } × ${state.plan.repeat_count}`;
    elements.confirmToken.textContent = state.plan.confirm_token;
    elements.planAttachments.textContent = String(state.plan.attachment_count);
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

function isCampaignActive(campaign) {
  return ["pending", "running", "waiting", "cancel_requested"].includes(campaign?.status);
}

function renderCampaignStatus(campaign) {
  state.campaign = isCampaignActive(campaign) ? campaign : null;
  if (campaign.results?.length) {
    renderResults(campaign.results);
  }
  updateProgress(campaign.current_round || 0, campaign.repeat_count || 1);

  if (campaign.status === "waiting" && campaign.next_run_at) {
    const nextRound = (campaign.current_round || 0) + 1;
    const remaining = Math.max(0, Math.ceil((campaign.next_run_at * 1000 - Date.now()) / 1000));
    elements.countdownLabel.textContent = `Цикл ${nextRound} начнётся через`;
    elements.countdownValue.textContent = formatCountdown(remaining);
    elements.countdownBox.classList.remove("hidden");
  } else if (campaign.status === "running" || campaign.status === "pending") {
    elements.countdownLabel.textContent = `Цикл ${(campaign.current_round || 0) + 1} выполняется`;
    elements.countdownValue.textContent = "идёт";
    elements.countdownBox.classList.remove("hidden");
  } else if (campaign.status === "cancel_requested") {
    elements.countdownLabel.textContent = "Останавливаем кампанию";
    elements.countdownValue.textContent = "…";
    elements.countdownBox.classList.remove("hidden");
  } else {
    elements.countdownBox.classList.add("hidden");
  }
}

function stopCampaignPolling() {
  if (state.campaignPoll) {
    clearInterval(state.campaignPoll);
    state.campaignPoll = null;
  }
}

async function refreshCampaignStatus({notifyTerminal = false} = {}) {
  const campaign = await api("/api/campaign");
  const wasActive = Boolean(state.campaign);
  renderCampaignStatus(campaign);
  setCampaignControls(isCampaignActive(campaign));
  if (!isCampaignActive(campaign)) {
    stopCampaignPolling();
    if (wasActive || notifyTerminal) {
      if (campaign.status === "completed") {
        playNotificationSound();
        showToast("Кампания завершена", "success");
      } else if (campaign.status === "cancelled") {
        showToast("Кампания остановлена", "info");
      } else if (campaign.status === "failed") {
        showError(campaign.error || "Кампания завершилась ошибкой");
        showToast(campaign.error || "Кампания завершилась ошибкой", "error");
      }
      invalidatePlan();
      updateSelection();
      loadStats().catch(() => {});
      if (!elements.historyView.classList.contains("hidden")) {
        loadHistory().catch(() => {});
      }
    }
  }
  return campaign;
}

function startCampaignPolling() {
  stopCampaignPolling();
  state.campaignPoll = setInterval(() => {
    refreshCampaignStatus({notifyTerminal: true}).catch((error) => {
      showError(error.message);
    });
  }, 2000);
}

function setCampaignControls(disabled) {
  elements.message.disabled = disabled;
  elements.attachmentInput.disabled = disabled;
  elements.attachmentPreviews.querySelectorAll("button").forEach((button) => {
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
  setCampaignControls(true);
  try {
    const campaign = await api("/api/campaign", {
      method: "POST",
      body: JSON.stringify({
        aliases: [...state.selected],
        message: elements.message.value,
        attachments: state.attachments.map((attachment) => attachment.dataUrl),
        confirm_token: state.plan.confirm_token,
        retry_unknown: false,
        repeat_count: state.plan.repeat_count,
        interval_seconds: state.plan.interval_seconds,
      }),
    });
    renderCampaignStatus(campaign);
    startCampaignPolling();
    showToast("Кампания запущена на сервере", "success");
  } catch (error) {
    showError(error.message);
    showToast(error.message, "error");
    setCampaignControls(false);
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

/* Toast Notification System */
function showToast(message, type = "info", duration = 5000) {
  const icons = {
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 12l2 2 4-4m6 2a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"/></svg>',
    error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M12 11v5"/></svg>',
  };
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || icons.info}</span>
    <span>${escapeHtml(message)}</span>
    <button class="toast-close" type="button">×</button>
  `;
  elements.toastContainer.appendChild(toast);
  const dismiss = () => {
    toast.classList.add("dismissing");
    setTimeout(() => toast.remove(), 300);
  };
  toast.querySelector(".toast-close").addEventListener("click", dismiss);
  setTimeout(dismiss, duration);
}

/* Campaign Progress Bar */
function updateProgress(round, total) {
  if (total <= 1) {
    elements.progressContainer.classList.add("hidden");
    return;
  }
  const percent = Math.round((round / total) * 100);
  elements.progressContainer.classList.remove("hidden");
  elements.progressLabel.textContent = `Цикл ${round} из ${total}`;
  elements.progressPercent.textContent = `${percent}%`;
  elements.progressFill.style.width = `${percent}%`;
}

/* Notification Sound (Web Audio API) */
function playNotificationSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(880, ctx.currentTime);
    oscillator.frequency.setValueAtTime(1100, ctx.currentTime + 0.1);
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
    oscillator.start(ctx.currentTime);
    oscillator.stop(ctx.currentTime + 0.35);
  } catch { /* silently ignore in environments without Web Audio API */ }
}

/* Stats Widget */
async function loadStats() {
  try {
    [elements.statHourly, elements.statDaily, elements.statSuccess, elements.statRemaining]
      .forEach((el) => el?.classList.add("updating"));
    const stats = await api("/api/stats");
    elements.statHourly.textContent = stats.hourly_count;
    elements.statDaily.textContent = stats.daily_count;
    elements.statSuccess.textContent = `${stats.success_rate}%`;
    elements.statRemaining.textContent = `${stats.hourly_remaining} / ${stats.daily_remaining}`;
    [elements.statHourly, elements.statDaily, elements.statSuccess, elements.statRemaining]
      .forEach((el) => el?.classList.remove("updating"));
  } catch { /* silently ignore on stats failure */ }
}

// Auto-refresh stats every 60 seconds
setInterval(() => loadStats().catch(() => {}), 60_000);


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
  loadStats().catch(() => {});
  refreshCampaignStatus().then((campaign) => {
    if (isCampaignActive(campaign)) startCampaignPolling();
  }).catch(() => {});
  if (!elements.historyView.classList.contains("hidden")) {
    loadHistory().catch(() => {});
  }
});
// Debounced search — avoids re-render on every keypress
elements.search.addEventListener("input", debounce(renderGroups, 250));
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
elements.attachmentInput.addEventListener("change", async () => {
  try {
    await addAttachments([...elements.attachmentInput.files]);
  } catch (error) {
    showError(error.message);
  } finally {
    elements.attachmentInput.value = "";
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
  elements.dialogAttachments.textContent = state.plan.attachment_count
    ? `${state.plan.attachment_count} ${
      pluralize(state.plan.attachment_count, "вложение", "вложения", "вложений")
    }.`
    : "Без вложений.";
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
  api("/api/campaign/cancel", {method: "POST", body: "{}"})
    .then((campaign) => {
      renderCampaignStatus(campaign);
      showToast("Остановка кампании запрошена", "info");
    })
    .catch((error) => showError(error.message));
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

// Keyboard shortcuts
document.addEventListener("keydown", (event) => {
  // Ctrl+Enter to send (when plan is ready)
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    if (state.plan && !elements.sendButton.disabled && !state.campaign) {
      event.preventDefault();
      elements.sendButton.click();
    }
  }
  // Escape to close dialogs
  if (event.key === "Escape") {
    if (elements.dialog.open) elements.dialog.close();
    if (elements.accountDialog.open) elements.accountDialog.close();
  }
});

// Auto-refresh history (every 30s when History tab is open)
let historyRefreshInterval = null;
function startHistoryAutoRefresh() {
  stopHistoryAutoRefresh();
  historyRefreshInterval = setInterval(() => {
    if (!elements.historyView.classList.contains("hidden")) {
      loadHistory().catch(() => {});
      loadStats().catch(() => {});
    }
  }, 30000);
}
function stopHistoryAutoRefresh() {
  if (historyRefreshInterval) {
    clearInterval(historyRefreshInterval);
    historyRefreshInterval = null;
  }
}

// Initial setup
initTheme();
restoreDraft();
loadStatus().catch(() => {});
loadStats().catch(() => {});
refreshCampaignStatus().then((campaign) => {
  if (isCampaignActive(campaign)) startCampaignPolling();
}).catch(() => {});
startHistoryAutoRefresh();

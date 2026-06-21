const state = {
  chats: [],
  selected: new Set(),
  plan: null,
  campaign: null,
  attachments: [],
  history: [],
  phone: "",
  authorized: false,
  savedDraftSelected: null,
};

const initialStatus = window.__TELEGRAM_INITIAL_STATUS__ || null;

const elements = {
  connectionDot: document.querySelector("#connection-dot"),
  connectionTitle: document.querySelector("#connection-title"),
  connectionCopy: document.querySelector("#connection-copy"),
  phone: document.querySelector("#telegram-phone"),
  authButton: document.querySelector("#telegram-auth-button"),
  refresh: document.querySelector("#refresh-button"),
  search: document.querySelector("#chat-search"),
  list: document.querySelector("#chats-list"),
  selectionCount: document.querySelector("#selection-count"),
  selectAll: document.querySelector("#select-all"),
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
  authDialog: document.querySelector("#telegram-auth-dialog"),
  authCopy: document.querySelector("#telegram-auth-copy"),
  authCode: document.querySelector("#telegram-code"),
  authPasswordRow: document.querySelector("#telegram-password-row"),
  authPassword: document.querySelector("#telegram-password"),
  authStatus: document.querySelector("#telegram-auth-status"),
  submitAuthButton: document.querySelector("#submit-auth-button"),
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
  } catch (error) {
    if (!response.ok) throw new Error(`Ошибка запроса: ${response.status} ${response.statusText}`);
    throw error;
  }
  if (!response.ok) {
    let message = "Ошибка запроса";
    if (payload && payload.detail) {
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (Array.isArray(payload.detail)) {
        message = payload.detail.map((item) => item.msg).join("; ");
      } else {
        message = JSON.stringify(payload.detail);
      }
    }
    throw new Error(message);
  }
  return payload;
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
      <button type="button" data-remove-attachment="${index}" aria-label="Удалить вложение">×</button>
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
  const total = state.attachments.reduce((sum, attachment) => sum + attachment.size, 0)
    + files.reduce((sum, file) => sum + file.size, 0);
  if (files.some((file) => !allowed.has(file.type))) {
    showError("Разрешены только PNG, JPEG, WebP, GIF и MP4.");
    return;
  }
  if (files.some((file) => file.size === 0 || file.size > 8 * 1024 * 1024)) {
    showError("Размер каждого вложения должен быть не более 8 МБ.");
    return;
  }
  if (total > 20 * 1024 * 1024) {
    showError("Суммарный размер вложений не должен превышать 20 МБ.");
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
  const availableCount = state.chats.filter((chat) => chat.available).length;
  elements.selectionCount.textContent = `${state.selected.size} выбрано`;
  elements.selectAll.checked = availableCount > 0 && state.selected.size === availableCount;
  elements.planButton.disabled = !state.authorized || state.selected.size === 0 || (!elements.message.value.trim() && state.attachments.length === 0);
  invalidatePlan();
  saveDraft();
}

function renderChats() {
  const query = elements.search.value.trim().toLocaleLowerCase("ru");
  const visible = state.chats.filter((chat) =>
    chat.name.toLocaleLowerCase("ru").includes(query)
  );
  elements.list.innerHTML = visible.map((chat) => `
    <label class="group-row">
      <input type="checkbox" data-alias="${escapeHtml(chat.alias)}"
        ${state.selected.has(chat.alias) ? "checked" : ""}
        ${chat.available ? "" : "disabled"}>
      <span class="group-name" title="${escapeHtml(chat.name)}">
        ${escapeHtml(chat.name)} <small style="opacity:.65;">${escapeHtml(chat.kind)}</small>
      </span>
      <span class="availability ${chat.available ? "" : "offline"}"
        title="${chat.available ? "Доступен" : "Недоступен"}"></span>
    </label>
  `).join("") || '<div class="empty-state">Чаты не найдены.</div>';

  elements.list.querySelectorAll("input[data-alias]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.selected.add(input.dataset.alias);
      else state.selected.delete(input.dataset.alias);
      updateSelection();
    });
  });
}

async function loadStatus() {
  elements.refresh.disabled = true;
  showError();
  try {
    const payload = await api("/api/status");
    applyStatusPayload(payload);
  } catch (error) {
    elements.connectionDot.className = "status-dot error";
    elements.connectionTitle.textContent = "Ошибка";
    elements.connectionCopy.textContent = error.message;
    showError(error.message);
  } finally {
    elements.refresh.disabled = false;
  }
}

function applyStatusPayload(payload) {
    state.phone = payload.phone || "";
    state.authorized = payload.authorized === true;
    state.chats = (payload.chats || []).map((chat) => ({...chat, available: chat.available !== false}));
    elements.phone.value = state.phone || "—";
    elements.authButton.textContent = state.authorized ? "Переавторизовать" : "Войти в Telegram";

    if (state.savedDraftSelected) {
      state.selected = new Set(
        [...state.savedDraftSelected].filter((alias) =>
          state.chats.some((chat) => chat.alias === alias && chat.available)
        )
      );
      state.savedDraftSelected = null;
    } else {
      state.selected = new Set(
        [...state.selected].filter((alias) =>
          state.chats.some((chat) => chat.alias === alias && chat.available)
        )
      );
    }

    if (!payload.connected) {
      elements.connectionDot.className = "status-dot error";
      elements.connectionTitle.textContent = "Ошибка";
    } else if (!state.authorized) {
      elements.connectionDot.className = "status-dot pending";
      elements.connectionTitle.textContent = "Нужен вход";
    } else {
      elements.connectionDot.className = "status-dot";
      elements.connectionTitle.textContent = "Подключено";
    }
    elements.connectionCopy.textContent = payload.message || "—";
    renderChats();
    updateSelection();
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
    elements.planGroups.textContent = `${state.plan.chat_count} ${pluralize(state.plan.chat_count, "чат", "чата", "чатов")} × ${state.plan.repeat_count}`;
    elements.confirmToken.textContent = state.plan.confirm_token;
    elements.planAttachments.textContent = String(state.plan.attachment_count);
    elements.planBox.classList.remove("hidden");
    elements.sendButton.textContent =
      state.plan.repeat_count > 1
        ? `Запустить ${state.plan.repeat_count} ${pluralize(state.plan.repeat_count, "отправку", "отправки", "отправок")}`
        : `Отправить в ${state.plan.chat_count} ${pluralize(state.plan.chat_count, "чат", "чата", "чатов")}`;
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
    const chat = state.chats.find((item) => item.alias === result.alias);
    return `
      <div class="result-row">
        <span>Цикл ${result.round_index}: ${escapeHtml(chat?.name || result.alias)}</span>
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
  elements.attachmentInput.disabled = disabled;
  elements.attachmentPreviews.querySelectorAll("button").forEach((button) => {
    button.disabled = disabled;
  });
  elements.repeatCount.disabled = disabled;
  elements.intervalSelect.disabled = disabled;
  elements.authButton.disabled = disabled;
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
          attachments: state.attachments.map((attachment) => attachment.dataUrl),
          confirm_token: state.plan.confirm_token,
          retry_unknown: false,
          repeat_count: state.plan.repeat_count,
          interval_seconds: state.plan.interval_seconds,
          round_index: round,
        }),
      });
      campaign.results.push(...payload.results.map((result) => ({...result, round_index: round})));
      renderResults(campaign.results);
      updateProgress(round, state.plan.repeat_count);
      if (!payload.complete) break;
      if (round < state.plan.repeat_count) {
        await waitInterval(state.plan.interval_seconds, round + 1);
      }
    }
    playNotificationSound();
    showToast("Кампания завершена", "success");
  } catch (error) {
    showError(error.message);
    showToast(error.message, "error");
  } finally {
    state.campaign = null;
    elements.countdownBox.classList.add("hidden");
    elements.progressContainer.classList.add("hidden");
    setCampaignControls(false);
    invalidatePlan();
    updateSelection();
    loadStats().catch(() => {});
  }
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

function initTheme() {
  const savedTheme = localStorage.getItem("theme");
  const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const isDark = savedTheme === "dark" || (!savedTheme && systemPrefersDark);
  document.documentElement.classList.toggle("dark-theme", isDark);
  updateThemeUI(isDark);
}

function toggleTheme() {
  const isDark = document.documentElement.classList.toggle("dark-theme");
  localStorage.setItem("theme", isDark ? "dark" : "light");
  updateThemeUI(isDark);
}

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
  } catch {}
}

async function loadStats() {
  try {
    const stats = await api("/api/stats");
    elements.statHourly.textContent = stats.hourly_count;
    elements.statDaily.textContent = stats.daily_count;
    elements.statSuccess.textContent = `${stats.success_rate}%`;
    elements.statRemaining.textContent = `${stats.hourly_remaining} / ${stats.daily_remaining}`;
  } catch {}
}

function switchView(viewName) {
  if (viewName === "broadcast") {
    elements.navBroadcast.classList.add("active");
    elements.navHistory.classList.remove("active");
    elements.broadcastView.classList.remove("hidden");
    elements.historyView.classList.add("hidden");
    elements.viewTitle.textContent = "Новая рассылка";
    elements.viewSubtitle.textContent = "Выберите чаты, проверьте сообщение и подтвердите отправку.";
  } else {
    elements.navBroadcast.classList.remove("active");
    elements.navHistory.classList.add("active");
    elements.broadcastView.classList.add("hidden");
    elements.historyView.classList.remove("hidden");
    elements.viewTitle.textContent = "История отправлений";
    elements.viewSubtitle.textContent = "Записи прошлых попыток и текущего сеанса.";
    loadHistory().catch(() => {});
  }
}

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
    const matchesSearch = !query
      || item.alias.toLowerCase().includes(query)
      || item.target_token.toLowerCase().includes(query);
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
    elements.historyTableBody.innerHTML = filtered.map((item) => `
      <tr>
        <td>${escapeHtml(new Date(item.sent_at * 1000).toLocaleString("ru-RU"))}</td>
        <td><strong>${escapeHtml(item.alias)}</strong></td>
        <td><code>${escapeHtml(item.target_token)}</code></td>
        <td><span class="result-status ${escapeHtml(item.status)}">${escapeHtml(labels[item.status] || item.status)}</span></td>
      </tr>
    `).join("");
  }
}

function saveDraft() {
  const draft = {
    message: elements.message.value,
    repeatCount: elements.repeatCount.value,
    interval: elements.intervalSelect.value,
    selected: [...state.selected],
  };
  localStorage.setItem("telegram_draft", JSON.stringify(draft));
}

function restoreDraft() {
  try {
    const raw = localStorage.getItem("telegram_draft");
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
  } catch (error) {
    console.error("Draft restoration failed:", error);
  }
}

async function openTelegramAuth() {
  elements.authStatus.classList.add("hidden");
  elements.authStatus.textContent = "";
  elements.authPasswordRow.classList.add("hidden");
  elements.authPassword.value = "";
  elements.authCode.value = "";
  elements.authCopy.textContent = `Отправим код на номер ${state.phone || "из .env"}.`;
  elements.authDialog.showModal();
  try {
    const payload = await api("/api/auth/request-code", {
      method: "POST",
      body: "{}",
    });
    if (payload.authorized) {
      elements.authStatus.textContent = "Аккаунт уже авторизован.";
      elements.authStatus.classList.remove("hidden");
      await loadStatus();
      setTimeout(() => elements.authDialog.close(), 700);
      return;
    }
    elements.authStatus.textContent = `Код отправлен на ${payload.phone}.`;
    elements.authStatus.classList.remove("hidden");
    elements.authCode.focus();
  } catch (error) {
    elements.authStatus.textContent = error.message;
    elements.authStatus.classList.remove("hidden");
  }
}

async function submitTelegramAuth() {
  elements.authStatus.classList.add("hidden");
  try {
    const payload = await api("/api/auth/complete", {
      method: "POST",
      body: JSON.stringify({
        code: elements.authCode.value.trim(),
        password: elements.authPassword.value || null,
      }),
    });
    if (payload.password_required) {
      elements.authPasswordRow.classList.remove("hidden");
      elements.authStatus.textContent = "Нужен пароль двухэтапной проверки Telegram.";
      elements.authStatus.classList.remove("hidden");
      elements.authPassword.focus();
      return;
    }
    showToast("Telegram авторизован", "success");
    elements.authDialog.close();
    await loadStatus();
  } catch (error) {
    elements.authStatus.textContent = error.message;
    elements.authStatus.classList.remove("hidden");
  }
}

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

function needsStatusHydration() {
  return state.phone === "" || elements.connectionTitle.textContent === "Проверка";
}

async function hydrateStatus(retries = 4, delayMs = 500) {
  let lastError = null;
  for (let attempt = 0; attempt < retries; attempt += 1) {
    try {
      await loadStatus();
      if (!needsStatusHydration()) {
        return;
      }
    } catch (error) {
      lastError = error;
    }
    if (attempt < retries - 1) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }
  if (lastError) {
    console.error("Telegram status hydration failed:", lastError);
  }
}

function refreshDashboard() {
  hydrateStatus().catch((error) => {
    console.error("Telegram status bootstrap failed:", error);
  });
  loadStats().catch(() => {});
}

elements.refresh.addEventListener("click", () => {
  loadStatus().catch(() => {});
  if (!elements.historyView.classList.contains("hidden")) {
    loadHistory().catch(() => {});
  }
});
elements.search.addEventListener("input", renderChats);
elements.selectAll.addEventListener("change", () => {
  state.selected = new Set(
    elements.selectAll.checked
      ? state.chats.filter((chat) => chat.available).map((chat) => chat.alias)
      : []
  );
  renderChats();
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
  elements.dialogCount.textContent = `${state.plan.chat_count} ${pluralize(state.plan.chat_count, "чат", "чата", "чатов")} × ${state.plan.repeat_count} ${pluralize(state.plan.repeat_count, "цикл", "цикла", "циклов")}`;
  elements.dialogToken.textContent = state.plan.confirm_token;
  elements.dialogAttachments.textContent = state.plan.attachment_count
    ? `${state.plan.attachment_count} ${pluralize(state.plan.attachment_count, "вложение", "вложения", "вложений")}.`
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
  if (state.campaign) state.campaign.cancelled = true;
});
elements.authButton.addEventListener("click", openTelegramAuth);
elements.submitAuthButton.addEventListener("click", submitTelegramAuth);
elements.logoutButton.addEventListener("click", async () => {
  await api("/api/logout", {method: "POST", body: "{}"});
  location.href = "/login";
});
elements.themeToggle.addEventListener("click", toggleTheme);
elements.navBroadcast.addEventListener("click", () => switchView("broadcast"));
elements.navHistory.addEventListener("click", () => switchView("history"));
elements.historySearch.addEventListener("input", renderHistory);
elements.historyStatusFilter.addEventListener("change", renderHistory);

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    if (state.plan && !elements.sendButton.disabled && !state.campaign) {
      event.preventDefault();
      elements.sendButton.click();
    }
  }
  if (event.key === "Escape") {
    if (elements.dialog.open) elements.dialog.close();
    if (elements.authDialog.open) elements.authDialog.close();
  }
});

initTheme();
restoreDraft();
if (initialStatus) {
  applyStatusPayload(initialStatus);
}
refreshDashboard();
window.addEventListener("pageshow", () => {
  if (needsStatusHydration()) {
    refreshDashboard();
  }
});
startHistoryAutoRefresh();

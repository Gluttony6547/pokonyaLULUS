"use strict";

const API = "/api/v1";
const WIB = "Asia/Jakarta";
const HORIZONS = [1, 5, 10, 20, 50];

const state = {
  symbols: [],
  symbol: null,
  historyHorizon: "1",
  versions: [],
  jobsTimer: null,
};

const $ = (id) => document.getElementById(id);

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);

const priceFormat = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });

function formatPrice(value) {
  return value === null || value === undefined ? "tidak ada" : priceFormat.format(value);
}

function formatRatio(value) {
  return value === null || value === undefined ? "belum dievaluasi" : value.toFixed(3).replace(".", ",");
}

function formatPercent(value) {
  if (value === null || value === undefined) return "tidak ada";
  const sign = value > 0 ? "+" : value < 0 ? "\u2212" : "";
  return `${sign}${Math.abs(value).toFixed(2).replace(".", ",")}%`;
}

function formatDate(value) {
  if (!value) return "belum ada";
  const parts = String(value).slice(0, 10).split("-");
  const date = new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2])));
  return date.toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
}

function parseTimestamp(value) {
  if (!value) return null;
  const text = String(value);
  if (/Z$|[+-]\d{2}:?\d{2}$/.test(text)) return new Date(text);
  return new Date(`${text.replace(" ", "T")}Z`);
}

function formatTimestamp(value) {
  const date = parseTimestamp(value);
  if (!date || Number.isNaN(date.getTime())) return "belum ada";
  return `${date.toLocaleString("id-ID", {
    timeZone: WIB,
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })} WIB`;
}

function horizonLabel(days) {
  return `T+${days}`;
}

function deltaClass(value) {
  if (value > 0) return "delta-pos";
  if (value < 0) return "delta-neg";
  return "delta-flat";
}

async function api(path, options) {
  const response = await fetch(`${API}${path}`, {
    headers: { Accept: "application/json" },
    ...options,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : `Permintaan gagal (${response.status}).`;
    throw new Error(detail);
  }
  return payload;
}

/* Banners and inline states name the cause and the next action. */

function showBanner(tone, title, detail) {
  const banner = $("banner");
  banner.hidden = false;
  banner.dataset.tone = tone;
  banner.innerHTML = `<p><strong>${escapeHtml(title)}</strong></p>${
    detail ? `<p>${escapeHtml(detail)}</p>` : ""
  }`;
}

function clearBanner() {
  const banner = $("banner");
  banner.hidden = true;
  banner.innerHTML = "";
}

function setState(id, tone, title, detail, action) {
  const node = $(id);
  node.hidden = false;
  node.dataset.tone = tone || "";
  node.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail || "")}</span>${
    action ? `<div class="state-action"></div>` : ""
  }`;
  if (action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button button-quiet";
    button.textContent = action.label;
    button.addEventListener("click", action.run);
    node.querySelector(".state-action").appendChild(button);
  }
}

function hideState(id) {
  const node = $(id);
  node.hidden = true;
  node.innerHTML = "";
}

/* Theme */

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const toggle = $("theme-toggle");
  toggle.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
  toggle.textContent = theme === "dark" ? "Mode terang" : "Mode gelap";
}

function initTheme() {
  const stored = localStorage.getItem("sinyal-theme");
  const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  applyTheme(stored === "dark" || stored === "light" ? stored : preferred);
  $("theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("sinyal-theme", next);
    applyTheme(next);
  });
}

/* Ticker rail */

function renderRail() {
  const rail = $("ticker-rail");
  rail.innerHTML = "";
  state.symbols.forEach((stock) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = stock.symbol;
    button.title = `${stock.name}, harga terakhir ${formatPrice(stock.last_close)}`;
    button.setAttribute("aria-pressed", stock.symbol === state.symbol ? "true" : "false");
    button.addEventListener("click", () => selectSymbol(stock.symbol));
    rail.appendChild(button);
  });
}

function selectSymbol(symbol) {
  state.symbol = symbol;
  renderRail();
  const stock = state.symbols.find((item) => item.symbol === symbol);
  $("signals-sub").textContent = stock
    ? `${stock.name}${stock.sector ? `, ${stock.sector}` : ""}`
    : "";
  loadSymbolPanels();
}

/* Signal panel */

function renderSignals(payload) {
  const stock = state.symbols.find((item) => item.symbol === payload.symbol);
  $("signals-sub").textContent = stock
    ? `${stock.name}${stock.sector ? `, ${stock.sector}` : ""}`
    : payload.symbol;
  $("reference-price").textContent = payload.last_close
    ? `Harga acuan ${formatPrice(payload.last_close)} pada ${formatDate(payload.last_price_date)}`
    : "Harga acuan belum tersedia";

  if (!payload.signals.length) {
    $("signal-body").hidden = true;
    setState(
      "signal-state",
      "",
      `Belum ada sinyal untuk ${payload.symbol}.`,
      "Jalankan pembaruan data, lalu model akan menghasilkan sinyal untuk lima horizon.",
      { label: "Perbarui data sekarang", run: () => runRefresh() },
    );
    return;
  }

  hideState("signal-state");
  const rows = $("signal-rows");
  rows.innerHTML = "";
  payload.signals.forEach((signal) => {
    const ratio = Number(signal.return_pct);
    const row = document.createElement("tr");
    row.innerHTML = `
      <td data-label="Horizon"><span class="horizon">${horizonLabel(signal.horizon_days)}</span>
        <span class="artifact">${escapeHtml(formatDate(signal.data_as_of))}</span></td>
      <td data-label="Sinyal"><span class="chip" data-signal="${escapeHtml(signal.signal)}">${escapeHtml(signal.signal)}</span></td>
      <td data-label="Perkiraan">${formatPrice(signal.predicted_price)}</td>
      <td data-label="Perubahan"><span class="${deltaClass(ratio)}">${formatPercent(ratio)}</span>
        <span class="artifact">ambang ${formatPercent(signal.threshold_pct)}</span></td>
      <td data-label="Tanggal target">${formatDate(signal.target_date)}</td>
      <td data-label="Model"><span class="artifact">${escapeHtml(signal.model_artifact || "belum terdaftar")}</span></td>
    `;
    rows.appendChild(row);

    // The warning text is written by the service once and shown as-is, so the
    // stored record and the page can never disagree about it.
    if (signal.warnings) {
      const noteRow = document.createElement("tr");
      noteRow.className = "note-row";
      const cell = document.createElement("td");
      cell.colSpan = 6;
      cell.textContent = signal.warnings;
      noteRow.appendChild(cell);
      rows.appendChild(noteRow);
    }
  });

  const newest = payload.signals.reduce(
    (latest, item) => (item.data_as_of > latest ? item.data_as_of : latest),
    payload.signals[0].data_as_of,
  );
  $("signal-note").textContent =
    `Semua angka di atas dihitung dari data sampai ${formatDate(newest)}. ` +
    `${payload.signals.length} dari ${HORIZONS.length} horizon punya sinyal.`;
  $("signal-body").hidden = false;
}

async function loadSignals() {
  if (!state.symbol) return;
  setState("signal-state", "", "Memuat sinyal.", `Menunggu respons untuk ${state.symbol}.`);
  try {
    const payload = await api(`/stocks/${state.symbol}/signals`);
    renderSignals(payload);
  } catch (error) {
    $("signal-body").hidden = true;
    setState(
      "signal-state",
      "error",
      "Sinyal tidak bisa dimuat.",
      error.message,
      { label: "Coba lagi", run: () => loadSignals() },
    );
  }
}

/* Price chart and indicator context */

function renderChart(payload) {
  const svg = $("price-chart");
  const caption = $("chart-caption");
  const facts = $("chart-facts");
  svg.innerHTML = "";
  facts.innerHTML = "";

  if (!payload.rows.length) {
    caption.textContent = "Belum ada data harga tersimpan untuk saham ini.";
    return;
  }

  const closes = payload.rows.map((row) => row.close);
  const previous = closes.length > 1 ? closes[0] : null;
  const span = previous === null ? 0 : ((closes[closes.length - 1] - previous) / previous) * 100;
  facts.innerHTML = `
    <dt>Sesi tersimpan</dt><dd>${payload.rows.length}</dd>
    <dt>Terendah</dt><dd>${formatPrice(Math.min(...closes))}</dd>
    <dt>Tertinggi</dt><dd>${formatPrice(Math.max(...closes))}</dd>
    <dt>Perubahan rentang</dt><dd class="${deltaClass(span)}">${formatPercent(span)}</dd>
  `;

  const width = 480;
  const height = 200;
  const padX = 6;
  const padY = 12;
  const closeSeries = closes;
  const sma = payload.context.sma_20;

  let low = Math.min(...closeSeries);
  let high = Math.max(...closeSeries);
  if (sma) {
    low = Math.min(low, sma);
    high = Math.max(high, sma);
  }
  if (high === low) high = low + 1;

  const x = (index) => padX + (index / Math.max(closeSeries.length - 1, 1)) * (width - padX * 2);
  const y = (value) => height - padY - ((value - low) / (high - low)) * (height - padY * 2);

  const path = closeSeries.map((value, index) => `${x(index)},${y(value)}`).join(" ");

  const ns = "http://www.w3.org/2000/svg";
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", path);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "var(--ink)");
  line.setAttribute("stroke-width", "1.6");
  line.setAttribute("vector-effect", "non-scaling-stroke");
  svg.appendChild(line);

  if (sma) {
    const smaLine = document.createElementNS(ns, "line");
    smaLine.setAttribute("x1", String(padX));
    smaLine.setAttribute("x2", String(width - padX));
    smaLine.setAttribute("y1", String(y(sma)));
    smaLine.setAttribute("y2", String(y(sma)));
    smaLine.setAttribute("stroke", "var(--accent)");
    smaLine.setAttribute("stroke-width", "1.4");
    smaLine.setAttribute("stroke-dasharray", "5 4");
    smaLine.setAttribute("vector-effect", "non-scaling-stroke");
    svg.appendChild(smaLine);
  }

  const first = payload.rows[0];
  const last = payload.rows[payload.rows.length - 1];
  caption.innerHTML =
    `<span class="chart-legend"><span>Harga penutup</span> &nbsp; ` +
    `<span class="sma">SMA 20 sesi</span></span><br />` +
    `${formatDate(first.trade_date)} sampai ${formatDate(last.trade_date)}, ` +
    `rentang ${formatPrice(low)} hingga ${formatPrice(high)}.`;
  svg.setAttribute(
    "aria-label",
    `Grafik harga penutup ${payload.symbol} dari ${formatDate(first.trade_date)} sampai ${formatDate(last.trade_date)}, terendah ${formatPrice(low)}, tertinggi ${formatPrice(high)}.`,
  );
}

function renderIndicators(payload) {
  const container = $("indicator-facts");
  if (!payload.rows.length || !payload.context) {
    container.innerHTML =
      "<dt>Indikator</dt><dd>belum cukup data</dd>";
    return;
  }
  const labels = {
    sma_20: "SMA 20",
    sma_50: "SMA 50",
    rsi: "RSI 14",
    macd: "MACD",
    upperband: "Bollinger atas",
    lowerband: "Bollinger bawah",
  };
  container.innerHTML = Object.entries(labels)
    .map(([key, label]) => {
      const value = payload.context[key];
      return `<dt>${escapeHtml(label)}</dt><dd>${
        value === null || value === undefined ? "belum cukup data" : value.toFixed(2).replace(".", ",")
      }</dd>`;
    })
    .join("");
}

async function loadPrices() {
  if (!state.symbol) return;
  try {
    const payload = await api(`/prices/${state.symbol}?limit=180`);
    renderChart(payload);
    renderIndicators(payload);
  } catch (error) {
    $("chart-caption").textContent = `Data harga tidak bisa dimuat: ${error.message}`;
    $("chart-facts").innerHTML = "";
    $("indicator-facts").innerHTML = "";
  }
}

/* History */

function renderHistory(rows) {
  if (!rows.length) {
    $("history-wrap").hidden = true;
    setState(
      "history-state",
      "",
      "Belum ada riwayat untuk horizon ini.",
      "Riwayat terisi setiap kali data diperbarui. Coba horizon lain, atau jalankan pembaruan.",
    );
    return;
  }
  hideState("history-state");
  const body = $("history-rows");
  body.innerHTML = rows
    .map((row) => {
      const ratio = Number(row.return_pct);
      return `
      <tr>
        <td data-label="Data per">${formatDate(row.data_as_of)}</td>
        <td data-label="Sinyal"><span class="chip" data-signal="${escapeHtml(row.signal)}">${escapeHtml(row.signal)}</span></td>
        <td data-label="Harga acuan">${formatPrice(row.last_close)}</td>
        <td data-label="Perkiraan">${formatPrice(row.predicted_price)}</td>
        <td data-label="Perubahan"><span class="${deltaClass(ratio)}">${formatPercent(ratio)}</span></td>
        <td data-label="Tanggal target">${formatDate(row.target_date)}</td>
        <td data-label="Dibuat">${formatTimestamp(row.created_at)}</td>
      </tr>`;
    })
    .join("");
  $("history-wrap").hidden = false;
}

async function loadHistory() {
  if (!state.symbol) return;
  setState("history-state", "", "Memuat riwayat.", "");
  try {
    const rows = await api(
      `/predictions/${state.symbol}?horizon_days=${encodeURIComponent(state.historyHorizon)}&limit=24`,
    );
    renderHistory(rows);
  } catch (error) {
    $("history-wrap").hidden = true;
    setState("history-state", "error", "Riwayat tidak bisa dimuat.", error.message, {
      label: "Coba lagi",
      run: () => loadHistory(),
    });
  }
}

/* Update log */

async function loadUpdates() {
  setState("updates-state", "", "Memuat riwayat pembaruan.", "");
  try {
    const rows = await api("/update-logs?limit=10");
    if (!rows.length) {
      setState(
        "updates-state",
        "",
        "Belum ada pembaruan data tercatat.",
        "Pembaruan pertama akan muncul di sini setelah dijalankan dari tombol di atas.",
      );
      $("update-list").innerHTML = "";
      return;
    }
    hideState("updates-state");
    $("update-list").innerHTML = rows
      .map(
        (row) => `
      <li>
        <span class="log-time">${formatTimestamp(row.run_at)}</span>
        <span class="log-status" data-status="${escapeHtml(row.status)}">${escapeHtml(row.status)}${
          row.trigger_type === "manual" ? " (manual)" : " (jadwal)"
        }</span>
        <span class="log-detail">${row.rows_inserted} baris harga. ${escapeHtml(row.message || "")}</span>
      </li>`,
      )
      .join("");
  } catch (error) {
    setState("updates-state", "error", "Riwayat pembaruan tidak bisa dimuat.", error.message, {
      label: "Coba lagi",
      run: () => loadUpdates(),
    });
  }
}

/* Models and training */

function renderVersions(rows) {
  state.versions = rows;
  if (!rows.length) {
    $("versions-wrap").hidden = true;
    setState(
      "models-state",
      "",
      "Belum ada versi model terdaftar untuk saham ini.",
      "Versi acuan terdaftar otomatis saat pembaruan data pertama dijalankan.",
    );
    return;
  }
  hideState("models-state");
  const body = $("versions-rows");
  body.innerHTML = "";
  rows.forEach((version) => {
    const metrics = version.metrics || {};
    const origin = (version.config && version.config.source) || "tidak diketahui";
    const row = document.createElement("tr");
    row.innerHTML = `
      <td data-label="Horizon"><span class="horizon">${horizonLabel(version.horizon_days)}</span></td>
      <td data-label="Versi">#${version.id}<br /><span class="artifact">${formatTimestamp(version.trained_at)}</span></td>
      <td data-label="Asal">${escapeHtml(origin === "retrained" ? "latih ulang" : "acuan")}</td>
      <td data-label="Akurasi">${
        metrics.accuracy === undefined
          ? "belum dievaluasi"
          : `<span title="${escapeHtml(metrics.source || "")}">${formatRatio(metrics.accuracy)}</span>`
      }</td>
      <td data-label="Presisi">${formatRatio(metrics.precision)}</td>
      <td data-label="Recall">${formatRatio(metrics.recall)}</td>
      <td data-label="F1">${formatRatio(metrics.f1)}</td>
      <td data-label="Berkas"><span class="artifact">${escapeHtml(version.artifact_path.split(/[\\/]/).pop())}</span></td>
      <td data-label="Status"></td>
    `;
    const statusCell = row.querySelector("td[data-label='Status']");
    if (version.is_active) {
      const active = document.createElement("span");
      active.className = "chip";
      active.dataset.signal = "BUY";
      active.textContent = "aktif";
      statusCell.appendChild(active);
    } else {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button button-quiet";
      button.textContent = "Jadikan aktif";
      button.addEventListener("click", () => activateVersion(version.id));
      statusCell.appendChild(button);
    }
    body.appendChild(row);
  });
  $("versions-wrap").hidden = false;
}

async function loadVersions() {
  if (!state.symbol) return;
  setState("models-state", "", "Memuat versi model.", "");
  try {
    const rows = await api(`/model-versions/${state.symbol}`);
    renderVersions(rows);
  } catch (error) {
    $("versions-wrap").hidden = true;
    setState("models-state", "error", "Versi model tidak bisa dimuat.", error.message, {
      label: "Coba lagi",
      run: () => loadVersions(),
    });
  }
}

async function activateVersion(versionId) {
  try {
    await api(`/model-versions/${versionId}/activate`, { method: "POST" });
    showBanner("ok", `Versi #${versionId} sekarang aktif.`, "Sinyal berikutnya memakai versi ini.");
    await Promise.all([loadVersions(), loadSignals()]);
  } catch (error) {
    showBanner("error", "Versi model gagal diaktifkan.", error.message);
  }
}

function renderJobs(rows) {
  const list = $("jobs-list");
  if (!rows.length) {
    list.innerHTML = `<li><span class="log-time">belum ada</span><span class="log-status">-</span><span class="log-detail">Setiap permintaan pelatihan akan muncul di sini beserta statusnya.</span></li>`;
    return;
  }
  list.innerHTML = rows
    .map(
      (job) => `
    <li>
      <span class="log-time">${formatTimestamp(job.requested_at)}</span>
      <span class="log-status" data-status="${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
      <span class="log-detail">${escapeHtml(job.symbol)} ${horizonLabel(job.horizon_days)}${
        job.error_message ? `: ${escapeHtml(job.error_message)}` : ""
      }${job.model_version_id ? `, versi #${job.model_version_id}` : ""}</span>
    </li>`,
    )
    .join("");
}

async function loadJobs() {
  try {
    const rows = await api("/training-jobs?limit=10");
    renderJobs(rows);
    const active = rows.some((job) => job.status === "queued" || job.status === "running");
    if (active) startJobPolling();
    else stopJobPolling();
  } catch (error) {
    $("jobs-list").innerHTML = `<li><span class="log-time">galat</span><span class="log-status" data-status="failed">failed</span><span class="log-detail">${escapeHtml(error.message)}</span></li>`;
  }
}

/* A run is the only thing worth polling for, so polling starts and stops with one. */

function startJobPolling() {
  if (state.jobsTimer !== null) return;
  state.jobsTimer = window.setInterval(async () => {
    try {
      const rows = await api("/training-jobs?limit=10");
      renderJobs(rows);
      const active = rows.some((job) => job.status === "queued" || job.status === "running");
      if (!active) {
        stopJobPolling();
        await Promise.all([loadVersions(), loadJobs()]);
      }
    } catch (error) {
      stopJobPolling();
    }
  }, 6000);
}

function stopJobPolling() {
  if (state.jobsTimer === null) return;
  window.clearInterval(state.jobsTimer);
  state.jobsTimer = null;
}

async function submitTraining(event) {
  event.preventDefault();
  const button = $("train-submit");
  const horizon = Number($("train-horizon").value);
  button.disabled = true;
  button.textContent = "Mengantre";
  try {
    const result = await api("/training-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        symbol: state.symbol,
        horizon_days: horizon,
        force: $("train-force").checked,
      }),
    });
    showBanner(result.reused ? "warn" : "ok", result.message, null);
    await loadJobs();
  } catch (error) {
    showBanner("error", "Pelatihan tidak bisa dimulai.", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Latih model";
  }
}

/* Manual data update */

async function runRefresh() {
  const button = $("refresh-button");
  button.disabled = true;
  button.textContent = "Memperbarui";
  showBanner("warn", "Pembaruan data berjalan.", "Mengambil harga harian dari penyedia dan menghitung ulang sinyal.");
  try {
    const entry = await api("/update-logs/refresh", { method: "POST" });
    const tone = entry.status === "success" ? "ok" : "warn";
    showBanner(tone, `Pembaruan selesai dengan status ${entry.status}.`, entry.message);
    await loadAll();
  } catch (error) {
    showBanner("error", "Pembaruan data gagal.", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Perbarui data sekarang";
  }
}

/* System status */

async function loadHealth() {
  try {
    const health = await api("/health");
    const pieces = [];
    if (health.last_update) {
      pieces.push(
        `Pembaruan terakhir ${formatTimestamp(health.last_update.run_at)} (${health.last_update.status})`,
      );
    } else {
      pieces.push("Belum ada pembaruan data tercatat");
    }
    if (health.pending_slot) {
      pieces.push(`slot jadwal ${formatTimestamp(health.pending_slot)} masih menunggu`);
    }
    $("freshness").textContent = pieces.join(", ");

    const facts = $("freshness-facts");
    const artifacts = Object.entries(health.artifacts || {});
    const complete = artifacts.filter(([, count]) => count === HORIZONS.length).length;
    facts.innerHTML = `
      <dt>Penyimpanan</dt><dd>${escapeHtml(health.storage_backend)}</dd>
      <dt>Baris harga</dt><dd>${priceFormat.format(health.price_rows)}</dd>
      <dt>Baris sinyal</dt><dd>${priceFormat.format(health.prediction_rows)}</dd>
      <dt>Berkas model lengkap</dt><dd>${complete} dari ${artifacts.length} emiten</dd>
      <dt>Jadwal pembaruan</dt><dd>16:05 dan 18:00 WIB</dd>
    `;
  } catch (error) {
    $("freshness").textContent = "Status layanan tidak bisa dimuat.";
    $("freshness-facts").innerHTML = `<dt>Galat</dt><dd>${escapeHtml(error.message)}</dd>`;
  }
}

/* Panels that follow the selected ticker, kept apart from the system panels so a
   ticker change does not refetch the service-wide status. */
async function loadSymbolPanels() {
  await Promise.all([loadSignals(), loadPrices(), loadHistory(), loadVersions()]);
}

async function loadAll() {
  await Promise.all([loadHealth(), loadUpdates(), loadJobs(), loadSymbolPanels()]);
}

async function boot() {
  initTheme();
  HORIZONS.forEach((days) => {
    [ $("history-horizon"), $("train-horizon") ].forEach((select) => {
      const option = document.createElement("option");
      option.value = String(days);
      option.textContent = horizonLabel(days);
      select.appendChild(option);
    });
  });
  $("history-horizon").addEventListener("change", (event) => {
    state.historyHorizon = event.target.value;
    loadHistory();
  });
  $("train-form").addEventListener("submit", submitTraining);
  $("refresh-button").addEventListener("click", runRefresh);

  setState("signal-state", "", "Memuat daftar saham.", "Mengambil daftar emiten terdaftar.");
  try {
    state.symbols = await api("/stocks");
  } catch (error) {
    setState("signal-state", "error", "Daftar saham tidak bisa dimuat.", error.message, {
      label: "Coba lagi",
      run: boot,
    });
    return;
  }
  if (!state.symbols.length) {
    setState(
      "signal-state",
      "",
      "Belum ada emiten terdaftar.",
      "Jalankan perintah seed pada layanan untuk mengisi daftar emiten dan kalender libur bursa.",
    );
    return;
  }
  selectSymbol(state.symbols[0].symbol);
  await Promise.all([loadHealth(), loadUpdates(), loadJobs()]);
}

document.addEventListener("DOMContentLoaded", boot);

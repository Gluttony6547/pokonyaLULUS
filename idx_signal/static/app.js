"use strict";

const API = "/api/v1";
const WIB = "Asia/Jakarta";
const HORIZONS = [1, 5, 10, 20, 50];
const WINDOW = Math.max(...HORIZONS);

const state = {
  symbols: [],
  symbol: null,
  historyHorizon: "1",
  versions: [],
  jobsTimer: null,
  quoteTimer: null,
  quoteLoading: false,
  quote: null,
  referenceClose: null,
  referenceCloseDate: null,
  referenceDate: null,
  rejectedReference: false,
  signalRequest: 0,
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
const rangePriceFormat = new Intl.NumberFormat("id-ID", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

function formatPrice(value) {
  return value === null || value === undefined ? "belum tersedia" : priceFormat.format(value);
}

function formatRangeBoundary(value) {
  return rangePriceFormat.format(value);
}

function anchorPrice(signal, historical) {
  return historical ? signal.reference_close : signal.last_close;
}

function formatPriceRange(signal, referencePrice) {
  if (signal.threshold_pct === null || signal.threshold_pct === undefined || signal.threshold_pct === "") {
    return "belum tersedia";
  }
  const threshold = Number(signal.threshold_pct);
  if (!Number.isFinite(referencePrice) || referencePrice <= 0 || !Number.isFinite(threshold) || threshold < 0) {
    return "belum tersedia";
  }
  const lower = referencePrice * (1 - threshold / 100);
  const upper = referencePrice * (1 + threshold / 100);
  if (signal.signal === "BUY") return `≥ ${formatRangeBoundary(upper)}`;
  if (signal.signal === "SELL") return `≤ ${formatRangeBoundary(lower)}`;
  if (signal.signal === "HOLD") {
    return `${formatRangeBoundary(lower)} - ${formatRangeBoundary(upper)}`;
  }
  return "belum tersedia";
}

function formatRatio(value) {
  return value === null || value === undefined ? "belum dievaluasi" : value.toFixed(3).replace(".", ",");
}

function formatPercent(value) {
  if (value === null || value === undefined) return "belum tersedia";
  const sign = value > 0 ? "+" : value < 0 ? "\u2212" : "";
  return `${sign}${Math.abs(value).toFixed(2).replace(".", ",")}%`;
}

function formatAbsPercent(value) {
  if (value === null || value === undefined) return "belum tersedia";
  return `${Math.abs(value).toFixed(2).replace(".", ",")}%`;
}

function formatDate(value) {
  if (!value) return "belum ada";
  const parts = String(value).slice(0, 10).split("-");
  const date = new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2])));
  return date.toLocaleDateString("id-ID", {
    timeZone: WIB,
    day: "numeric",
    month: "short",
    year: "numeric",
  });
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

function dateInWib(value) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: WIB,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  const fields = Object.fromEntries(parts.map(({ type, value: part }) => [type, part]));
  return `${fields.year}-${fields.month}-${fields.day}`;
}

function isWibMarketOpen() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: WIB,
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date()).map(({ type, value }) => [type, value]),
  );
  const minuteOfDay = Number(parts.hour) * 60 + Number(parts.minute);
  return !["Sat", "Sun"].includes(parts.weekday) && minuteOfDay >= 9 * 60 && minuteOfDay < 16 * 60 + 15;
}

function updateStatusLabel(status) {
  return ({
    success: "berhasil",
    partial: "sebagian berhasil",
    failed: "gagal",
    skipped: "dilewati",
    queued: "dalam antrean",
    running: "sedang berjalan",
  })[status] || status;
}

function formatSector(sector) {
  return ({
    Energy: "Energi",
    "Basic Materials": "Bahan baku",
    Financials: "Keuangan",
    "Communication Services": "Jasa komunikasi",
    Utilities: "Utilitas",
  })[sector] || sector;
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
  let payload = null;
  let parsed = true;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      parsed = false;
    }
  }
  if (!response.ok) {
    const detail = payload && payload.detail;
    const detailText =
      typeof detail === "string"
        ? detail
        : detail && typeof detail.message === "string"
          ? detail.message
          : "";
    const fallback = parsed
      ? `Permintaan gagal (${response.status}).`
      : `Server mengembalikan respons yang tidak bisa dibaca (HTTP ${response.status}).`;
    const error = new Error(detailText || fallback);
    error.status = response.status;
    throw error;
  }
  if (!parsed) throw new Error("Respons server tidak bisa dibaca.");
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
  state.quote = null;
  state.quoteLoading = false;
  state.rejectedReference = false;
  state.referenceClose = null;
  state.referenceCloseDate = null;
  state.referenceDate = null;
  $("reference-date").value = "";
  $("latest-signals").hidden = true;
  setDateMessage("");
  applyDateBounds();
  renderRail();
  const stock = state.symbols.find((item) => item.symbol === symbol);
  $("signals-sub").textContent = stock
    ? `${stock.name}${stock.sector ? ` · ${formatSector(stock.sector)}` : ""}`
    : "";
  loadSymbolPanels();
  writeUrlState();
}

/* Reference date */

function currentStock() {
  return state.symbols.find((item) => item.symbol === state.symbol) || null;
}

function referenceBounds(stock = currentStock()) {
  return {
    min: stock?.first_usable_reference_date || "",
    max: stock?.last_price_date || "",
    sessions: stock?.price_session_count || 0,
  };
}

function applyDateBounds() {
  const stock = currentStock();
  if (!stock) return;
  const input = $("reference-date");
  const { min, max, sessions } = referenceBounds(stock);
  input.min = min;
  input.max = max;
  input.disabled = !min || !max;
  if (!max) {
    $("date-hint").textContent = `Belum ada harga tersimpan untuk ${stock.symbol}. Perbarui harga untuk mengisi rentang tanggal.`;
  } else if (!min) {
    $("date-hint").textContent = `${stock.symbol} baru punya ${sessions} sesi harga. Model membutuhkan ${WINDOW} sesi. Perbarui harga untuk mengisi rentang tanggal.`;
  } else {
    $("date-hint").textContent = `Model memakai ${WINDOW} sesi terakhir. Tanggal paling awal yang bisa dihitung: ${formatDate(min)}. Data tersedia sampai ${formatDate(max)}.`;
  }
}

function setDateMessage(message) {
  $("date-message").textContent = message || "";
  $("reference-date").setAttribute("aria-invalid", message ? "true" : "false");
}

function renderActiveDate(value) {
  $("date-active").textContent = `Tanggal acuan aktif: ${value}`;
}

function clearReferencePrice() {
  state.referenceClose = null;
  state.referenceCloseDate = null;
  renderReferencePrice();
}

function clearSignalView() {
  $("signal-body").hidden = true;
  hideState("signal-state");
  clearReferencePrice();
  renderActiveDate("tidak tersedia");
}

function isIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
  );
}

function referenceDateProblem(value) {
  if (!value) return null;
  const { min, max } = referenceBounds();
  if (!isIsoDate(value)) return "Tanggal acuan harus berformat YYYY-MM-DD.";
  if (!min || !max) {
    return `Tanggal acuan belum tersedia untuk ${currentStock()?.symbol || "saham ini"}.`;
  }
  if (value < min || value > max) {
    return `Tanggal ${formatDate(value)} di luar rentang data ${formatDate(min)} sampai ${formatDate(max)}.`;
  }
  return null;
}

function rejectReferenceDate(message) {
  // Bump the token so an in-flight response cannot overwrite this message.
  state.signalRequest += 1;
  state.rejectedReference = true;
  state.referenceDate = null;
  setDateMessage(message);
  clearSignalView();
  $("signals-heading").textContent = "Sinyal terbaru";
  $("latest-signals").hidden = false;
  writeUrlState();
}

async function applyReferenceDate(value) {
  const problem = referenceDateProblem(value);
  if (problem) {
    rejectReferenceDate(problem);
    return;
  }
  setDateMessage("");
  state.rejectedReference = false;
  state.referenceDate = value || null;
  $("latest-signals").hidden = !state.referenceDate;
  writeUrlState();
  await loadSignals();
}

/* Signal panel */

function outcomeLabel(signal) {
  if (signal.outcome_status === "realized") {
    return signal.direction_correct ? "tepat" : "meleset";
  }
  if (signal.outcome_status === "pending") return "belum terjadi";
  if (signal.outcome_status === "no_price") return "tidak ada harga";
  if (signal.outcome_status === "corporate_action") return "aksi korporasi";
  return "belum dinilai";
}

function renderActual(signal) {
  if (signal.actual_close === null || signal.actual_close === undefined) {
    if (signal.outcome_status === "pending") {
      return `Belum terjadi. Target ${formatDate(signal.target_date)}.`;
    }
    if (signal.outcome_status === "no_price") return "Harga target belum tersedia.";
    if (signal.outcome_status === "corporate_action") {
      return "Aksi korporasi di jendela target. Hasil tidak dinilai.";
    }
    return "belum tersedia";
  }
  if (signal.outcome_status === "corporate_action") {
    return `${formatPrice(signal.actual_close)} · ${formatDate(signal.actual_date)} ` +
      `<span class="artifact">aksi korporasi</span>`;
  }
  if (signal.outcome_approximate) {
    return `${formatPrice(signal.actual_close)} · Sesi terdekat: ${formatDate(signal.actual_date)}`;
  }
  return `${formatPrice(signal.actual_close)} · ${formatDate(signal.actual_date)}`;
}

function renderOutcome(signal) {
  const label = outcomeLabel(signal);
  return `<span class="outcome" data-correct="${
    signal.direction_correct === true
  }">${escapeHtml(label)}</span>`;
}

function renderScorecard(payload, historical) {
  const node = $("scorecard-summary");
  if (!node) return;
  const score = payload.scorecard;
  if (!historical || !score || !score.realized) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  const parts = [
    `${score.realized} dari ${payload.signals.length} horizon sudah terealisasi.`,
  ];
  if (score.direction_total > 0) {
    parts.push(`Arah tepat ${score.direction_correct} dari ${score.direction_total}.`);
  }
  if (score.mean_abs_error_pct !== null && score.mean_abs_error_pct !== undefined) {
    parts.push(`Rata-rata selisih absolut ${formatAbsPercent(score.mean_abs_error_pct)}.`);
  }
  node.textContent = parts.join(" ");
  node.hidden = false;
}

function renderSignals(payload) {
  const historical = Boolean(state.referenceDate);
  const stock = currentStock();
  $("signals").dataset.mode = historical ? "historical" : "latest";
  $("signals-heading").textContent = historical ? "Sinyal historis" : "Sinyal terbaru";
  $("signals-sub").textContent = stock
    ? `${stock.name}${stock.sector ? ` · ${formatSector(stock.sector)}` : ""}`
    : payload.symbol;
  state.referenceClose = anchorPrice(payload, historical);
  state.referenceCloseDate = historical ? payload.reference_date : payload.last_price_date;
  renderReferencePrice();
  renderActiveDate(formatDate(historical ? payload.reference_date : payload.last_price_date));
  renderScorecard(payload, historical);
  const historicalNote = $("historical-note");
  historicalNote.textContent = historical
    ? "Dihitung ulang dengan model yang aktif sekarang, bukan sinyal yang tersimpan pada tanggal itu."
    : "";
  historicalNote.hidden = !historical;

  const warnings = payload.warnings || [];
  $("signal-warnings").innerHTML = warnings
    .map((warning) => `<li>${escapeHtml(warning)}</li>`)
    .join("");
  $("signal-warnings").hidden = warnings.length === 0;

  if (!payload.signals.length) {
    $("signal-body").hidden = true;
    setState(
      "signal-state",
      "",
      historical
        ? `Tidak ada sinyal pada ${formatDate(payload.reference_date)}.`
        : `Belum ada sinyal untuk ${payload.symbol}.`,
      historical
        ? "Pilih tanggal lain atau kembali ke sinyal terbaru."
        : "Perbarui harga untuk menghitung sinyal pada lima rentang waktu.",
      historical ? null : { label: "Perbarui harga", run: () => runRefresh() },
    );
    return;
  }

  hideState("signal-state");
  const rows = $("signal-rows");
  rows.innerHTML = "";
  payload.signals.forEach((signal) => {
    const error = signal.prediction_error_pct;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td data-label="Rentang waktu"><span class="horizon">${horizonLabel(signal.horizon_days)}</span>
        <span class="artifact">${escapeHtml(formatDate(signal.data_as_of))}</span></td>
      <td data-label="Sinyal"><span class="chip" data-signal="${escapeHtml(signal.signal)}">${escapeHtml(signal.signal)}</span></td>
      <td data-label="Rentang harga">${formatPriceRange(signal, anchorPrice(signal, historical))}</td>
      <td data-label="Threshold">±${formatAbsPercent(signal.threshold_pct)}</td>
      <td class="outcome-col" data-label="Harga aktual">${renderActual(signal)}</td>
      <td class="outcome-col" data-label="Selisih">${
        error === null || error === undefined ? "belum tersedia" : formatPercent(error)
      }</td>
      <td class="outcome-col" data-label="Arah">${renderOutcome(signal)}</td>
      <td data-label="Tanggal prediksi">${formatDate(signal.target_date)}</td>
      <td data-label="Model"><span class="artifact">${escapeHtml(signal.model_artifact || "belum terdaftar")}</span></td>
    `;
    rows.appendChild(row);

    // The warning text is written by the service once and shown as-is, so the
    // stored record and the page can never disagree about it.
    if (signal.warnings) {
      const noteRow = document.createElement("tr");
      noteRow.className = "note-row";
      const cell = document.createElement("td");
      cell.colSpan = historical ? 9 : 6;
      cell.textContent = signal.warnings;
      noteRow.appendChild(cell);
      rows.appendChild(noteRow);
    }
  });

  const newest = payload.signals.reduce(
    (latest, item) => (item.data_as_of > latest ? item.data_as_of : latest),
    payload.signals[0].data_as_of,
  );
  $("signal-note").textContent = historical
    ? `Harga acuan ${formatDate(newest)}. Tanggal target mengikuti sesi bursa IDX; ` +
      "hasil ini tidak disimpan sebagai sinyal operasional."
    : `Sinyal memakai harga penutupan ${formatDate(newest)}; harga intrahari hanya untuk pantauan. ` +
      "Tanggal prediksi dihitung dari hari ini. " +
      `${payload.signals.length} dari ${HORIZONS.length} rentang waktu memiliki sinyal.`;
  $("signal-body").hidden = false;
}

async function loadSignals() {
  if (!state.symbol) return;
  const symbol = state.symbol;
  const reference = state.referenceDate;
  const request = ++state.signalRequest;
  const historical = Boolean(reference);
  $("signal-body").hidden = true;
  clearReferencePrice();
  renderActiveDate("memuat…");
  setState(
    "signal-state",
    "",
    historical ? "Menghitung ulang sinyal…" : "Memuat sinyal…",
    historical
      ? `Memakai harga penutupan sampai ${formatDate(reference)}.`
      : `Meminta data ${symbol}.`,
  );
  try {
    const payload = historical
      ? await api(`/stocks/${symbol}/signals/historical?date=${encodeURIComponent(reference)}`)
      : await api(`/stocks/${symbol}/signals`);
    if (request !== state.signalRequest) return;
    renderSignals(payload);
  } catch (error) {
    if (request !== state.signalRequest) return;
    if (historical && error.status === 422) {
      rejectReferenceDate(error.message);
      return;
    }
    clearSignalView();
    setState(
      "signal-state",
      "error",
      "Sinyal belum bisa ditampilkan.",
      error.message,
      { label: "Coba lagi", run: () => loadSignals() },
    );
  }
}

function renderReferencePrice() {
  if (state.rejectedReference) {
    $("reference-price").textContent = "Harga acuan belum tersedia";
    return;
  }
  if (state.referenceDate) {
    $("reference-price").textContent =
      state.referenceClose === null
        ? "Harga acuan belum tersedia"
        : `Harga acuan ${formatPrice(state.referenceClose)} · ${formatDate(state.referenceCloseDate)}`;
    return;
  }
  const quote = state.quote;
  const quoteIsToday = quote && dateInWib(quote.observed_at) === dateInWib(new Date());
  if (quoteIsToday) {
    $("reference-price").textContent =
      `Harga intrahari ${formatPrice(quote.price)} · ${formatTimestamp(quote.observed_at)}`;
    return;
  }
  $("reference-price").textContent = state.referenceClose !== null
    ? `Harga penutupan ${formatPrice(state.referenceClose)} · ${formatDate(state.referenceCloseDate)}`
    : "Harga belum tersedia";
}

async function loadQuote() {
  if (!state.symbol || state.quoteLoading || state.referenceDate) return;
  state.quoteLoading = true;
  const symbol = state.symbol;
  try {
    const quote = await api(`/quotes/${symbol}`);
    if (state.symbol === symbol) {
      state.quote = quote;
      renderReferencePrice();
    }
  } catch {
    if (state.symbol === symbol) {
      state.quote = null;
      renderReferencePrice();
    }
  } finally {
    state.quoteLoading = false;
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
    caption.textContent = "Belum ada riwayat harga untuk saham ini.";
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
  const symbol = state.symbol;
  try {
    const payload = await api(`/prices/${symbol}?limit=180`);
    if (state.symbol !== symbol) return;
    renderChart(payload);
    renderIndicators(payload);
  } catch (error) {
    if (state.symbol !== symbol) return;
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
      "Belum ada sinyal untuk rentang waktu ini.",
      "Riwayat akan muncul setelah harga diperbarui. Pilih rentang waktu lain atau perbarui harga.",
    );
    return;
  }
  hideState("history-state");
  const body = $("history-rows");
  body.innerHTML = rows
    .map((row) => {
      return `
      <tr>
        <td data-label="Tanggal harga">${formatDate(row.data_as_of)}</td>
        <td data-label="Sinyal"><span class="chip" data-signal="${escapeHtml(row.signal)}">${escapeHtml(row.signal)}</span></td>
        <td data-label="Harga acuan">${formatPrice(row.last_close)}</td>
        <td data-label="Rentang harga">${formatPriceRange(row, anchorPrice(row, false))}</td>
        <td data-label="Threshold">±${formatAbsPercent(row.threshold_pct)}</td>
        <td data-label="Tanggal prediksi">${formatDate(row.target_date)}</td>
        <td data-label="Waktu dibuat">${formatTimestamp(row.created_at)}</td>
      </tr>`;
    })
    .join("");
  $("history-wrap").hidden = false;
}

async function loadHistory() {
  if (!state.symbol) return;
  const symbol = state.symbol;
  const horizon = state.historyHorizon;
  setState("history-state", "", "Memuat riwayat…", "");
  try {
    const rows = await api(
      `/predictions/${symbol}?horizon_days=${encodeURIComponent(horizon)}&limit=24`,
    );
    if (state.symbol !== symbol || state.historyHorizon !== horizon) return;
    renderHistory(rows);
  } catch (error) {
    if (state.symbol !== symbol || state.historyHorizon !== horizon) return;
    $("history-wrap").hidden = true;
    setState("history-state", "error", "Riwayat tidak bisa dimuat.", error.message, {
      label: "Coba lagi",
      run: () => loadHistory(),
    });
  }
}

/* Update log */

async function loadUpdates() {
  setState("updates-state", "", "Memuat riwayat pembaruan…", "");
  try {
    const rows = await api("/update-logs?limit=10");
    if (!rows.length) {
      setState(
        "updates-state",
        "",
        "Belum ada catatan pembaruan harga.",
        "Catatan pembaruan akan muncul di sini setelah kamu memperbarui harga.",
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
        <span class="log-status" data-status="${escapeHtml(row.status)}">${escapeHtml(updateStatusLabel(row.status))}${
          row.trigger_type === "manual" ? " (manual)" : " · otomatis"
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
      "Model untuk saham ini belum tercatat.",
      "Model acuan akan tercatat saat harga pertama kali diperbarui.",
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
      <td data-label="Rentang waktu"><span class="horizon">${horizonLabel(version.horizon_days)}</span></td>
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
  const symbol = state.symbol;
  setState("models-state", "", "Memuat versi model.", "");
  try {
    const rows = await api(`/model-versions/${symbol}`);
    if (state.symbol !== symbol) return;
    renderVersions(rows);
  } catch (error) {
    if (state.symbol !== symbol) return;
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
      <span class="log-status" data-status="${escapeHtml(job.status)}">${escapeHtml(updateStatusLabel(job.status))}</span>
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
    $("jobs-list").innerHTML = `<li><span class="log-time">galat</span><span class="log-status" data-status="failed">gagal</span><span class="log-detail">${escapeHtml(error.message)}</span></li>`;
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
  showBanner("warn", "Harga sedang diperbarui.", "Mengambil harga terbaru dan menghitung ulang sinyal. Proses ini bisa memakan waktu.");
  try {
    const entry = await api("/update-logs/refresh", { method: "POST" });
    const tone = entry.status === "success" ? "ok" : "warn";
    showBanner(tone, `Pembaruan ${updateStatusLabel(entry.status)}.`, entry.message);
    await loadAll();
  } catch (error) {
    showBanner("error", "Harga belum berhasil diperbarui.", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Perbarui harga";
  }
}

/* System status */

async function loadHealth() {
  try {
    const health = await api("/health");
    const pieces = [];
    if (health.last_update) {
      pieces.push(
        `Terakhir diperbarui ${formatTimestamp(health.last_update.run_at)} (${updateStatusLabel(health.last_update.status)})`,
      );
    } else {
      pieces.push("Belum ada pembaruan data tercatat");
    }
    if (health.pending_slot) {
      pieces.push(`Pembaruan otomatis berikutnya: ${formatTimestamp(health.pending_slot)}`);
    }
    $("freshness").textContent = pieces.join(", ");

    const facts = $("freshness-facts");
    const artifacts = Object.entries(health.artifacts || {});
    const complete = artifacts.filter(([, count]) => count === HORIZONS.length).length;
    facts.innerHTML = `
      <dt>Penyimpanan</dt><dd>${escapeHtml(health.storage_backend)}</dd>
      <dt>Catatan harga</dt><dd>${priceFormat.format(health.price_rows)}</dd>
      <dt>Riwayat sinyal</dt><dd>${priceFormat.format(health.prediction_rows)}</dd>
      <dt>Model lengkap</dt><dd>${complete} dari ${artifacts.length} emiten</dd>
      <dt>Jadwal pembaruan</dt><dd>16:05 dan 18:00 WIB</dd>
    `;
  } catch (error) {
    $("freshness").textContent = "Status aplikasi belum bisa dimuat.";
    $("freshness-facts").innerHTML = `<dt>Galat</dt><dd>${escapeHtml(error.message)}</dd>`;
  }
}

/* Panels that follow the selected ticker, kept apart from the system panels so a
   ticker change does not refetch the service-wide status. */
async function loadSymbolPanels() {
  await Promise.all([loadQuote(), loadSignals(), loadPrices(), loadHistory(), loadVersions()]);
}

async function loadAll() {
  // A refresh can move the newest price date, which bounds the date control.
  try {
    await loadStocks();
  } catch (error) {
    $("date-hint").textContent =
      `Rentang tanggal gagal diperbarui (${error.message}). Batas yang tampil masih dari pemuatan sebelumnya.`;
  }
  await Promise.all([loadHealth(), loadUpdates(), loadJobs(), loadSymbolPanels()]);
}

async function loadStocks() {
  state.symbols = await api("/stocks");
  renderRail();
  applyDateBounds();
}

function readUrlState() {
  const params = new URLSearchParams(window.location.search);
  return {
    symbol: (params.get("symbol") || "").trim().toUpperCase(),
    date: (params.get("date") || "").trim(),
    horizon: (params.get("horizon") || "").trim(),
  };
}

function writeUrlState() {
  if (!state.symbol) return;
  const params = new URLSearchParams();
  params.set("symbol", state.symbol);
  if (state.referenceDate) params.set("date", state.referenceDate);
  params.set("horizon", state.historyHorizon);
  window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
}

let controlsBound = false;

function initControls() {
  if (controlsBound) return;
  controlsBound = true;
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
    writeUrlState();
    loadHistory();
  });
  $("train-form").addEventListener("submit", submitTraining);
  $("refresh-button").addEventListener("click", runRefresh);
  $("reference-date").addEventListener("change", (event) => {
    applyReferenceDate(event.target.value || null);
  });
  $("latest-signals").addEventListener("click", () => {
    $("reference-date").value = "";
    applyReferenceDate(null);
  });
}

async function boot() {
  initControls();

  setState("signal-state", "", "Memuat daftar saham…", "Menyiapkan pilihan saham.");
  try {
    await loadStocks();
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
      "Daftar saham masih kosong.",
      "Daftar saham dan kalender bursa belum disiapkan di server.",
    );
    return;
  }

  const url = readUrlState();
  const known = state.symbols.some((item) => item.symbol === url.symbol);
  if (HORIZONS.map(String).includes(url.horizon)) {
    state.historyHorizon = url.horizon;
    $("history-horizon").value = url.horizon;
  }
  selectSymbol(known ? url.symbol : state.symbols[0].symbol);
  if (known && url.date) {
    const problem = referenceDateProblem(url.date);
    if (problem) {
      setDateMessage("Tanggal di tautan tidak bisa dipakai. Menampilkan sinyal terbaru.");
      $("reference-date").value = "";
      writeUrlState();
    } else {
      $("reference-date").value = url.date;
      await applyReferenceDate(url.date);
    }
  } else {
    writeUrlState();
  }
  await Promise.all([loadHealth(), loadUpdates(), loadJobs()]);
  if (state.quoteTimer) window.clearInterval(state.quoteTimer);
  state.quoteTimer = window.setInterval(() => {
    if (isWibMarketOpen()) loadQuote();
  }, 60_000);
}

document.addEventListener("DOMContentLoaded", boot);

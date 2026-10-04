"use strict";

/*
 * Prog5 dashboard. Reads only the read-only endpoints that already exist:
 * /api/v1/health, /stocks, /runs, /prices/{symbol}, /predictions/latest/{symbol}
 * and /predictions/{symbol}?horizon_days=. It never writes anything.
 */

const API = {
  health: "/api/v1/health",
  stocks: "/api/v1/stocks",
  runs: "/api/v1/runs?limit=10",
  prices: (symbol) => `/api/v1/prices/${encodeURIComponent(symbol)}?limit=180`,
  latest: (symbol) => `/api/v1/predictions/latest/${encodeURIComponent(symbol)}`,
  history: (symbol, horizon) =>
    `/api/v1/predictions/${encodeURIComponent(symbol)}?horizon_days=${horizon}&limit=50`,
};

const HORIZONS = [1, 5, 10, 20, 50];

const state = {
  symbol: null,
  horizon: 1,
  tickers: [],
  artifacts: {},
  seq: 0,
};

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const integerFormat = new Intl.NumberFormat("en-US");

function $(id) {
  return document.getElementById(id);
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    switch (character) {
      case "&": return "&amp;";
      case "<": return "&lt;";
      case ">": return "&gt;";
      case '"': return "&quot;";
      default: return "&#39;";
    }
  });
}

function fmtNumber(value) {
  return value === null || value === undefined || Number.isNaN(value) ? "n/a" : numberFormat.format(value);
}

function fmtPercent(value) {
  if (value === null || value === undefined) {
    return "n/a";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function fmtDate(iso) {
  if (!iso) {
    return "n/a";
  }
  const date = new Date(`${iso}T00:00:00Z`);
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
}

function fmtDateTime(iso) {
  if (!iso) {
    return "n/a";
  }
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalized);
  return date.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function daysSince(iso) {
  const then = Date.parse(`${iso}T00:00:00Z`);
  return Math.max(0, Math.floor((Date.now() - then) / 86400000));
}

function freshness(iso) {
  const age = daysSince(iso);
  const label = age === 0 ? "today" : age === 1 ? "1 day old" : `${age} days old`;
  if (age <= 3) {
    return { cls: "ok", label: "Fresh", ageText: label };
  }
  if (age <= 10) {
    return { cls: "warn", label: "Older", ageText: label };
  }
  return { cls: "bad", label: "Stale", ageText: label };
}

async function fetchJSON(url, signal) {
  const response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} from ${url}`);
  }
  return response.json();
}

function panelEmpty(text) {
  return `<p class="panel-empty">${esc(text)}</p>`;
}

function setBusy(container, busy) {
  container.setAttribute("aria-busy", busy ? "true" : "false");
}

/* ---------- Theme ---------- */

function syncThemeButton() {
  const dark = document.documentElement.dataset.theme === "dark";
  const button = $("theme-toggle");
  button.textContent = dark ? "Light mode" : "Dark mode";
  button.setAttribute("aria-pressed", String(dark));
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("prog5-theme", next);
  } catch (error) {
    // Persisting is a convenience; the toggle still works without it.
  }
  syncThemeButton();
}

/* ---------- Selection ---------- */

function tickerLabel(ticker) {
  return ticker.hasData ? ticker.symbol : `${ticker.symbol} (no stored data)`;
}

function buildTickers(health, stocks) {
  const bySymbol = new Map();
  for (const symbol of Object.keys(health.artifacts || {})) {
    bySymbol.set(symbol, { symbol, hasData: false, lastPriceDate: null });
  }
  for (const stock of stocks || []) {
    const entry = bySymbol.get(stock.symbol) || { symbol: stock.symbol, hasData: false, lastPriceDate: null };
    entry.hasData = Boolean(stock.last_price_date);
    entry.lastPriceDate = stock.last_price_date;
    bySymbol.set(stock.symbol, entry);
  }
  state.tickers = [...bySymbol.values()].sort((a, b) => a.symbol.localeCompare(b.symbol));
  state.artifacts = health.artifacts || {};

  const select = $("ticker-select");
  select.innerHTML = state.tickers
    .map((ticker) => `<option value="${esc(ticker.symbol)}">${esc(tickerLabel(ticker))}</option>`)
    .join("");

  const refreshed = state.tickers.filter((ticker) => ticker.hasData).length;
  $("selection-note").textContent =
    `${refreshed} of ${state.tickers.length} research tickers have stored data. ` +
    "Tickers without rows show an empty state, not an error.";
}

function syncHorizonButtons() {
  for (const button of document.querySelectorAll(".horizon-button")) {
    button.setAttribute("aria-pressed", String(Number(button.dataset.horizon) === state.horizon));
  }
}

function updateUrl() {
  const params = new URLSearchParams();
  if (state.symbol) {
    params.set("symbol", state.symbol);
  }
  params.set("horizon", String(state.horizon));
  history.replaceState(null, "", `${location.pathname}?${params.toString()}`);
}

function selectTicker(symbol) {
  if (!symbol || symbol === state.symbol) {
    return;
  }
  state.symbol = symbol;
  $("ticker-select").value = symbol;
  updateUrl();
  load();
}

function selectHorizon(horizon) {
  if (!HORIZONS.includes(horizon) || horizon === state.horizon) {
    return;
  }
  state.horizon = horizon;
  syncHorizonButtons();
  updateUrl();
  load();
}

/* ---------- Loading and rendering ---------- */

async function load() {
  const symbol = state.symbol;
  const horizon = state.horizon;
  if (!symbol) {
    return;
  }
  const seq = ++state.seq;
  document.title = `Prog5 · ${symbol} T+${horizon}`;

  const card = $("prediction");
  setBusy(card, true);
  card.innerHTML = `<p class="panel-loading" role="status">Loading ${esc(symbol)} T+${horizon}.</p>`;
  $("chart-wrap").innerHTML = panelEmpty("Loading stored price history.");
  $("indicator-chips").innerHTML = "";
  $("prediction-history").innerHTML = panelEmpty("Loading stored predictions.");
  $("prediction-history-note").textContent = `${symbol} T+${horizon}, newest first.`;

  try {
    const [latest, history, prices] = await Promise.all([
      fetchJSON(API.latest(symbol)),
      fetchJSON(API.history(symbol, horizon)),
      fetchJSON(API.prices(symbol)),
    ]);
    if (seq !== state.seq) {
      return;
    }
    renderPrediction(symbol, horizon, latest, prices);
    renderChart(prices);
    renderIndicators(prices);
    renderPredictionHistory(symbol, horizon, history);
  } catch (error) {
    if (seq !== state.seq) {
      return;
    }
    renderError(symbol, error);
  }
}

function renderPrediction(symbol, horizon, latest, prices) {
  const card = $("prediction");
  const ticker = state.tickers.find((entry) => entry.symbol === symbol);
  const prediction = (latest || []).find((row) => row.horizon_days === horizon);

  if (!prediction) {
    const stored = (latest || []).map((row) => `T+${row.horizon_days}`).join(", ");
    const detail = ticker && !ticker.hasData
      ? `${symbol} has ${state.artifacts[symbol] || 0} saved models but no stored market rows yet. Run the refresh pipeline once to populate it:`
      : stored
        ? `Stored horizons for ${symbol}: ${stored}. This horizon has no row yet; the next refresh run for it will appear here.`
        : `No predictions are stored for ${symbol} yet. Populate them with:`;
    const command = ticker && !ticker.hasData
      ? `python -m prog5.cli refresh --symbols ${symbol}`
      : stored ? null : `python -m prog5.cli refresh --symbols ${symbol}`;
    card.innerHTML = `
      <div class="prediction-card">
        <p class="kicker">${esc(symbol)} · horizon T+${horizon}</p>
        <p class="panel-empty">No T+${horizon} prediction stored for ${esc(symbol)}.</p>
        <p class="card-note">${esc(detail)}</p>
        ${command ? `<p class="mono card-note">${esc(command)}</p>` : ""}
      </div>`;
    setBusy(card, false);
    return;
  }

  const fresh = freshness(prediction.data_as_of);
  const change = prediction.return_pct;
  const direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  const signalLabel = prediction.signal_label || "hold";
  const warnings = prediction.warnings ? esc(prediction.warnings) : null;
  const ood = prediction.ood_flag
    ? `<p class="warning" role="note"><strong>Outside the model's training range.</strong>
       The most recent close sits ${esc(prediction.ood_z.toFixed(2))} training standard deviations
       from the training mean, so this prediction is the least trustworthy kind the service can show.
       Treat it as a warning, not a fix.</p>`
    : "";

  card.innerHTML = `
    <article class="prediction-card">
      <header class="prediction-head">
        <div>
          <p class="kicker">${esc(symbol)} · horizon T+${horizon}</p>
          <p class="prediction-price-value">${fmtNumber(prediction.predicted_price)}
            <span class="prediction-price-unit">IDR predicted</span></p>
          <p class="prediction-price-sub">Last close ${fmtNumber(prediction.last_close)} IDR
            <span class="delta-${direction}">(${fmtPercent(change)} over ${horizon} session${horizon === 1 ? "" : "s"})</span></p>
        </div>
        <div class="prediction-badges">
          <span class="signal signal-${esc(signalLabel)}"><span class="signal-dot" aria-hidden="true"></span>${esc(signalLabel)}</span>
          <span class="freshness freshness-${fresh.cls}" title="Latest stored trading day ${esc(prediction.data_as_of)}">${fresh.label}</span>
        </div>
      </header>
      <dl class="prediction-meta">
        <div><dt>Signal threshold</dt><dd>${fmtNumber(prediction.threshold_pct)}%</dd></div>
        <div><dt>Data as of</dt><dd>${fmtDate(prediction.data_as_of)} <span class="chip-label">${esc(fresh.ageText)}</span></dd></div>
        <div><dt>Input window</dt><dd>${fmtDate(prediction.window_start_date)} to ${fmtDate(prediction.data_as_of)}, ${prediction.window_size} sessions</dd></div>
        <div><dt>Stored</dt><dd>${fmtDateTime(prediction.created_at)}</dd></div>
        <div><dt>Model file</dt><dd class="mono">${esc(prediction.model_file)}</dd></div>
        <div><dt>Model SHA-256</dt><dd class="mono" title="${esc(prediction.model_sha256)}">${esc(prediction.model_sha256.slice(0, 12))}…</dd></div>
        <div><dt>OOD z-score</dt><dd>${esc(prediction.ood_z.toFixed(2))} ${prediction.ood_flag ? "(outside range)" : "(inside range)"}</dd></div>
        <div><dt>Price rows read</dt><dd>${integerFormat.format((prices.rows || []).length)}</dd></div>
      </dl>
      ${ood}
      <p class="prediction-rule">Rule from the training notebook: buy when the predicted return reaches
        ${fmtNumber(prediction.threshold_pct)}% or more, sell when it falls to ${fmtNumber(-prediction.threshold_pct)}% or less,
        otherwise hold. The OOD flag marks inputs far outside the model's 2018-2023 training range.</p>
      ${warnings ? `<p class="card-note"><strong>Pipeline note:</strong> ${warnings}</p>` : ""}
    </article>`;
  setBusy(card, false);
}

function renderChart(prices) {
  const container = $("chart-wrap");
  const rows = prices.rows || [];
  if (!rows.length) {
    container.innerHTML = panelEmpty(`No stored price rows for ${prices.symbol} yet, so there is nothing to chart.`);
    return;
  }
  const closes = rows.map((row) => row.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const width = 720;
  const height = 250;
  const left = 72;
  const right = 14;
  const top = 14;
  const bottom = 34;
  const innerWidth = width - left - right;
  const innerHeight = height - top - bottom;
  const span = Math.max(max - min, 1e-9);
  const x = (index) => left + (index / Math.max(1, closes.length - 1)) * innerWidth;
  const y = (value) => top + ((max - value) / span) * innerHeight;

  const points = closes.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
  const area = `${left},${(top + innerHeight).toFixed(1)} ${points} ${(left + innerWidth).toFixed(1)},${(top + innerHeight).toFixed(1)}`;

  let grid = "";
  const ticks = 4;
  for (let step = 0; step <= ticks; step += 1) {
    const value = min + (span * step) / ticks;
    const lineY = y(value);
    grid += `<line class="chart-grid" x1="${left}" y1="${lineY.toFixed(1)}" x2="${width - right}" y2="${lineY.toFixed(1)}"/>`;
    grid += `<text class="chart-tick" x="${left - 8}" y="${(lineY + 4).toFixed(1)}" text-anchor="end">${fmtNumber(value)}</text>`;
  }

  const firstDate = fmtDate(rows[0].price_date);
  const lastDate = fmtDate(rows[rows.length - 1].price_date);
  const lastX = x(closes.length - 1).toFixed(1);
  const lastY = y(closes[closes.length - 1]).toFixed(1);

  container.innerHTML = `
    <figure class="chart">
      <svg viewBox="0 0 ${width} ${height}" role="img"
           aria-label="Close price history for ${esc(prices.symbol)}, ${esc(firstDate)} to ${esc(lastDate)}">
        ${grid}
        <polygon class="chart-area" points="${area}"/>
        <polyline class="chart-line" points="${points}"/>
        <circle class="chart-dot" cx="${lastX}" cy="${lastY}" r="3.5"/>
        <text class="chart-tick" x="${left}" y="${height - 10}">${esc(firstDate)}</text>
        <text class="chart-tick" x="${width - right}" y="${height - 10}" text-anchor="end">${esc(lastDate)}</text>
      </svg>
      <figcaption>${rows.length} stored sessions from ${esc(firstDate)} to ${esc(lastDate)}.
        Range ${fmtNumber(min)} to ${fmtNumber(max)} IDR; last close ${fmtNumber(closes[closes.length - 1])} IDR.</figcaption>
    </figure>`;
}

function renderIndicators(prices) {
  const container = $("indicator-chips");
  const indicators = prices.latest_indicators || {};
  const rows = prices.rows || [];
  const asOf = rows.length ? fmtDate(rows[rows.length - 1].price_date) : null;
  const entries = [
    ["SMA 20", indicators.sma_20],
    ["EMA 20", indicators.ema_20],
    ["RSI", indicators.rsi],
    ["MACD", indicators.macd],
    ["MACD signal", indicators.macd_signal],
    ["Bollinger upper", indicators.upperband],
    ["Bollinger lower", indicators.lowerband],
  ].filter(([, value]) => value !== null && value !== undefined);

  if (!entries.length) {
    container.innerHTML = `<p class="card-note">No indicator rows are stored for ${esc(prices.symbol)} yet.</p>`;
    return;
  }
  container.innerHTML = `
    <p class="chips-label">Technical indicators${asOf ? `, ${esc(asOf)}` : ""}</p>
    <ul class="chips">
      ${entries.map(([label, value]) => `
        <li><span class="chip-label">${esc(label)}</span><span class="chip-value">${fmtNumber(value)}</span></li>`).join("")}
    </ul>`;
}

function renderPredictionHistory(symbol, horizon, history) {
  const container = $("prediction-history");
  const note = $("prediction-history-note");
  const rows = history || [];
  note.textContent = `${symbol} T+${horizon}, newest first. ${rows.length} stored row${rows.length === 1 ? "" : "s"}.`;
  if (!rows.length) {
    container.innerHTML = panelEmpty(`No stored T+${horizon} predictions for ${symbol} yet. Each refresh run adds one row.`);
    return;
  }
  container.innerHTML = `
    <div class="table-scroll">
      <table>
        <caption class="visually-hidden">Stored ${esc(symbol)} T+${horizon} predictions, newest first</caption>
        <thead>
          <tr>
            <th>Data as of</th>
            <th class="num">Last close</th>
            <th class="num">Predicted</th>
            <th class="num">Return</th>
            <th class="num">Threshold</th>
            <th>Signal</th>
            <th class="num">OOD z</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => {
            const direction = row.return_pct > 0 ? "up" : row.return_pct < 0 ? "down" : "flat";
            return `
            <tr>
              <td>${fmtDate(row.data_as_of)}</td>
              <td class="num">${fmtNumber(row.last_close)}</td>
              <td class="num">${fmtNumber(row.predicted_price)}</td>
              <td class="num delta-${direction}">${fmtPercent(row.return_pct)}</td>
              <td class="num">${fmtNumber(row.threshold_pct)}%</td>
              <td><span class="signal signal-${esc(row.signal_label)}"><span class="signal-dot" aria-hidden="true"></span>${esc(row.signal_label)}</span></td>
              <td class="num">${esc(row.ood_z.toFixed(2))}${row.ood_flag ? " flagged" : ""}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>`;
}

function renderRuns(runs) {
  const container = $("runs");
  if (!runs || !runs.length) {
    container.innerHTML = panelEmpty("No refresh runs are stored yet.");
    return;
  }
  const statusClass = (status) => (status === "completed" ? "ok" : status === "failed" ? "bad" : "warn");
  container.innerHTML = `
    <div class="table-scroll">
      <table>
        <caption class="visually-hidden">Recent refresh runs, newest first</caption>
        <thead>
          <tr>
            <th>Run</th>
            <th>Status</th>
            <th>Symbols</th>
            <th>Horizons</th>
            <th>Started</th>
            <th>Finished</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          ${runs.map((run) => `
            <tr>
              <td>#${run.id} · ${esc(run.kind)}</td>
              <td><span class="status status-${statusClass(run.status)}">${esc(run.status)}</span></td>
              <td>${esc(run.requested_symbols)}</td>
              <td>${esc(run.horizons)}</td>
              <td>${fmtDateTime(run.started_at)}</td>
              <td>${run.finished_at ? fmtDateTime(run.finished_at) : "in progress"}</td>
              <td class="summary-cell" title="${esc(run.summary || "")}">${esc(run.summary || "n/a")}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
}

function renderFooterStatus(health) {
  const modelTickers = Object.keys(health.artifacts || {}).length;
  const storage = health.storage_backend === "postgresql" ? "PostgreSQL" : "SQLite";
  const run = health.last_run;
  const runText = run
    ? ` Last refresh #${run.id} ${esc(run.status)}${run.finished_at ? ` at ${esc(fmtDateTime(run.finished_at))}` : ""}.`
    : " No refresh run is recorded yet.";
  $("footer-status").innerHTML =
    `<strong>Service v${esc(health.version)}</strong> · ${integerFormat.format(health.price_rows)} price rows · ` +
    `${integerFormat.format(health.indicator_rows)} indicator rows · ${integerFormat.format(health.prediction_rows)} predictions · ` +
    `saved models for ${modelTickers} tickers.${runText}`;
  $("storage-note").textContent = `Stored in ${storage}.`;
}

function renderError(symbol, error) {
  const card = $("prediction");
  card.innerHTML = `
    <div class="panel-error" role="alert">
      <p><strong>Could not load data for ${esc(symbol)}.</strong></p>
      <p class="panel-error-detail">${esc(error.message)}</p>
      <button type="button" id="retry-button" class="button">Try again</button>
    </div>`;
  setBusy(card, false);
  // A boot-time failure never reached a selection, so retry has to redo boot.
  $("retry-button").addEventListener("click", () => {
    if (state.symbol) {
      load();
    } else {
      boot();
    }
  });
  $("chart-wrap").innerHTML = panelEmpty("Price history is unavailable while the request is failing.");
  $("indicator-chips").innerHTML = "";
  $("prediction-history").innerHTML = panelEmpty("Prediction history is unavailable while the request is failing.");
}

/* ---------- Boot ---------- */

async function boot() {
  syncThemeButton();
  try {
    const [health, stocks, runs] = await Promise.all([
      fetchJSON(API.health),
      fetchJSON(API.stocks),
      fetchJSON(API.runs),
    ]);
    buildTickers(health, stocks);
    renderFooterStatus(health);
    renderRuns(runs);

    const params = new URLSearchParams(location.search);
    const requestedSymbol = (params.get("symbol") || "").toUpperCase();
    const requestedHorizon = Number(params.get("horizon"));
    const defaultTicker = state.tickers.find((ticker) => ticker.hasData) || state.tickers[0];
    const symbol = state.tickers.some((ticker) => ticker.symbol === requestedSymbol)
      ? requestedSymbol
      : defaultTicker
        ? defaultTicker.symbol
        : null;
    state.symbol = symbol;
    state.horizon = HORIZONS.includes(requestedHorizon) ? requestedHorizon : 1;
    if (symbol) {
      $("ticker-select").value = symbol;
    }
    syncHorizonButtons();
    updateUrl();
    await load();
  } catch (error) {
    renderError(state.symbol || "the service", error);
  }
}

$("theme-toggle").addEventListener("click", toggleTheme);
$("ticker-select").addEventListener("change", (event) => selectTicker(event.target.value));
for (const button of document.querySelectorAll(".horizon-button")) {
  button.addEventListener("click", () => selectHorizon(Number(button.dataset.horizon)));
}

boot();

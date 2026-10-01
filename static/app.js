const symbolSelect = document.querySelector("#symbol-select");
const periodSelect = document.querySelector("#period-select");
const horizonSelect = document.querySelector("#horizon-select");
const statusLine = document.querySelector("#page-status");
const refreshButton = document.querySelector("#refresh-button");
const runPredictionButton = document.querySelector("#run-prediction");
const themeToggle = document.querySelector("#theme-toggle");
const priceChart = document.querySelector("#price-chart");
const chartEmpty = document.querySelector("#chart-empty");
const chartSource = document.querySelector("#chart-source");
const signalSummary = document.querySelector("#signal-summary");
const historyRows = document.querySelector("#history-rows");
let marketRequestId = 0;

const currencyFormat = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});
const numberFormat = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 });
const dateFormat = new Intl.DateTimeFormat("id-ID", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});
const timeFormat = new Intl.DateTimeFormat("id-ID", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function setStatus(message, state = "neutral") {
  statusLine.textContent = message;
  statusLine.dataset.state = state;
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `Permintaan gagal (${response.status}).`);
  }
  return body;
}

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.setAttribute("aria-busy", String(busy));
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = label;
  } else if (button.dataset.originalLabel) {
    button.textContent = button.dataset.originalLabel;
    delete button.dataset.originalLabel;
  }
}

function formatPrice(value) {
  return Number.isFinite(Number(value)) ? currencyFormat.format(Number(value)) : "Belum tersedia";
}

function formatDate(value) {
  return value ? dateFormat.format(new Date(`${value}T00:00:00`)) : "Belum tersedia";
}

function formatPercent(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return "Belum tersedia";
  const prefix = numericValue > 0 ? "+" : "";
  return `${prefix}${numberFormat.format(numericValue)}%`;
}

function formatIndicator(value) {
  return value === null || value === undefined ? "Belum tersedia" : numberFormat.format(value);
}

function formatSource(source) {
  return {
    yahoo_finance: "Yahoo Finance",
    database_cache: "Cache lokal",
    research_dataset: "Dataset penelitian",
  }[source] || source;
}

function setIndicator(id, value) {
  document.querySelector(`#${id}`).textContent = formatIndicator(value);
}

function renderPriceChart(prices) {
  if (!prices.length) {
    priceChart.setAttribute("hidden", "");
    chartEmpty.hidden = false;
    chartEmpty.textContent = "Belum ada data harga untuk rentang ini.";
    return;
  }

  const width = 1000;
  const height = 340;
  const padding = { top: 18, right: 14, bottom: 18, left: 14 };
  const closes = prices.map((point) => Number(point.close));
  const minimum = Math.min(...closes);
  const maximum = Math.max(...closes);
  const spread = maximum - minimum || Math.max(Math.abs(maximum) * 0.02, 1);
  const low = minimum - spread * 0.08;
  const high = maximum + spread * 0.08;
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const points = closes.map((value, index) => {
    const x = padding.left + (index / Math.max(closes.length - 1, 1)) * plotWidth;
    const y = padding.top + ((high - value) / (high - low)) * plotHeight;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  priceChart.replaceChildren();
  priceChart.setAttribute("viewBox", `0 0 ${width} ${height}`);
  priceChart.setAttribute("aria-label", `Grafik harga penutupan ${symbolSelect.value}`);
  for (let index = 0; index < 4; index += 1) {
    const y = padding.top + (index / 3) * plotHeight;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", String(padding.left));
    line.setAttribute("x2", String(width - padding.right));
    line.setAttribute("y1", String(y));
    line.setAttribute("y2", String(y));
    line.setAttribute("class", "chart-grid-line");
    priceChart.append(line);
  }

  const path = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  path.setAttribute("points", points.join(" "));
  path.setAttribute("class", "chart-line");
  priceChart.append(path);
  chartEmpty.hidden = true;
  priceChart.removeAttribute("hidden");
}

function renderMarket(data) {
  const prices = data.prices || [];
  const latest = prices.at(-1);
  document.querySelector("#latest-price").textContent = latest ? formatPrice(latest.close) : "Belum ada data";
  document.querySelector("#price-context").textContent = latest
    ? `${data.symbol} · data sampai ${formatDate(data.data_as_of)}`
    : "Pilih kode saham untuk melihat riwayat.";
  document.querySelector("#chart-period").textContent = prices.length
    ? `${formatDate(prices[0].date)} hingga ${formatDate(data.data_as_of)}`
    : "Belum ada rentang data";
  chartSource.textContent = `Sumber: ${formatSource(data.source)}`;
  renderPriceChart(prices);
  setIndicator("indicator-rsi", data.indicators.rsi);
  setIndicator("indicator-macd", data.indicators.macd);
  setIndicator("indicator-sma5", data.indicators.sma_5);
  setIndicator("indicator-sma20", data.indicators.sma_20);
  setIndicator("indicator-sma50", data.indicators.sma_50);
  setIndicator("indicator-ema20", data.indicators.ema_20);
  setStatus(
    data.warning || `Data ${data.symbol} tersedia dari ${formatSource(data.source)}.`,
    data.warning ? "warning" : "success",
  );
}

function renderPrediction(prediction) {
  const signalKey = prediction.signal === 1 ? "buy" : prediction.signal === -1 ? "sell" : "hold";
  signalSummary.dataset.signal = signalKey;
  document.querySelector("#signal-label").textContent = prediction.signal_label;
  document.querySelector("#signal-context").textContent =
    `${formatPercent(prediction.return_percent)} terhadap harga terakhir. Ambang sinyal ±${numberFormat.format(prediction.threshold_percent)}%.`;
  document.querySelector("#predicted-price").textContent = formatPrice(prediction.predicted_price);
  document.querySelector("#predicted-return").textContent = formatPercent(prediction.return_percent);
  document.querySelector("#prediction-as-of").textContent = formatDate(prediction.input_as_of);
  document.querySelector("#prediction-model").textContent =
    `${prediction.architecture}, ${prediction.feature_set}`;
  document.querySelector("#prediction-source").textContent = formatSource(prediction.data_source);
  document.querySelector("#prediction-empty").hidden = true;
  document.querySelector("#prediction-result").hidden = false;
}

function clearMarketView(message) {
  document.querySelector("#latest-price").textContent = "Belum ada data";
  document.querySelector("#price-context").textContent = "Pilih kode saham untuk melihat riwayat.";
  document.querySelector("#chart-period").textContent = "Belum ada rentang data";
  chartSource.textContent = "";
  priceChart.replaceChildren();
  priceChart.setAttribute("hidden", "");
  chartEmpty.hidden = false;
  chartEmpty.textContent = message;
  for (const id of [
    "indicator-rsi",
    "indicator-macd",
    "indicator-sma5",
    "indicator-sma20",
    "indicator-sma50",
    "indicator-ema20",
  ]) {
    document.querySelector(`#${id}`).textContent = "Belum tersedia";
  }
  signalSummary.dataset.signal = "empty";
  document.querySelector("#signal-label").textContent = "Belum ada prediksi";
  document.querySelector("#signal-context").textContent = "Jalankan prediksi untuk melihat hasil.";
  document.querySelector("#prediction-empty").hidden = false;
  document.querySelector("#prediction-result").hidden = true;
  historyRows.replaceChildren();
  document.querySelector("#history-count").textContent = "Belum ada catatan";
  document.querySelector("#history-empty").textContent = "Prediksi yang dijalankan akan tercatat di sini.";
  document.querySelector("#history-empty").hidden = false;
  document.querySelector("#history-table-wrap").hidden = true;
}

function renderHistory(predictions) {
  historyRows.replaceChildren();
  const empty = document.querySelector("#history-empty");
  const table = document.querySelector("#history-table-wrap");
  document.querySelector("#history-count").textContent = `${predictions.length} catatan`;
  empty.hidden = predictions.length > 0;
  table.hidden = predictions.length === 0;

  for (const prediction of predictions) {
    const row = document.createElement("tr");
    const values = [
      timeFormat.format(new Date(prediction.created_at)),
      formatDate(prediction.input_as_of),
      formatPrice(prediction.predicted_price),
      formatPercent(prediction.return_percent),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const signalCell = document.createElement("td");
    signalCell.className = "signal-cell";
    signalCell.dataset.signal = String(prediction.signal);
    signalCell.textContent = prediction.signal_label;
    row.append(signalCell);
    historyRows.append(row);
  }
}

async function loadHistory(symbol, requestId = marketRequestId) {
  const horizonDays = horizonSelect.value;
  const query = new URLSearchParams({ horizon_days: horizonDays, limit: "20" });
  const predictions = await requestJson(
    `/api/v1/predictions/history/${encodeURIComponent(symbol)}?${query}`,
  );
  if (
    requestId !== marketRequestId
    || symbol !== symbolSelect.value
    || horizonDays !== horizonSelect.value
  ) return;
  renderHistory(predictions);
  if (predictions.length) {
    renderPrediction(predictions[0]);
  } else {
    signalSummary.dataset.signal = "empty";
    document.querySelector("#signal-label").textContent = "Belum ada prediksi";
    document.querySelector("#signal-context").textContent = "Jalankan prediksi untuk melihat hasil.";
    document.querySelector("#prediction-empty").hidden = false;
    document.querySelector("#prediction-result").hidden = true;
  }
}

async function refreshMarketData() {
  const symbol = symbolSelect.value;
  const period = periodSelect.value;
  const requestId = ++marketRequestId;
  setBusy(refreshButton, true, "Memuat data...");
  setStatus(`Memuat riwayat harga ${symbol}...`);
  clearMarketView("Mengambil harga dan menghitung indikator...");
  try {
    const data = await requestJson(
      `/api/v1/market-data/${encodeURIComponent(symbol)}?period=${encodeURIComponent(period)}`,
    );
    if (requestId !== marketRequestId) return;
    renderMarket(data);
    try {
      await loadHistory(symbol, requestId);
    } catch (error) {
      document.querySelector("#history-empty").textContent = error.message;
      setStatus(`Harga tersedia, tetapi riwayat prediksi gagal dimuat: ${error.message}`, "error");
    }
  } catch (error) {
    if (requestId === marketRequestId) {
      clearMarketView(error.message);
      setStatus(error.message, "error");
    }
  } finally {
    if (requestId === marketRequestId) setBusy(refreshButton, false);
  }
}

async function runPrediction() {
  const symbol = symbolSelect.value;
  const horizonDays = horizonSelect.value;
  document.querySelector("#horizon-caption").textContent = `HORIZON ${horizonDays} HARI BURSA`;
  setBusy(runPredictionButton, true, "Menghitung...");
  setStatus(`Menjalankan model LSTM ${symbol} untuk ${horizonDays} hari bursa...`);
  try {
    const prediction = await requestJson(
      `/api/v1/predictions/${encodeURIComponent(symbol)}?horizon_days=${horizonDays}`,
      {
      method: "POST",
      },
    );
    if (symbolSelect.value === symbol && horizonSelect.value === horizonDays) {
      renderPrediction(prediction);
      await loadHistory(symbol);
      const sourceWarning = prediction.data_source === "research_dataset"
        ? " Hasil ini memakai dataset penelitian historis."
        : prediction.data_source === "database_cache"
          ? " Hasil ini memakai data harga tersimpan."
          : "";
      setStatus(`Prediksi ${symbol} untuk ${horizonDays} hari tersimpan.${sourceWarning}`, "success");
    }
  } catch (error) {
    if (symbolSelect.value === symbol && horizonSelect.value === horizonDays) {
      setStatus(error.message, "error");
    }
  } finally {
    setBusy(runPredictionButton, false);
  }
}

async function loadStocks() {
  const stocks = await requestJson("/api/v1/stocks");
  symbolSelect.replaceChildren();
  for (const stock of stocks) {
    const option = document.createElement("option");
    option.value = stock.symbol;
    option.textContent = stock.symbol;
    symbolSelect.append(option);
  }
  if (stocks.some((stock) => stock.symbol === "ADRO")) {
    symbolSelect.value = "ADRO";
  }
}

document.querySelector("#market-controls").addEventListener("submit", (event) => {
  event.preventDefault();
  refreshMarketData();
});
symbolSelect.addEventListener("change", refreshMarketData);
periodSelect.addEventListener("change", refreshMarketData);
horizonSelect.addEventListener("change", () => {
  const horizonDays = horizonSelect.value;
  document.querySelector("#horizon-caption").textContent = `HORIZON ${horizonDays} HARI BURSA`;
  loadHistory(symbolSelect.value).catch((error) => setStatus(error.message, "error"));
});
runPredictionButton.addEventListener("click", runPrediction);
themeToggle.addEventListener("click", () => {
  const darkMode = document.documentElement.dataset.theme !== "dark";
  document.documentElement.dataset.theme = darkMode ? "dark" : "light";
  themeToggle.textContent = darkMode ? "Mode terang" : "Mode gelap";
  themeToggle.setAttribute("aria-pressed", String(darkMode));
});

loadStocks()
  .then(refreshMarketData)
  .catch((error) => setStatus(error.message, "error"));

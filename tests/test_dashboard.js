const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appPath = path.join(__dirname, "../idx_signal/static/app.js");
const htmlPath = path.join(__dirname, "../idx_signal/static/index.html");
const app = fs.readFileSync(appPath, "utf8");
const html = fs.readFileSync(htmlPath, "utf8");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.hidden = false;
    this._innerHTML = "";
    this._textContent = null;
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this._textContent = null;
    this.children = [];
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set textContent(value) {
    this._textContent = String(value ?? "");
    this._innerHTML = this._textContent;
  }

  get textContent() {
    if (this._textContent !== null) return this._textContent;
    return this._innerHTML
      .replace(/<br\s*\/?>/gi, " ")
      .replace(/<[^>]*>/g, "")
      .replace(/&nbsp;/g, " ")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">");
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  get cells() {
    if (this.tagName !== "TR") return [];
    if (this.children.length) return this.children;
    return [...this._innerHTML.matchAll(/<td\b([^>]*)>([\s\S]*?)<\/td>/gi)].map(([, attrs, body]) => {
      const cell = new Element("td");
      cell.innerHTML = body;
      const label = attrs.match(/\bdata-label="([^"]*)"/i);
      if (label) cell.setAttribute("data-label", label[1]);
      return cell;
    });
  }

  get rows() {
    if (this.tagName !== "TBODY") return [];
    if (this.children.length) return this.children.filter((child) => child.tagName === "TR");
    return [...this._innerHTML.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)].map(([, body]) => {
      const row = new Element("tr");
      row.innerHTML = body;
      return row;
    });
  }
}

function createDashboard() {
  const elements = new Map();
  const document = {
    addEventListener() {},
    createElement: (tagName) => new Element(tagName),
    getElementById(id) {
      if (!elements.has(id)) {
        const tagName = ["signal-rows", "history-rows"].includes(id) ? "tbody" : "div";
        elements.set(id, new Element(tagName));
      }
      return elements.get(id);
    },
  };
  const context = vm.createContext({
    document,
    URLSearchParams,
    fetch: () => Promise.reject(new Error("Unexpected network request")),
    window: {
      location: { pathname: "/" },
      history: { replaceState() {} },
    },
  });
  vm.runInContext(app, context);
  return { context, elements };
}

function signal(signalName, threshold, anchor, horizon, date) {
  return {
    signal: signalName,
    threshold_pct: threshold,
    last_close: anchor,
    reference_close: anchor,
    predicted_price: 9999,
    horizon_days: horizon,
    data_as_of: date,
    target_date: date,
    outcome_status: "pending",
  };
}

function renderSignals(context, payload, referenceDate = null) {
  context.__payload = payload;
  context.__referenceDate = referenceDate;
  vm.runInContext(
    "state.symbol = __payload.symbol; state.symbols = [{symbol: __payload.symbol, name: 'Saham Uji'}]; " +
      "state.referenceDate = __referenceDate; renderSignals(__payload)",
    context,
  );
  delete context.__payload;
  delete context.__referenceDate;
  return context.document.getElementById("signal-rows").rows;
}

test("latest signal rows render BUY, HOLD, and SELL ranges from each row's close and threshold", () => {
  const { context, elements } = createDashboard();
  const rows = renderSignals(context, {
    symbol: "TEST",
    last_close: 777,
    last_price_date: "2026-10-29",
    signals: [
      { ...signal("BUY", 2, 1000, 1, "2026-10-29"), reference_close: 9000 },
      { ...signal("HOLD", 3, 2000, 5, "2026-10-29"), reference_close: 9000 },
      { ...signal("SELL", 4, 500, 10, "2026-10-29"), reference_close: 9000 },
    ],
  });

  assert.deepEqual(rows.map((row) => row.cells[2].textContent), [
    "≥ 1.020,00",
    "1.940,00 - 2.060,00",
    "≤ 480,00",
  ]);
  assert.deepEqual(rows.map((row) => row.cells[3].textContent), ["±2,00%", "±3,00%", "±4,00%"]);
  assert.ok(rows.every((row) => row.cells[2].attributes["data-label"] === "Rentang harga"));
  assert.ok(rows.every((row) => row.cells[3].attributes["data-label"] === "Threshold"));
  assert.ok(rows.every((row) => row.cells[4].attributes["data-label"] === "Harga aktual"));
  assert.ok(rows.every((row) => !row.cells[2].textContent.includes("9999")));
  assert.equal(elements.get("signals-heading").textContent, "Sinyal terbaru");
  assert.equal(elements.get("reference-price").textContent, "Harga penutupan 777 · 29 Okt 2026");
  assert.match(elements.get("signal-note").textContent, /Tanggal prediksi dihitung dari hari ini/);
});

test("historical rows use each signal's reference close rather than latest or point-predicted prices", () => {
  const { context } = createDashboard();
  const rows = renderSignals(context, {
    symbol: "TEST",
    reference_close: 8888,
    reference_date: "2026-10-28",
    signals: [
      { ...signal("BUY", 2, 1000, 1, "2026-10-28"), last_close: 9000 },
      { ...signal("HOLD", 3, 2000, 5, "2026-10-28"), last_close: 9000 },
      { ...signal("SELL", 4, 500, 10, "2026-10-28"), last_close: 9000 },
    ],
  }, "2026-10-28");

  assert.deepEqual(rows.map((row) => row.cells[2].textContent), [
    "≥ 1.020,00",
    "1.940,00 - 2.060,00",
    "≤ 480,00",
  ]);
  assert.equal(context.document.getElementById("signals-heading").textContent, "Sinyal historis");
  assert.equal(context.document.getElementById("date-active").textContent, "Tanggal acuan aktif: 28 Okt 2026");
});

test("saved history rows calculate independent ranges from each stored close and threshold", () => {
  const { context, elements } = createDashboard();
  context.__rows = [
    { ...signal("BUY", 2, 1000, 1, "2026-10-29"), created_at: "2026-10-29T12:00:00Z" },
    { ...signal("HOLD", 3, 2000, 1, "2026-10-28"), created_at: "2026-10-28T12:00:00Z" },
    { ...signal("SELL", 4, 500, 1, "2026-10-27"), created_at: "2026-10-27T12:00:00Z" },
  ];
  vm.runInContext("renderHistory(__rows)", context);

  const rows = elements.get("history-rows").rows;
  assert.deepEqual(rows.map((row) => row.cells[3].textContent), [
    "≥ 1.020,00",
    "1.940,00 - 2.060,00",
    "≤ 480,00",
  ]);
  assert.deepEqual(rows.map((row) => row.cells[4].textContent), ["±2,00%", "±3,00%", "±4,00%"]);
  assert.ok(rows.every((row) => row.cells[3].attributes["data-label"] === "Rentang harga"));
  assert.ok(rows.every((row) => row.cells[0].attributes["data-label"] === "Tanggal harga"));
  assert.ok(rows.every((row) => !row.cells[3].textContent.includes("9999")));
  assert.equal(elements.get("history-wrap").hidden, false);
});

test("visible table labels and the range disclaimer match the approved wording", () => {
  const signalTable = html.match(/<table class="signal-table">([\s\S]*?)<\/table>/)?.[1];
  const historyTable = html.match(/<table class="plain-table">([\s\S]*?)<\/table>/)?.[1];
  assert.ok(signalTable);
  assert.ok(historyTable);
  for (const table of [signalTable, historyTable]) {
    assert.match(table, />Rentang harga</);
    assert.match(table, />Threshold</);
    assert.doesNotMatch(table, />Batas perubahan</);
    assert.match(table, />Tanggal prediksi</);
    assert.doesNotMatch(table, />Harga perkiraan</);
    assert.doesNotMatch(table, />Perkiraan tanggal</);
  }
  assert.match(signalTable, />Harga aktual</);
  assert.doesNotMatch(signalTable, />Aktual</);
  assert.match(historyTable, />Tanggal harga</);
  assert.match(html, /Rentang harga mengikuti threshold tiap sinyal, bukan tingkat keyakinan model atau jaminan harga\./);
});

test("a slower response for the previous reference date cannot replace the current ranges", async () => {
  const { context, elements } = createDashboard();
  const pending = [];
  context.fetch = (url) => new Promise((resolve) => pending.push({ url, resolve }));

  vm.runInContext(
    "state.symbol = 'TEST'; state.symbols = [{symbol: 'TEST', name: 'Saham Uji', " +
      "first_usable_reference_date: '2026-10-01', last_price_date: '2026-10-30'}]; " +
      "globalThis.oldLoad = applyReferenceDate('2026-10-28'); " +
      "globalThis.currentLoad = applyReferenceDate('2026-10-29')",
    context,
  );
  assert.equal(pending.length, 2);
  assert.match(pending[0].url, /date=2026-10-28/);
  assert.match(pending[1].url, /date=2026-10-29/);

  const response = (referenceDate, anchor) => ({
    ok: true,
    status: 200,
    text: async () => JSON.stringify({
      symbol: "TEST",
      reference_date: referenceDate,
      reference_close: anchor,
      signals: [signal("BUY", 3, anchor, 1, referenceDate)],
    }),
  });
  pending[1].resolve(response("2026-10-29", 2000));
  await context.currentLoad;
  pending[0].resolve(response("2026-10-28", 1000));
  await context.oldLoad;

  assert.equal(elements.get("date-active").textContent, "Tanggal acuan aktif: 29 Okt 2026");
  assert.equal(elements.get("signal-rows").rows[0].cells[2].textContent, "≥ 2.060,00");
  assert.equal(elements.get("signal-rows").rows.length, 1);
});

test("a failed stocks reload says the date bounds are still the previous ones", async () => {
  const { context, elements } = createDashboard();
  const input = context.document.getElementById("reference-date");
  input.min = "2026-10-01";
  input.max = "2026-10-30";
  context.fetch = () => Promise.reject(new Error("Server menjawab 500."));

  await vm.runInContext("loadAll()", context).catch(() => {});

  assert.match(
    elements.get("date-hint").textContent,
    /^Rentang tanggal gagal diperbarui \(Server menjawab 500\.\)\. Batas yang tampil masih dari pemuatan sebelumnya\.$/,
  );
  assert.equal(input.min, "2026-10-01");
  assert.equal(input.max, "2026-10-30");
});

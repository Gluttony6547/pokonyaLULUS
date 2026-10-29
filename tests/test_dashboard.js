const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appPath = path.join(__dirname, "../idx_signal/static/app.js");
const htmlPath = path.join(__dirname, "../idx_signal/static/index.html");
const app = fs.readFileSync(appPath, "utf8");
const html = fs.readFileSync(htmlPath, "utf8");
const context = vm.createContext({
  document: { addEventListener() {} },
});
vm.runInContext(app, context);

function formatRange(signal, referencePrice) {
  return vm.runInContext(
    `formatPriceRange(${JSON.stringify(signal)}, ${JSON.stringify(referencePrice)})`,
    context,
  );
}

test("BUY and SELL use the inclusive threshold boundaries", () => {
  assert.equal(formatRange({ signal: "BUY", threshold_pct: 1.5 }, 1000), "≥ 1.015,00");
  assert.equal(formatRange({ signal: "SELL", threshold_pct: 1.5 }, 1000), "≤ 985,00");
});

test("HOLD shows prices strictly between the signal thresholds", () => {
  assert.equal(
    formatRange({ signal: "HOLD", threshold_pct: 1.5 }, 1000),
    "> 985,00 dan < 1.015,00",
  );
});

test("missing reference data or threshold does not render a numeric range", () => {
  assert.equal(formatRange({ signal: "BUY", threshold_pct: 1.5 }, null), "belum tersedia");
  assert.equal(formatRange({ signal: "BUY", threshold_pct: null }, 1000), "belum tersedia");
});

test("the dashboard does not show the model's point price in signal or history rows", () => {
  assert.doesNotMatch(app, /data-label="Harga perkiraan"/);
  assert.doesNotMatch(app, /data-label="Harga prediksi"/);
  assert.match(app, /Tanggal prediksi dihitung dari hari ini\./);
});

test("the latest, historical, and saved-history renderers use each signal's reference close", () => {
  assert.match(app, /historical \? signal\.reference_close : signal\.last_close/);
  assert.match(app, /formatPriceRange\(row, row\.last_close\)/);
});

test("signal and history tables use clear range and target-date labels", () => {
  const signalTable = html.match(/<table class="signal-table">([\s\S]*?)<\/table>/)?.[1];
  const historyTable = html.match(/<table class="plain-table">([\s\S]*?)<\/table>/)?.[1];
  assert.ok(signalTable);
  assert.ok(historyTable);
  for (const table of [signalTable, historyTable]) {
    assert.match(table, />Rentang harga</);
    assert.match(table, />Batas perubahan</);
    assert.match(table, />Tanggal prediksi</);
    assert.doesNotMatch(table, />Harga perkiraan</);
    assert.doesNotMatch(table, />Perubahan</);
    assert.doesNotMatch(table, />Perkiraan tanggal</);
  }
  assert.match(app, /data-label="Rentang harga"/);
  assert.match(app, /data-label="Batas perubahan"/);
  assert.match(app, /data-label="Tanggal prediksi"/);
});

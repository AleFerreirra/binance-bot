import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { createAlertManager } from "../dashboard/js/alerts.js";
import { createMarketChart } from "../dashboard/js/chart.js";
import { calculateIndicators, supportResistance } from "../dashboard/js/indicators.js";
import { getMarketClock } from "../dashboard/js/marketClock.js";
import { closedCandles, createKlineSocket, demoForexQuotes, fetchForexQuotes, mergeCandle } from "../dashboard/js/marketData.js";
import {
  buildAnalysis,
  calculateProgressiveScore,
  classifyTrend,
  createDirectional,
  DECISIONS,
  verificarAproximacaoZona,
} from "../dashboard/js/signalEngine.js";

function candles(count = 260, direction = 1) {
  const rows = [];
  let price = 100;
  for (let index = 0; index < count; index += 1) {
    const open = price;
    price += direction * 0.8 + Math.sin(index / 10) * 0.2;
    const close = price;
    rows.push({
      time: 1700000000 + index * 900,
      open,
      high: Math.max(open, close) + 1,
      low: Math.min(open, close) - 1,
      close,
      volume: 1000 + index,
      closeTime: (1700000000 + index * 900) * 1000,
    });
  }
  return rows;
}

function priceActionCandles() {
  const data = [];
  let price = 320;
  for (let index = 0; index < 260; index += 1) {
    const open = price;
    price += Math.sin(index / 7) * 0.6;
    const close = price;
    data.push({
      time: 1700000000 + index * 900,
      open,
      high: Math.max(open, close) + 3,
      low: Math.min(open, close) - 3,
      close,
      volume: 1000,
      closeTime: (1700000000 + index * 900) * 1000,
    });
  }
  const highIndex = data.length - 30;
  const lowIndex = data.length - 18;
  Object.assign(data[highIndex], { open: 330, high: 360, low: 325, close: 340, volume: 5000 });
  Object.assign(data[highIndex + 1], { open: 340, high: 345, low: 320, close: 330 });
  Object.assign(data[lowIndex], { open: 310, high: 315, low: 280, close: 300, volume: 6000 });
  Object.assign(data[lowIndex + 1], { open: 300, high: 320, low: 295, close: 310 });
  return data;
}

test("atualizacao de preco substitui candle duplicado", () => {
  const base = candles(3);
  const updated = mergeCandle(base, { ...base[2], close: 123 });
  assert.equal(updated.length, 3);
  assert.equal(updated[2].close, 123);
});

test("candle aberto nao entra no calculo do sinal", () => {
  const now = Date.now();
  const rows = [
    { time: 1, close: 100, closeTime: now - 1000, closed: true },
    { time: 2, close: 101, closeTime: now + 60000, closed: false },
  ];
  assert.deepEqual(closedCandles(rows, now).map((item) => item.time), [1]);
});

test("websocket agenda reconexao quando desconecta", () => {
  const originalSetTimeout = globalThis.setTimeout;
  let reconnects = 0;
  const sockets = [];
  globalThis.setTimeout = (fn) => {
    reconnects += 1;
    fn();
    return 1;
  };
  class FakeSocket {
    constructor() {
      sockets.push(this);
    }
    close() {}
  }
  const feed = createKlineSocket({ symbol: "BTCUSDT", interval: "15m", WebSocketImpl: FakeSocket });
  sockets[0].onclose();
  feed.close();
  globalThis.setTimeout = originalSetTimeout;
  assert.equal(reconnects, 1);
  assert.equal(sockets.length, 2);
});

test("renderizacao do grafico usa Lightweight Charts", () => {
  globalThis.window = { addEventListener() {}, removeEventListener() {} };
  const created = { candleData: [], lineData: [], priceLines: [] };
  const fakeSeries = {
    setData(data) { created.candleData = data; },
    createPriceLine(line) { created.priceLines.push(line); return line; },
    removePriceLine() {},
  };
  const fakeChart = {
    options: null,
    addCandlestickSeries: () => fakeSeries,
    addHistogramSeries: () => ({ setData() {} }),
    addLineSeries: () => ({ setData(data) { created.lineData = data; } }),
    applyOptions(options) { this.options = { ...this.options, ...options }; },
    timeScale: () => ({ fitContent() {} }),
    remove() {},
  };
  let chartOptions;
  const chart = createMarketChart(
    { getBoundingClientRect: () => ({ width: 800, height: 480 }) },
    { createChart: (_container, options) => { chartOptions = options; return fakeChart; }, CrosshairMode: { Normal: 0 } },
  );
  chart.update(candles(), {
    targets: [],
    supportZone: { lower: 96, upper: 98 },
    resistanceZone: { lower: 122, upper: 124 },
    fibonacci: { zones: [{ label: "50.0%", lower: 108, upper: 110 }] },
  });
  assert.equal(chartOptions.handleScroll.mouseWheel, true);
  assert.equal(chartOptions.handleScale.mouseWheel, true);
  assert.equal(chartOptions.handleScale.pinch, true);
  assert.ok(created.candleData.length > 0);
  assert.ok(created.lineData.length > 0);
  assert.deepEqual(created.priceLines.map((line) => line.title).sort(), ["Demanda max", "Demanda min", "Supply max", "Supply min"]);
});

test("renderizacao do grafico suporta Lightweight Charts v5", () => {
  globalThis.window = { addEventListener() {}, removeEventListener() {} };
  const calls = [];
  const fakeSeries = {
    setData(data) { calls.push(data); },
    createPriceLine(line) { return line; },
    removePriceLine() {},
  };
  const fakeChart = {
    addSeries(type, options) {
      calls.push({ type, options });
      return fakeSeries;
    },
    applyOptions() {},
    timeScale: () => ({ fitContent() {} }),
    remove() {},
  };
  const chart = createMarketChart(
    { getBoundingClientRect: () => ({ width: 800, height: 480 }) },
    {
      createChart: () => fakeChart,
      CrosshairMode: { Normal: 0 },
      CandlestickSeries: Symbol("CandlestickSeries"),
      HistogramSeries: Symbol("HistogramSeries"),
      LineSeries: Symbol("LineSeries"),
    },
  );
  chart.update(candles(), { targets: [], support: 100, resistance: 200 });
  assert.ok(calls.length > 4);
});

test("calculo de niveis retorna suporte, resistencia e indicadores", () => {
  const data = candles();
  const levels = supportResistance(data);
  const indicators = calculateIndicators(data);
  assert.ok(levels.support < levels.resistance);
  assert.ok(indicators.ema200.length === data.length);
  assert.ok(Number.isFinite(indicators.atr));
});

test("zonas de price action usam pivos confirmados com volume", () => {
  const levels = supportResistance(priceActionCandles());
  assert.ok(levels.supplyZones.length > 0);
  assert.ok(levels.demandZones.length > 0);
  assert.ok(levels.resistanceZone.lower < levels.resistanceZone.upper);
  assert.ok(levels.supportZone.lower < levels.supportZone.upper);
  assert.ok(["altista", "baixista", "neutro"].includes(levels.pocBias));
});

test("POC curto usa janela de 6h no dashboard", () => {
  const rows = [];
  for (let index = 0; index < 120; index += 1) {
    const price = index < 96 ? 100 : 200;
    rows.push({
      time: 1700000000 + index * 900,
      open: price,
      high: price + 1,
      low: price - 1,
      close: price,
      volume: 1000,
      closeTime: (1700000000 + index * 900) * 1000,
    });
  }
  const levels = supportResistance(rows);
  assert.ok(levels.poc < 150);
  assert.ok(levels.pocShort > 150);
});

test("tendencia detecta queda forte por movimento maior que dois ATR", () => {
  const rows = Array.from({ length: 8 }, (_, index) => ({
    time: 1700000000 + index * 900,
    open: 100 - index,
    high: 101 - index,
    low: 99 - index,
    close: 100 - index,
    volume: 1000,
    closeTime: (1700000000 + index * 900) * 1000,
  }));
  assert.equal(classifyTrend(rows, { atr: 2 }), "bearish_strong");
});

test("score progressivo e alerta de aproximacao antecipam zona quente", () => {
  const rows = [
    {
      time: 1700000000,
      open: 106,
      high: 107,
      low: 103,
      close: 104,
      volume: 1500,
      closeTime: 1700000000000,
    },
  ];
  const indicators = {
    atr: 10,
    volumeRatio: 1.3,
    pocBias: "altista",
    supportZone: { lower: 90, upper: 100 },
    resistanceZone: { lower: 130, upper: 140 },
    candlePatterns: { patterns: [] },
  };
  const alert = verificarAproximacaoZona(rows, indicators);
  const score = calculateProgressiveScore(rows, indicators);
  assert.equal(alert.alertType, "HOT_ZONE");
  assert.equal(alert.alertDirection, "compra");
  assert.ok(alert.alertMessage.includes("Prepare COMPRA"));
  assert.ok(score.score >= 60);
  assert.equal(score.phase, "hot");
});

test("motor de sinal retorna somente decisoes permitidas", () => {
  const up = candles(260, 1);
  const signal = buildAnalysis("BTCUSDT", "15m", { "5m": up, "15m": up, "1h": up, "4h": up });
  assert.ok(DECISIONS.includes(signal.decision));
  assert.equal(signal.symbol, "BTCUSDT");
});

test("motor de sinal sai de aguardar quando ha confluencia suficiente", () => {
  const up = candles(260, 1);
  const signal = buildAnalysis("BTCUSDT", "15m", { "5m": up, "15m": up, "1h": up, "4h": up }, {
    minRiskReward: 2,
    minStopLossPercent: 0.02,
    entryToleranceAtr: 999999,
  });
  assert.equal(signal.decision, "LONG_SETUP");
  assert.ok(signal.score >= 70);
});

test("periodo selecionado guia a analise principal do sinal", () => {
  const up = candles(260, 1);
  const down = candles(260, -1);
  const signal = buildAnalysis("BTCUSDT", "5m", { "5m": down, "15m": up, "1h": up, "4h": up }, {
    minRiskReward: 2,
    minStopLossPercent: 0.02,
  });
  assert.equal(signal.timeframe, "5m");
  assert.notEqual(signal.trends["5m"], signal.trends["15m"]);
  assert.notEqual(signal.decision, "LONG_SETUP");
});

test("stop loss respeita distancia minima configurada", () => {
  const data = candles();
  const signal = createDirectional(
    "LONG_SETUP",
    "BTCUSDT",
    "15m",
    data,
    { "4h": "bullish", "1h": "bullish", "15m": "bullish" },
    {
      atr: 0.1,
      support: 99.95,
      resistance: 105,
      volumeRatio: 1.5,
      volatility: 0.01,
    },
    { score: 80, reasons: [] },
    { minStopLossPercent: 0.02, minRiskReward: 2 },
  );
  const entryReference = (signal.entry[0] + signal.entry[1]) / 2;
  assert.ok(Math.abs((entryReference - signal.stop) / entryReference) >= 0.02);
  assert.ok(signal.stopLossPercent >= 2);
});

test("relogio de mercado mostra cripto 24h e sessoes globais", () => {
  const clock = getMarketClock(new Date("2026-09-08T13:00:00Z"));
  assert.equal(clock.length, 5);
  assert.equal(clock[0].name, "Cripto");
  assert.equal(clock[0].open, true);
  assert.ok(clock.every((session) => session.localTime));
});

test("cotacoes forex carregam pares solicitados por API publica", async () => {
  const calls = [];
  const fakeFetch = async (url) => {
    calls.push(String(url));
    const from = url.searchParams.get("from");
    return {
      ok: true,
      async json() {
        return {
          date: "2026-09-08",
          rates: from === "USD" ? { JPY: 147.5 } : from === "EUR" ? { USD: 1.08 } : { USD: 1.27 },
        };
      },
    };
  };
  const quotes = await fetchForexQuotes(["EUR/USD", "USD/JPY", "GBP/USD"], fakeFetch);
  assert.deepEqual(quotes.map((item) => item.symbol), ["EUR/USD", "USD/JPY", "GBP/USD"]);
  assert.equal(calls.length, 3);
  assert.equal(demoForexQuotes(["EUR/USD"]).length, 1);
});

test("alerta operacional dispara mesmo com decisao aguardar", () => {
  const storage = new Map();
  globalThis.localStorage = {
    getItem(key) { return storage.get(key) ?? null; },
    setItem(key, value) { storage.set(key, value); },
  };
  const element = { hidden: true, textContent: "" };
  const manager = createAlertManager({ element, cooldownMs: 1 });
  assert.equal(typeof manager.hasBeenQuiet, "function");
  assert.equal(manager.hasBeenQuiet(3), true);
  const notified = manager.notify({
    id: "BTCUSDT:WAIT:1",
    decision: "WAIT",
    alertType: "HOT_ZONE",
    alertMessage: "ZONA QUENTE - Prepare entrada",
  });
  assert.equal(notified, true);
  assert.equal(manager.hasBeenQuiet(3), false);
  assert.equal(element.hidden, false);
  assert.equal(element.textContent, "ZONA QUENTE - Prepare entrada");
});

test("dashboard nao contem chamadas de execucao de ordens", async () => {
  const files = await collectFiles(path.resolve("dashboard"));
  files.push(path.resolve("analysis_api.py"));
  const forbidden = /create_order|createOrder|create_oco_order|cancel_order|cancelOrder|futures_(account|order)|get_margin|getMargin|margin_order|leverage|place_market_order|SIDE_BUY|SIDE_SELL/i;
  for (const file of files) {
    const text = await readFile(file, "utf8");
    assert.equal(forbidden.test(text), false, file);
  }
});

async function collectFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await collectFiles(full));
    else files.push(full);
  }
  return files;
}

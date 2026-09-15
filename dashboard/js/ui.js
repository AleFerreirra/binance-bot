import { createAlertManager } from "./alerts.js";
import { createMarketChart } from "./chart.js";
import { calculateIndicators, last } from "./indicators.js";
import { getMarketClock } from "./marketClock.js";
import { closedCandles, createKlineSocket, demoCandles, demoForexQuotes, fetchBackendSignal, fetchForexQuotes, fetchInitialCandles, fetchLocalCandles, makeDemoFeed, mergeCandle } from "./marketData.js";
import { buildAnalysis } from "./signalEngine.js";
import { clearHistory, loadHistory, loadPrefs, savePrefs, saveSignal } from "./storage.js";

const FOREX_PAIRS = Object.freeze(["EUR/USD", "USD/JPY", "GBP/USD"]);

const els = {
  symbolSelect: document.querySelector("#symbolSelect"),
  timeframeSelect: document.querySelector("#timeframeSelect"),
  scoreFilter: document.querySelector("#scoreFilter"),
  scoreFilterValue: document.querySelector("#scoreFilterValue"),
  signalFilter: document.querySelector("#signalFilter"),
  demoToggle: document.querySelector("#demoToggle"),
  connectionStatus: document.querySelector("#connectionStatus"),
  uiState: document.querySelector("#uiState"),
  chartTitle: document.querySelector("#chartTitle"),
  symbolLabel: document.querySelector("#symbolLabel"),
  priceLabel: document.querySelector("#priceLabel"),
  changeLabel: document.querySelector("#changeLabel"),
  rangeLabel: document.querySelector("#rangeLabel"),
  volumeLabel: document.querySelector("#volumeLabel"),
  updatedLabel: document.querySelector("#updatedLabel"),
  localClock: document.querySelector("#localClock"),
  clockGrid: document.querySelector("#clockGrid"),
  chartNotice: document.querySelector("#chartNotice"),
  decisionLabel: document.querySelector("#decisionLabel"),
  scoreRing: document.querySelector("#scoreRing"),
  scoreLabel: document.querySelector("#scoreLabel"),
  waitMessage: document.querySelector("#waitMessage"),
  trend4h: document.querySelector("#trend4h"),
  trend1h: document.querySelector("#trend1h"),
  trend15m: document.querySelector("#trend15m"),
  entryLabel: document.querySelector("#entryLabel"),
  stopLabel: document.querySelector("#stopLabel"),
  gainPercentLabel: document.querySelector("#gainPercentLabel"),
  stopPercentLabel: document.querySelector("#stopPercentLabel"),
  targetsLabel: document.querySelector("#targetsLabel"),
  rrLabel: document.querySelector("#rrLabel"),
  reasonsList: document.querySelector("#reasonsList"),
  fibonacciList: document.querySelector("#fibonacciList"),
  prereqList: document.querySelector("#prereqList"),
  cancelList: document.querySelector("#cancelList"),
  trendCard: document.querySelector("#trendCard"),
  strengthCard: document.querySelector("#strengthCard"),
  volumeCard: document.querySelector("#volumeCard"),
  volatilityCard: document.querySelector("#volatilityCard"),
  supportCard: document.querySelector("#supportCard"),
  resistanceCard: document.querySelector("#resistanceCard"),
  riskCard: document.querySelector("#riskCard"),
  historyBody: document.querySelector("#historyBody"),
  emptyRowTemplate: document.querySelector("#emptyRowTemplate"),
  clearHistoryButton: document.querySelector("#clearHistoryButton"),
  alertBanner: document.querySelector("#alertBanner"),
};

let chart;
let socket;
let candlesByTimeframe = {};
let activeSignal;
let lastBackendFetch = 0;
let clockTimer;

const alertManager = createAlertManager({ element: els.alertBanner });

init();

async function init() {
  const prefs = loadPrefs();
  els.symbolSelect.value = prefs.symbol ?? "BTCUSDT";
  els.timeframeSelect.value = prefs.timeframe ?? "15m";
  els.scoreFilter.value = prefs.minScore ?? "0";
  els.signalFilter.value = prefs.signalType ?? "ALL";
  els.demoToggle.checked = Boolean(prefs.demo);
  els.scoreFilterValue.textContent = els.scoreFilter.value;
  updateControlsForSelectedPair();

  try {
    chart = createMarketChart(document.querySelector("#chart"));
    bindEvents();
    renderHistory();
    updateClock();
    clockTimer = setInterval(updateClock, 1000);
    await restart();
  } catch (error) {
    setConnection("error");
    setState("error", `Erro na interface: ${translateMessage(error.message)}`);
  }
}

function bindEvents() {
  for (const element of [els.timeframeSelect, els.signalFilter, els.demoToggle]) {
    element.addEventListener("change", restart);
  }
  els.symbolSelect.addEventListener("change", () => {
    updateControlsForSelectedPair();
    restart();
  });
  els.scoreFilter.addEventListener("input", () => {
    els.scoreFilterValue.textContent = els.scoreFilter.value;
    renderHistory();
    if (activeSignal) updateDecision(activeSignal);
  });
  els.clearHistoryButton.addEventListener("click", () => {
    clearHistory();
    renderHistory();
  });
}

async function restart() {
  socket?.close();
  savePrefs(currentPrefs());
  setState("loading", "Carregando");
  const symbol = els.symbolSelect.value;
  const timeframe = els.timeframeSelect.value;
  els.symbolLabel.textContent = symbol;
  els.chartTitle.textContent = `${symbol} - ${timeframe}`;

  try {
    if (isForexPair(symbol)) {
      await loadSelectedForexPair(symbol);
      return;
    }
    hideChartNotice();
    if (els.demoToggle.checked) {
      candlesByTimeframe = {
        "5m": demoCandles(320),
        "15m": demoCandles(320),
        "1h": demoCandles(320),
        "4h": demoCandles(320),
      };
      socket = makeDemoFeed({
        interval: timeframe,
        onStatus: setConnection,
        onCandle: (candle) => handleCandle(timeframe, candle),
      });
    } else {
      const frames = ["5m", "15m", "1h", "4h"];
      const rows = await Promise.all(frames.map((frame) => loadCandles(symbol, frame, 320)));
      candlesByTimeframe = Object.fromEntries(frames.map((frame, index) => [frame, rows[index]]));
      socket = createKlineSocket({
        symbol,
        interval: timeframe,
        onStatus: setConnection,
        onCandle: (candle) => handleCandle(timeframe, candle),
      });
    }
    refresh();
  } catch (error) {
    setConnection("error");
    setState("error", `Erro na API: ${translateMessage(error.message)}`);
  }
}

async function loadCandles(symbol, frame, limit) {
  if (location.protocol !== "file:") {
    try {
      return await fetchLocalCandles(symbol, frame, limit);
    } catch {
      return fetchInitialCandles(symbol, frame, limit);
    }
  }
  return fetchInitialCandles(symbol, frame, limit);
}

function handleCandle(timeframe, candle) {
  candlesByTimeframe[timeframe] = mergeCandle(candlesByTimeframe[timeframe] ?? [], candle);
  if (Date.now() - (candle.closeTime ?? candle.time * 1000) > 3 * 60 * 1000) {
    setState("stale", "Dados atrasados");
  }
  refresh();
}

function refresh() {
  const symbol = els.symbolSelect.value;
  const timeframe = els.timeframeSelect.value;
  const candles = candlesByTimeframe[timeframe] ?? [];
  const closedByTimeframe = Object.fromEntries(
    Object.entries(candlesByTimeframe).map(([frame, frameCandles]) => [frame, closedCandles(frameCandles)]),
  );
  const signalCandles = closedByTimeframe[timeframe] ?? [];
  if (signalCandles.length < 220) {
    setState("insufficient", "Dados insuficientes");
    return;
  }
  activeSignal = withAnalysisPercents(buildAnalysis(symbol, timeframe, closedByTimeframe, {
    minScore: Number(els.scoreFilter.value),
    minRiskReward: 2,
    minStopLossPercent: 0.02,
    useShortPoc: shouldUseShortPoc(),
  }));
  chart.update(candles, activeSignal);
  updateMarketOverview(candles);
  updateDecision(activeSignal);
  updateCards(candles, activeSignal);
  saveSignal(activeSignal);
  renderHistory();
  alertManager.notify(activeSignal);
  setState(activeSignal.decision === "WAIT" ? "waiting" : "connected", statusLabel(activeSignal.status));
  refreshBackendSignal(symbol, timeframe);
}

async function loadSelectedForexPair(symbol) {
  const [quote] = els.demoToggle.checked ? demoForexQuotes([symbol]) : await fetchForexQuotes([symbol]);
  if (!quote) throw new Error("Cotação de câmbio indisponível");
  const session = forexSession(symbol);
  const signal = forexReferenceSignal(symbol, quote, session);
  candlesByTimeframe = {};
  activeSignal = signal;
  updateForexOverview(signal, session);
  updateDecision(signal);
  updateForexCards(signal, session);
  renderHistory();
  showChartNotice(`Candles intradiários e sinais técnicos são exibidos apenas para pares Binance Spot. ${symbol} está em modo cotação de câmbio.`);
  setConnection("connected");
  setState("connected", "Cotação atualizada");
}

function forexSession(symbol) {
  if (symbol === "USD/JPY") return { open: "09:00 Tóquio", close: "16:00 Nova York" };
  if (symbol === "EUR/USD") return { open: "08:00 Londres", close: "16:00 Nova York" };
  if (symbol === "GBP/USD") return { open: "08:00 Londres", close: "16:00 Nova York" };
  return { open: "--", close: "--" };
}

function forexMarketLabel(symbol) {
  return {
    "EUR/USD": "Forex - Euro / Dólar",
    "USD/JPY": "Forex - Dólar / Iene",
    "GBP/USD": "Forex - Libra / Dólar",
  }[symbol] ?? "Forex";
}

function forexReferenceSignal(symbol, quote, session) {
  return {
    id: `${symbol}:FOREX:${quote.timestamp}`,
    timestamp: quote.timestamp,
    symbol,
    timeframe: "Câmbio",
    decision: "WAIT",
    score: 0,
    price: quote.price,
    trends: { "4h": "indefinida", "1h": "indefinida", "15m": "indefinida" },
    reasons: [`${forexMarketLabel(symbol)} com cotação pública de referência.`],
    prerequisites: [`Sessão de referência: abertura ${session.open}, fechamento ${session.close}.`],
    cancelConditions: ["Sem sinal técnico Binance para esta paridade."],
    entry: null,
    stop: null,
    targets: [],
    riskReward: 0,
    support: undefined,
    resistance: undefined,
    volatility: 0,
    volumeRatio: 0,
    confidence: "referência",
    trendStrength: "indefinida",
    status: "Cotação de referência",
    gainPercent: null,
    stopLossPercent: null,
  };
}

function updateControlsForSelectedPair() {
  const forex = isForexPair(els.symbolSelect.value);
  els.timeframeSelect.disabled = forex;
  els.scoreFilter.disabled = forex;
  els.signalFilter.disabled = forex;
}

function isForexPair(symbol) {
  return FOREX_PAIRS.includes(symbol);
}

function shouldUseShortPoc() {
  return typeof alertManager.hasBeenQuiet === "function" ? alertManager.hasBeenQuiet(3) : false;
}

function showChartNotice(message) {
  els.chartNotice.hidden = false;
  els.chartNotice.textContent = message;
  document.querySelector("#chart").hidden = true;
}

function hideChartNotice() {
  els.chartNotice.hidden = true;
  els.chartNotice.textContent = "";
  document.querySelector("#chart").hidden = false;
}

function updateClock() {
  const now = new Date();
  els.localClock.textContent = now.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  els.clockGrid.innerHTML = getMarketClock(now).map((session) => `
    <article class="clock-card" data-open="${session.open}">
      <strong>${session.name}</strong>
      <span>${session.region} - ${session.localTime}</span>
      <small>Abertura ${session.open} | Fechamento ${session.close}</small>
      <em>${session.label}</em>
    </article>
  `).join("");
}

async function refreshBackendSignal(symbol, timeframe) {
  if (els.demoToggle.checked || location.protocol === "file:") return;
  if (Date.now() - lastBackendFetch < 30000) return;
  lastBackendFetch = Date.now();
  try {
    const backendSignal = normalizeBackendSignal(await fetchBackendSignal(symbol, timeframe));
    if (activeSignal?.decision !== "WAIT" && backendSignal.decision === "WAIT") {
      return;
    }
    backendSignal.support ??= activeSignal?.support;
    backendSignal.resistance ??= activeSignal?.resistance;
    backendSignal.volatility ||= activeSignal?.volatility ?? 0;
    backendSignal.volumeRatio ||= activeSignal?.volumeRatio ?? 0;
    activeSignal = backendSignal;
    updateDecision(activeSignal);
    updateCards(candlesByTimeframe[timeframe] ?? [], activeSignal);
    saveSignal(activeSignal);
    renderHistory();
    alertManager.notify(activeSignal);
    setState(activeSignal.decision === "WAIT" ? "waiting" : "connected", statusLabel(activeSignal.status));
  } catch {
    // The local API is optional; browser-side analysis remains active.
  }
}

function normalizeBackendSignal(data) {
  return withAnalysisPercents({
    id: data.signal_id,
    timestamp: data.data_hora,
    symbol: data.ativo,
    timeframe: els.timeframeSelect.value,
    decision: data.decisao,
    score: Number(data.score),
    price: Number(data.preco_atual),
    trends: data.tendencias ?? {},
    reasons: data.justificativa ?? [],
    prerequisites: data.condicoes_antes_entrada ?? [],
    cancelConditions: data.condicoes_cancelam_sinal ?? [],
    entry: data.regiao_ideal_entrada ? data.regiao_ideal_entrada.map(Number) : null,
    stop: data.stop_loss_tecnico ? Number(data.stop_loss_tecnico) : null,
    targets: [data.alvo_1, data.alvo_2, data.alvo_3].filter(Boolean).map(Number),
    riskReward: Number(data.risco_retorno),
    support: undefined,
    resistance: undefined,
    volatility: 0,
    volumeRatio: 0,
    status: data.decisao === "WAIT" ? "aguardando confirmação" : "ativo",
    alertType: data.tipo_alerta ?? "",
    alertMessage: data.mensagem_alerta ?? "",
    alertDirection: data.direcao_alerta ?? "",
  });
}

function updateMarketOverview(candles) {
  const current = last(candles);
  const previous = candles[candles.length - 2] ?? current;
  const change = previous.close ? (current.close - previous.close) / previous.close : 0;
  const recent = candles.slice(-96);
  els.priceLabel.textContent = formatPrice(current.close);
  els.changeLabel.textContent = formatPercent(change);
  els.changeLabel.className = change >= 0 ? "positive" : "negative";
  els.rangeLabel.textContent = `${formatPrice(Math.max(...recent.map((item) => item.high)))} / ${formatPrice(Math.min(...recent.map((item) => item.low)))}`;
  els.volumeLabel.textContent = compact(current.volume);
  els.updatedLabel.textContent = new Date(current.closeTime || current.time * 1000).toLocaleString();
}

function updateForexOverview(signal, session) {
  els.chartTitle.textContent = `${signal.symbol} - Cotação Forex`;
  els.priceLabel.textContent = formatPrice(signal.price);
  els.changeLabel.textContent = "--";
  els.changeLabel.className = "";
  els.rangeLabel.textContent = `${session.open} / ${session.close}`;
  els.volumeLabel.textContent = "Forex OTC";
  els.updatedLabel.textContent = new Date(signal.timestamp).toLocaleString();
}

function updateDecision(signal) {
  const passesType = els.signalFilter.value === "ALL" || els.signalFilter.value === signal.decision;
  const passesScore = signal.score >= Number(els.scoreFilter.value);
  els.decisionLabel.textContent = passesType && passesScore ? signalLabel(signal.decision, signal) : signalLabel("WAIT");
  els.decisionLabel.className = decisionClassName(signal);
  els.scoreRing.style.setProperty("--score", signal.score);
  els.scoreLabel.textContent = String(signal.score);
  els.waitMessage.hidden = signal.decision !== "WAIT" || signal.score >= 30;
  els.trend4h.textContent = trendLabel(signal.trends["4h"]);
  els.trend1h.textContent = trendLabel(signal.trends["1h"]);
  els.trend15m.textContent = trendLabel(signal.trends["15m"]);
  els.entryLabel.textContent = signal.entry ? `${formatPrice(signal.entry[0])} - ${formatPrice(signal.entry[1])}` : "--";
  els.stopLabel.textContent = Number.isFinite(signal.stop) ? formatPrice(signal.stop) : "--";
  els.gainPercentLabel.textContent = formatPercentValue(signal.gainPercent);
  els.gainPercentLabel.className = Number(signal.gainPercent) > 0 ? "positive" : "";
  els.stopPercentLabel.textContent = formatPercentValue(signal.stopLossPercent);
  els.stopPercentLabel.className = Number(signal.stopLossPercent) > 0 ? "negative" : "";
  els.targetsLabel.textContent = signal.targets.length ? signal.targets.map(formatPrice).join(" | ") : "--";
  els.rrLabel.textContent = signal.riskReward ? `1:${signal.riskReward}` : "--";
  fillList(els.reasonsList, signal.reasons.map(translateMessage));
  fillList(els.fibonacciList, fibonacciItems(signal));
  fillList(els.prereqList, signal.prerequisites.map(translateMessage));
  fillList(els.cancelList, signal.cancelConditions.map(translateMessage));
}

function updateCards(candles, signal) {
  const ind = calculateIndicators(candles);
  els.trendCard.textContent = trendLabel(signal.trends[els.timeframeSelect.value] ?? signal.trends["15m"]);
  els.strengthCard.textContent = `${signal.score}/100`;
  els.volumeCard.textContent = `${ind.volumeRatio.toFixed(2)}x`;
  els.volatilityCard.textContent = formatPercent(ind.volatility);
  els.supportCard.textContent = formatZone(signal.supportZone);
  els.resistanceCard.textContent = formatZone(signal.resistanceZone);
  els.riskCard.textContent = signal.riskReward ? `1:${signal.riskReward}` : "inadequado";
}

function updateForexCards(signal, session) {
  els.trendCard.textContent = "Câmbio";
  els.strengthCard.textContent = "Referência";
  els.volumeCard.textContent = "OTC";
  els.volatilityCard.textContent = "--";
  els.supportCard.textContent = `Abre ${session.open}`;
  els.resistanceCard.textContent = `Fecha ${session.close}`;
  els.riskCard.textContent = "Sem sinal";
}

function renderHistory() {
  const minScore = Number(els.scoreFilter.value);
  const type = els.signalFilter.value;
  const selectedSymbol = els.symbolSelect.value;
  const rows = loadHistory().filter((item) => (
    item.symbol === selectedSymbol
    && item.score >= minScore
    && (type === "ALL" || item.decision === type)
  ));
  els.historyBody.innerHTML = "";
  if (!rows.length) {
    els.historyBody.append(els.emptyRowTemplate.content.cloneNode(true));
    return;
  }
  for (const item of rows.slice(0, 60)) {
    const tr = document.createElement("tr");
    const metrics = analysisPercents(item);
    tr.innerHTML = `
      <td>${new Date(item.timestamp).toLocaleString()}</td>
      <td>${item.symbol}</td>
      <td>${item.timeframe}</td>
      <td class="${decisionClass(item.decision)}">${signalLabel(item.decision)}</td>
      <td>${formatPrice(item.price)}</td>
      <td>${item.entry ? item.entry.map(formatPrice).join(" - ") : "--"}</td>
      <td>${Number.isFinite(item.stop) ? formatPrice(item.stop) : "--"}</td>
      <td class="${metrics.gainPercent > 0 ? "positive" : ""}">${formatPercentValue(metrics.gainPercent)}</td>
      <td class="${metrics.stopLossPercent > 0 ? "negative" : ""}">${formatPercentValue(metrics.stopLossPercent)}</td>
      <td>${item.targets?.length ? item.targets.map(formatPrice).join(" | ") : "--"}</td>
      <td>${item.score}</td>
      <td>${statusLabel(item.status)}</td>
    `;
    els.historyBody.append(tr);
  }
}

function fillList(element, items) {
  element.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    element.append(li);
  }
}

function setConnection(status) {
  const labels = {
    connecting: "Conectando",
    connected: "Conectado",
    disconnected: "Desconectado",
    error: "Erro",
  };
  els.connectionStatus.dataset.state = status === "connecting" ? "loading" : status;
  els.connectionStatus.querySelector("strong").textContent = labels[status] ?? status;
}

function setState(state, label) {
  els.uiState.textContent = label;
  els.uiState.dataset.state = state;
}

function signalLabel(decision, signal = {}) {
  if (decision === "WAIT" && signal.phaseLabel) return signal.phaseLabel;
  const labels = {
    LONG_SETUP: "COMPRA",
    SHORT_SETUP: "VENDA",
    WAIT: "AGUARDAR",
    INVALIDATED: "INVALIDADO",
  };
  return labels[decision] ?? decision;
}

function decisionClassName(signal) {
  if (signal.decision === "LONG_SETUP") return "long";
  if (signal.decision === "SHORT_SETUP" || signal.decision === "INVALIDATED") return "short";
  if (signal.score >= 85) return "long";
  if (signal.score >= 60) return "hot";
  if (signal.score >= 30) return "prepare";
  return "";
}

function trendLabel(trend) {
  const labels = {
    bullish: "Alta",
    bearish: "Baixa",
    bullish_strong: "Alta Forte",
    bearish_strong: "Baixa Forte",
    sideways: "Lateral",
    neutral: "Neutro",
    alta: "Alta",
    baixa: "Baixa",
    indefinida: "Indefinida",
  };
  return labels[trend] ?? labels[String(trend).toLowerCase()] ?? "--";
}

function statusLabel(status) {
  const labels = {
    ativo: "Ativo",
    "aguardando confirmacao": "Aguardando confirmação",
    "aguardando confirmação": "Aguardando confirmação",
    connected: "Conectado",
    disconnected: "Desconectado",
    waiting: "Aguardando confirmação",
    error: "Erro",
  };
  return labels[status] ?? labels[String(status).toLowerCase()] ?? translateMessage(status ?? "--");
}

function fibonacciItems(signal) {
  const zones = signal.fibonacci?.zones ?? [];
  if (!zones.length) return ["Sem zonas Fibonacci relevantes no momento."];
  return zones.map((zone) => `${zone.label}: ${formatPrice(zone.lower)} - ${formatPrice(zone.upper)}`);
}

function translateMessage(message) {
  if (!message) return "--";
  return String(message)
    .replaceAll("bullish", "alta")
    .replaceAll("bearish", "baixa")
    .replaceAll("sideways", "lateral")
    .replaceAll("neutral", "neutro")
    .replaceAll("ranging", "lateral")
    .replaceAll("trending", "tendência")
    .replaceAll("breakout", "rompimento")
    .replaceAll("volatile", "volátil")
    .replaceAll("oversold", "sobrevenda")
    .replaceAll("overbought", "sobrecompra")
    .replaceAll("timeframes", "períodos")
    .replaceAll("score", "pontuação")
    .replaceAll("setup", "configuração")
    .replaceAll("preco", "preço")
    .replaceAll("periodo", "período")
    .replaceAll("regiao", "região")
    .replaceAll("relacao", "relação")
    .replaceAll("confirmacao", "confirmação")
    .replaceAll("configuracao", "configuração")
    .replaceAll("tendencia", "tendência")
    .replaceAll("direcao", "direção")
    .replaceAll("media", "média")
    .replaceAll("nao", "não");
}

function decisionClass(decision) {
  if (decision === "LONG_SETUP") return "positive";
  if (decision === "SHORT_SETUP" || decision === "INVALIDATED") return "negative";
  return "";
}

function withAnalysisPercents(signal) {
  return { ...signal, ...analysisPercents(signal) };
}

function analysisPercents(signal) {
  if (!signal?.entry || !Number.isFinite(signal.stop) || !signal.targets?.length) {
    return { gainPercent: null, stopLossPercent: null };
  }
  const entryReference = (Number(signal.entry[0]) + Number(signal.entry[1])) / 2;
  const target1 = Number(signal.targets[0]);
  const stop = Number(signal.stop);
  if (!entryReference || !Number.isFinite(entryReference) || !Number.isFinite(target1) || !Number.isFinite(stop)) {
    return { gainPercent: null, stopLossPercent: null };
  }
  return {
    gainPercent: Math.abs((target1 - entryReference) / entryReference) * 100,
    stopLossPercent: Math.abs((entryReference - stop) / entryReference) * 100,
  };
}

function currentPrefs() {
  return {
    symbol: els.symbolSelect.value,
    timeframe: els.timeframeSelect.value,
    minScore: els.scoreFilter.value,
    signalType: els.signalFilter.value,
    demo: els.demoToggle.checked,
  };
}

function formatPrice(value) {
  if (!Number.isFinite(value)) return "--";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: value > 100 ? 2 : 6 });
}

function formatPercent(value) {
  if (!Number.isFinite(value)) return "--";
  return `${(value * 100).toFixed(2)}%`;
}

function formatPercentValue(value) {
  if (!Number.isFinite(value)) return "--";
  return `${Number(value).toFixed(2)}%`;
}

function formatZone(zone) {
  if (!zone || !Number.isFinite(zone.lower) || !Number.isFinite(zone.upper)) return "--";
  return `${formatPrice(zone.lower)} - ${formatPrice(zone.upper)}`;
}

function compact(value) {
  if (!Number.isFinite(value)) return "--";
  return Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

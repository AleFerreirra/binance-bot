// =========================================================================
// signalEngine.js - Analise profissional de sinais com pontuacao por confluencia
// =========================================================================

import { calculateIndicators, last } from "./indicators.js";

export const DECISIONS = Object.freeze(["LONG_SETUP", "SHORT_SETUP", "WAIT", "INVALIDATED"]);

export function buildAnalysis(symbol, timeframe, candlesByTimeframe, options = {}) {
  const decisionTimeframe = candlesByTimeframe["15m"]?.length ? "15m" : timeframe;
  const triggerTimeframe = candlesByTimeframe["5m"]?.length ? "5m" : decisionTimeframe;
  const setupCandles = candlesByTimeframe[decisionTimeframe] ?? candlesByTimeframe[timeframe] ?? [];
  const triggerCandles = candlesByTimeframe[triggerTimeframe] ?? setupCandles;
  if (setupCandles.length < 220) {
    return waitSignal(symbol, timeframe, setupCandles, "dados insuficientes para EMA 200");
  }

  const analysis = {};
  for (const [tf, candles] of Object.entries(candlesByTimeframe)) {
    if (candles.length >= 50) {
      const indicators = calculateIndicators(candles);
      analysis[tf] = { trend: classifyTrend(candles, indicators), indicators };
    }
  }

  const setup = analysis[decisionTimeframe] ?? analysis[timeframe];
  if (!setup) return waitSignal(symbol, timeframe, setupCandles, "sem dados de configuração");
  const current = last(setupCandles);
  const ind = setup.indicators;
  const trends = {
    "4h": analysis["4h"]?.trend ?? "sideways",
    "1h": analysis["1h"]?.trend ?? "sideways",
    "15m": analysis["15m"]?.trend ?? setup?.trend ?? "sideways",
    "5m": analysis["5m"]?.trend ?? "sideways",
  };
  const spread = options.spread ?? 0;
  const minScore = options.minScore ?? 0;
  const zoneAlert = zoneAlertSignal(setupCandles, ind);
  const progressive = calculateProgressiveScore(setupCandles, ind, options);
  const filters = marketFilters(ind, spread, options);
  if (filters.length) return waitSignal(symbol, timeframe, setupCandles, filters.join("; "), trends, ind, zoneAlert, progressive);

  const triggerSignal = triggerEntrySignal(symbol, timeframe, setupCandles, triggerCandles, trends, setup, ind, options, zoneAlert);
  if (triggerSignal) return triggerSignal;

  const reversalSignal = reversalZoneSignal(symbol, timeframe, setupCandles, trends, setup, ind, options, zoneAlert);
  if (reversalSignal) return reversalSignal;

  const continuationSignal = breakdownContinuationSignal(symbol, timeframe, setupCandles, trends, setup, ind, options, zoneAlert);
  if (continuationSignal) return continuationSignal;

  if (hasConflict(trends, setup.trend)) {
    return waitSignal(symbol, timeframe, setupCandles, "conflito relevante entre períodos", trends, ind, zoneAlert, progressive);
  }

  const long = directionScore("compra", trends, setup, options);
  const short = directionScore("venda", trends, setup, options);
  let signal;
  if (long.score >= short.score && long.score >= 70 && trendFollowingAllowed("compra", trends)) {
    signal = createDirectional("LONG_SETUP", symbol, timeframe, setupCandles, trends, ind, long, options);
  } else if (short.score > long.score && short.score >= 70 && trendFollowingAllowed("venda", trends)) {
    signal = createDirectional("SHORT_SETUP", symbol, timeframe, setupCandles, trends, ind, short, options);
  } else {
    return waitSignal(symbol, timeframe, setupCandles, "AGUARDAR - não há entrada válida neste momento", trends, ind, zoneAlert, progressive);
  }
  if (signal.score < minScore) {
    signal = waitSignal(symbol, timeframe, setupCandles, "pontuação abaixo do filtro", trends, ind, zoneAlert, progressive);
  }
  if (signal.riskReward < 2 && signal.decision !== "WAIT") {
    signal = waitSignal(symbol, timeframe, setupCandles, "relação risco/retorno inferior a 1:2", trends, ind, zoneAlert, progressive);
  }
  signal = enforceExecutableEntry(signal, setupCandles, ind, zoneAlert, options);
  if (zoneAlert) signal = { ...signal, ...zoneAlert };
  return signal;
}

export function classifyTrend(candles, indicators = calculateIndicators(candles)) {
  const close = last(candles).close;
  const strongMove = strongAtrMove(candles, indicators.atr || close * 0.01);
  if (strongMove) return strongMove;
  const ema21 = last(indicators.ema21);
  const ema50 = last(indicators.ema50);
  const ema200 = last(indicators.ema200);
  if (close > ema21 && ema21 > ema50 && close > ema200 && indicators.macd.histogram >= 0) return "bullish";
  if (close < ema21 && ema21 < ema50 && close < ema200 && indicators.macd.histogram <= 0) return "bearish";
  return "sideways";
}

function strongAtrMove(candles, atrValue) {
  const recent = candles.slice(-8);
  if (recent.length < 2 || !Number.isFinite(atrValue) || atrValue <= 0) return null;
  const first = recent[0].close;
  const current = last(recent).close;
  const move = current - first;
  if (move <= -2 * atrValue) return "bearish_strong";
  if (move >= 2 * atrValue) return "bullish_strong";
  return null;
}

function normalizeTrend(trend) {
  if (trend === "bullish_strong") return "bullish";
  if (trend === "bearish_strong") return "bearish";
  return trend;
}

export function directionScore(direction, trends, setup, options = {}) {
  const ind = setup.indicators;
  let score = 0;
  const reasons = [];
  const wanted = direction === "compra" ? "bullish" : "bearish";
  const wantedLabel = direction === "compra" ? "alta" : "baixa";
  const pocBias = ind.pocShortBias ?? ind.pocBias;
  const pocLabel = "POC 6h";

  // Multi-timeframe alignment (0-55 base)
  let alignedCount = 0;
  for (const tf of ["4h", "1h"]) {
    if (normalizeTrend(trends[tf]) === wanted) {
      score += 22;
      alignedCount += 1;
      reasons.push(`${tf} alinhado com tendência de ${wantedLabel}`);
    } else if (normalizeTrend(trends[tf]) === "sideways") {
      score += 6;
    }
  }
  if (normalizeTrend(setup.trend) === wanted) {
    score += 16;
    alignedCount += 1;
    reasons.push("período de configuração confirma a direção");
  }
  if ((direction === "compra" && pocBias === "altista") || (direction === "venda" && pocBias === "baixista")) {
    score += 8;
    reasons.push(`${pocLabel} confirma viés ${pocBias}`);
  } else if ((direction === "compra" && pocBias === "baixista") || (direction === "venda" && pocBias === "altista")) {
    score -= 8;
    reasons.push(`${pocLabel} contra a direção`);
  }
  const macroPocBias = ind.pocBias ?? "neutro";
  if (macroPocBias !== pocBias) {
    reasons.push(`POC 24h apenas como contexto macro: ${macroPocBias}`);
  }
  // Confluence bonus
  if (alignedCount >= 3) {
    score += 12;
    reasons.push("confluência de 3 ou mais períodos");
  }

  // EMA/VWAP position
  if (direction === "compra" && ind.distanceEma21 >= 0 && ind.distanceVwap >= 0) {
    score += 12;
    reasons.push("preço acima da EMA 21 e VWAP");
  }
  if (direction === "venda" && ind.distanceEma21 <= 0 && ind.distanceVwap <= 0) {
    score += 12;
    reasons.push("preço abaixo da EMA 21 e VWAP");
  }

  // Volume
  if (ind.volumeRatio >= 1.15) {
    score += 12;
    reasons.push(`volume ${ind.volumeRatio.toFixed(2)}x a média`);
  }

  // RSI zone
  if (direction === "compra" && ind.rsi >= 45 && ind.rsi <= 70) {
    score += 10;
    reasons.push(`RSI favorável: ${ind.rsi.toFixed(1)}`);
  }
  if (direction === "venda" && ind.rsi >= 30 && ind.rsi <= 55) {
    score += 10;
    reasons.push(`RSI favorável: ${ind.rsi.toFixed(1)}`);
  }

  // ADX bonus/penalty
  const adxVal = ind.adx ?? 20;
  if (adxVal >= 30) {
    score += 12;
    reasons.push(`ADX forte (${adxVal.toFixed(0)}): tendência definida`);
  } else if (adxVal >= 20) {
    score += 5;
  } else if (adxVal < 15) {
    score -= 10;
    reasons.push(`ADX fraco (${adxVal.toFixed(0)}): sem tendência definida`);
  }

  // Divergence bonus
  const rsiDiv = ind.rsiDivergence ?? "none";
  const macdDiv = ind.macdDivergence ?? "none";
  if (direction === "compra" && rsiDiv === "bullish") {
    score += 8;
    reasons.push("divergencia altista no RSI");
  }
  if (direction === "compra" && macdDiv === "bullish") {
    score += 4;
    reasons.push("divergencia altista no MACD");
  }
  if (direction === "venda" && rsiDiv === "bearish") {
    score += 8;
    reasons.push("divergencia baixista no RSI");
  }
  if (direction === "venda" && macdDiv === "bearish") {
    score += 4;
    reasons.push("divergencia baixista no MACD");
  }

  // Candle pattern confirmation
  const candleBias = ind.candlePatterns?.bias ?? "neutral";
  const patterns = ind.candlePatterns?.patterns ?? [];
  if (direction === "compra" && candleBias === "bullish") {
    score += 10;
    reasons.push(`padrão de candle altista: ${patterns.map(patternLabel).join(", ")}`);
  }
  if (direction === "venda" && candleBias === "bearish") {
    score += 10;
    reasons.push(`padrão de candle baixista: ${patterns.map(patternLabel).join(", ")}`);
  }

  // OBV confirmation
  const obvTrend = ind.obv?.trend ?? "neutral";
  if ((direction === "compra" && obvTrend === "bullish") || (direction === "venda" && obvTrend === "bearish")) {
    score += 8;
    reasons.push("OBV confirma pressão de volume na direção");
  }

  // Stochastic RSI confluence
  const stochSignal = ind.stochRsi?.signal ?? "neutral";
  if (direction === "compra" && stochSignal === "oversold") {
    score += 8;
    reasons.push("Stochastic RSI em sobrevenda (oportunidade)");
  }
  if (direction === "venda" && stochSignal === "overbought") {
    score += 8;
    reasons.push("Stochastic RSI em sobrecompra (oportunidade)");
  }

  // RSI extreme penalty
  if (direction === "compra" && ind.rsi > 80) {
    score -= 8;
    reasons.push(`RSI sobrecomprado (${ind.rsi.toFixed(0)}): risco de reversão`);
  }
  if (direction === "venda" && ind.rsi < 20) {
    score -= 8;
    reasons.push(`RSI sobrevendido (${ind.rsi.toFixed(0)}): risco de reversão`);
  }

  return { score: Math.min(100, Math.max(0, score)), reasons };
}

export function createDirectional(decision, symbol, timeframe, candles, trends, indicators, scored, options = {}) {
  const current = last(candles);
  const atrVal = indicators.atr || current.close * 0.01;
  const long = decision === "LONG_SETUP";
  const minStopLossPercent = options.minStopLossPercent ?? 0.02;
  const minRiskReward = options.minRiskReward ?? 2;
  const demandZone = indicators.supportZone ?? fallbackZone(current.close - atrVal, atrVal, "demand");
  const supplyZone = indicators.resistanceZone ?? fallbackZone(current.close + atrVal, atrVal, "supply");
  const entry = long
    ? [demandZone.lower, demandZone.upper]
    : [supplyZone.lower, supplyZone.upper];
  const entryReference = (entry[0] + entry[1]) / 2;
  const technicalStop = long ? demandZone.breakPrice - atrVal * 0.1 : supplyZone.breakPrice;
  const minimumDistanceStop = long
    ? entryReference * (1 - minStopLossPercent)
    : entryReference * (1 + minStopLossPercent);
  const stop = long
    ? Math.min(technicalStop, minimumDistanceStop)
    : Math.max(technicalStop, minimumDistanceStop);
  const risk = long ? entry[1] - stop : stop - entry[0];
  const targets = calcularAlvos(entryReference, stop, long);

  // Classify confidence
  const adxVal = indicators.adx ?? 20;
  const volRatio = indicators.volumeRatio ?? 1;
  let confidence;
  if (scored.score >= 85 && adxVal >= 30 && volRatio >= 1.2) confidence = "muito alta";
  else if (scored.score >= 75 && adxVal >= 20) confidence = "alta";
  else if (scored.score >= 65) confidence = "média";
  else confidence = "baixa";

  const regime = indicators.regime ?? "ranging";
  const trendStr = indicators.trendStrength?.label ?? "moderada";
  const momentum = indicators.momentum ?? "estável";

  const narrative = generateNarrative(
    decision, symbol, current.close, trends, scored, indicators, confidence, trendStr, momentum, regime,
  );

  return {
    id: `${symbol}:${timeframe}:${decision}:${Math.round(entry[0])}:${Math.round(stop)}`,
    timestamp: new Date(current.closeTime || current.time * 1000).toISOString(),
    symbol,
    timeframe,
    decision,
    score: scored.score,
    price: current.close,
    trends,
    reasons: scored.reasons,
    prerequisites: long
      ? ["aguardar fechamento acima da região de entrada", "confirmar reteste sem perder suporte", "volume deve seguir acima da média"]
      : ["aguardar fechamento abaixo da região de entrada", "confirmar rejeição de resistência", "volume deve confirmar o movimento"],
    cancelConditions: long
      ? ["fechamento abaixo do stop técnico", "perda do contexto maior", "spread ou liquidez fora do filtro"]
      : ["fechamento acima do stop técnico", "recuperação do contexto maior", "spread ou liquidez fora do filtro"],
    entry,
    stop,
    targets,
    riskReward: 2,
    stopLossPercent: Math.abs((entryReference - stop) / entryReference) * 100,
    gainPercent: Math.abs((targets[0] - entryReference) / entryReference) * 100,
    support: indicators.support,
    resistance: indicators.resistance,
    supportZone: indicators.supportZone,
    resistanceZone: indicators.resistanceZone,
    demandZones: indicators.demandZones ?? [],
    supplyZones: indicators.supplyZones ?? [],
    poc: indicators.poc,
    pocBias: indicators.pocBias,
    volatility: indicators.volatility,
    volumeRatio: indicators.volumeRatio,
    confidence,
    trendStrength: trendStr,
    trendStrengthScore: indicators.trendStrength?.score ?? 0,
    momentum,
    regime,
    narrative,
    candlePatterns: indicators.candlePatterns?.patterns?.map(patternLabel) ?? [],
    divergences: {
      rsi: indicators.rsiDivergence ?? "none",
      macd: indicators.macdDivergence ?? "none",
    },
    fibonacci: indicators.fibonacci ?? {},
    adx: adxVal,
    stochRsi: indicators.stochRsi ?? {},
    obv: indicators.obv ?? {},
    rsi: indicators.rsi,
    macdData: indicators.macd,
    status: "Ativo",
    alertType: "",
    alertMessage: "",
    alertDirection: "",
  };
}

export function calcularAlvos(entryReference, stop, long) {
  const risk = Math.max(Math.abs(entryReference - stop), 1e-9);
  const multipliers = [1, 1.5, 2];
  return multipliers.map((multiple) => long ? entryReference + risk * multiple : entryReference - risk * multiple);
}

function triggerEntrySignal(symbol, timeframe, setupCandles, triggerCandles, trends, setup, indicators, options, zoneAlert) {
  if (!triggerCandles?.length || triggerCandles === setupCandles) return null;
  const triggerIndicators = calculateIndicators(triggerCandles);
  const trigger = confirmarEntrada(setupCandles, triggerCandles, indicators, triggerIndicators);
  if (!trigger.valid) return null;
  if (!trendFollowingAllowed(trigger.direction, trends)) return null;
  const direction = trigger.direction === "compra" ? "LONG_SETUP" : "SHORT_SETUP";
  const scored = directionScore(trigger.direction, trends, setup, options);
  const signal = createDirectional(
    direction,
    symbol,
    timeframe,
    triggerCandles,
    trends,
    indicators,
    {
      score: Math.max(85, Math.min(100, scored.score + 18)),
      reasons: [...scored.reasons, ...trigger.reasons],
    },
    options,
  );
  const executable = enforceExecutableEntry(signal, triggerCandles, indicators, zoneAlert, options);
  return zoneAlert ? { ...executable, ...zoneAlert } : executable;
}

export function confirmarEntrada(contextCandles, triggerCandles, contextIndicators, triggerIndicators = calculateIndicators(triggerCandles)) {
  const contextCandle = last(contextCandles);
  const triggerCandle = last(triggerCandles);
  if (!contextCandle || !triggerCandle) return { valid: false, reasons: ["sem candles suficientes para gatilho"] };
  const atrVal = contextIndicators.atr || contextCandle.close * 0.01;
  const demand = contextIndicators.supportZone;
  const supply = contextIndicators.resistanceZone;
  const volumeOk = (triggerIndicators.volumeRatio ?? 0) >= 1;
  const wantedTrend = triggerIndicators.maTrend ?? "neutral";
  const body = Math.max(Math.abs(triggerCandle.close - triggerCandle.open), 1e-9);
  const lowerWick = Math.min(triggerCandle.close, triggerCandle.open) - triggerCandle.low;
  const upperWick = triggerCandle.high - Math.max(triggerCandle.close, triggerCandle.open);
  const patterns = triggerIndicators.candlePatterns?.patterns ?? [];
  const bullishPattern = lowerWick > body * 0.5
    || patterns.includes("pin_bar_bullish")
    || patterns.includes("bullish_engulfing");
  const bearishPattern = upperWick > body * 0.5
    || patterns.includes("pin_bar_bearish")
    || patterns.includes("bearish_engulfing");
  const nearDemand = demand && Math.abs(contextCandle.close - demand.upper) <= atrVal;
  const nearSupply = supply && Math.abs(contextCandle.close - supply.lower) <= atrVal;

  const bullishTrend = wantedTrend.startsWith("bullish") && triggerCandle.close > triggerCandle.open;
  const bearishTrend = wantedTrend.startsWith("bearish") && triggerCandle.close < triggerCandle.open;

  if (nearDemand && bullishPattern && bullishTrend && volumeOk) {
    return {
      valid: true,
      direction: "compra",
      reasons: [
        "contexto 15m próximo da zona de demanda",
        "gatilho 5m confirmou padrão comprador com volume",
      ],
    };
  }
  if (nearSupply && bearishPattern && bearishTrend && volumeOk) {
    return {
      valid: true,
      direction: "venda",
      reasons: [
        "contexto 15m próximo da zona de supply",
        "gatilho 5m confirmou padrão vendedor com volume",
      ],
    };
  }
  return { valid: false, reasons: ["gatilho 5m ainda sem padrão e volume confirmados"] };
}

function trendFollowingAllowed(direction, trends) {
  const wanted = direction === "compra" ? "bullish" : "bearish";
  const opposite = direction === "compra" ? "bearish" : "bullish";
  const setupTrend = normalizeTrend(trends["15m"]);
  const triggerTrend = normalizeTrend(trends["5m"]);
  const confirmationTrend = normalizeTrend(trends["1h"]);
  const contextTrend = normalizeTrend(trends["4h"]);
  return setupTrend === wanted
    && triggerTrend === wanted
    && confirmationTrend !== opposite
    && contextTrend !== opposite;
}

export function verificarTimeStop(position, now = new Date()) {
  if (!position?.openedAt) return { close: false, reason: "" };
  const openedAt = new Date(position.openedAt);
  const elapsedMs = now.getTime() - openedAt.getTime();
  const target1Hit = Boolean(position.target1Hit);
  if (elapsedMs >= 4 * 60 * 60 * 1000 && !target1Hit) {
    return { close: true, reason: "TIME_STOP_4H_SEM_ALVO_1" };
  }
  const brtHour = Number(new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo",
    hour: "2-digit",
    hour12: false,
  }).format(now));
  if (brtHour >= 22) {
    return { close: true, reason: "FECHAMENTO_MERCADO_22H_BRT" };
  }
  return { close: false, reason: "" };
}

function reversalZoneSignal(symbol, timeframe, candles, trends, setup, indicators, options, zoneAlert) {
  if (!trendFollowingAllowed("compra", trends)) return null;
  const demandZone = indicators.supportZone;
  if (!demandZone || !isDemandRejection(last(candles), indicators, demandZone)) return null;
  const scored = directionScore("compra", trends, setup, options);
  const signal = createDirectional(
    "LONG_SETUP",
    symbol,
    timeframe,
    candles,
    trends,
    indicators,
    {
      score: Math.max(70, Math.min(100, scored.score + 20)),
      reasons: [
        ...scored.reasons,
        "rejeição confirmada em zona de demanda",
        "RSI saindo de sobrevenda",
        "volume mínimo de reversão confirmado",
      ],
    },
    options,
  );
  if (signal.riskReward < (options.minRiskReward ?? 2)) {
    return waitSignal(symbol, timeframe, candles, "reversão em demanda sem relação risco/retorno mínima", trends, indicators, zoneAlert);
  }
  const executable = enforceExecutableEntry(signal, candles, indicators, zoneAlert, options);
  return zoneAlert ? { ...executable, ...zoneAlert } : executable;
}

function breakdownContinuationSignal(symbol, timeframe, candles, trends, setup, indicators, options, zoneAlert) {
  const candle = last(candles);
  const demandZone = indicators.supportZone;
  if (!candle || !demandZone) return null;
  const belowBreak = candle.close < demandZone.breakPrice;
  const volumeBreak = candle.volume > (indicators.volumeAverage || 1) * 1.3;
  const belowTrendRefs = indicators.distanceEma21 <= 0 && indicators.distanceVwap <= 0;
  if (!(belowBreak && volumeBreak && belowTrendRefs && isContinuationContext(trends, setup.trend, "bearish"))) return null;
  const scored = directionScore("venda", trends, setup, options);
  const signal = createDirectional(
    "SHORT_SETUP",
    symbol,
    timeframe,
    candles,
    trends,
    indicators,
    {
      score: Math.max(70, Math.min(100, scored.score + 15)),
      reasons: [
        ...scored.reasons,
        "fechamento abaixo do break_price da zona de demanda",
        "volume de rompimento acima de 1.3x a média",
        "preço abaixo da EMA 21 e VWAP",
      ],
    },
    options,
  );
  if (signal.riskReward < (options.minRiskReward ?? 2)) {
    return waitSignal(symbol, timeframe, candles, "rompimento sem relação risco/retorno mínima", trends, indicators, zoneAlert);
  }
  const executable = enforceExecutableEntry(signal, candles, indicators, zoneAlert, options);
  return zoneAlert ? { ...executable, ...zoneAlert } : executable;
}

export function enforceExecutableEntry(signal, candles, indicators = {}, zoneAlert = null, options = {}) {
  if (!signal || signal.decision === "WAIT" || !signal.entry) return signal;
  const candle = last(candles);
  if (!candle) return signal;
  const atrVal = indicators.atr || candle.close * 0.01;
  const tolerance = atrVal * (options.entryToleranceAtr ?? 0.05);
  const [entryLow, entryHigh] = signal.entry;
  const belowEntry = candle.close < entryLow - tolerance;
  const aboveEntry = candle.close > entryHigh + tolerance;
  if (!belowEntry && !aboveEntry) return signal;

  const long = signal.decision === "LONG_SETUP";
  const movedInFavor = long ? aboveEntry : belowEntry;
  const reason = movedInFavor
    ? "preço já se afastou da zona ideal; evitar perseguir movimento"
    : "preço fora da zona executável e contra o setup; aguardar novo reteste com confirmação";
  const directionLabel = long ? "compra" : "venda";
  const edge = long
    ? (aboveEntry ? entryHigh : entryLow)
    : (aboveEntry ? entryHigh : entryLow);
  return {
    ...signal,
    id: `${signal.symbol}:${signal.timeframe}:WAIT_RETEST:${Math.round(candle.close)}:${Math.round(edge)}`,
    decision: "WAIT",
    score: Math.min(signal.score, 59),
    phase: "prepare",
    phaseLabel: "AGUARDAR RETESTE",
    reasons: [reason, ...signal.reasons],
    prerequisites: [
      `aguardar preço retornar à zona de ${directionLabel}: ${entryLow.toFixed(2)} - ${entryHigh.toFixed(2)}`,
      "exigir fechamento confirmado dentro da zona antes de validar entrada",
      ...signal.prerequisites,
    ],
    status: "Aguardando reteste",
    alertType: zoneAlert?.alertType ?? "ENTRY_OUT_OF_ZONE",
    alertMessage: zoneAlert?.alertMessage ?? `AGUARDAR RETESTE - preço fora da zona executável de ${directionLabel}`,
    alertDirection: zoneAlert?.alertDirection ?? directionLabel,
  };
}

function isContinuationContext(trends, setupTrend, wanted) {
  return normalizeTrend(setupTrend) === wanted
    && normalizeTrend(trends["1h"]) === wanted
    && normalizeTrend(trends["4h"]) === wanted;
}

function isDemandRejection(candle, indicators, demandZone) {
  if (!candle) return false;
  const body = Math.max(Math.abs(candle.close - candle.open), 1e-9);
  const lowerWick = Math.min(candle.close, candle.open) - candle.low;
  const touched = candle.low <= demandZone.upper && candle.high >= demandZone.lower;
  const closedBackAboveZoneEdge = candle.close >= demandZone.lower;
  const aboveInvalidation = candle.close > demandZone.breakPrice;
  const rsiRecovering = (indicators.rsiPrev ?? 50) <= 35 && indicators.rsi > (indicators.rsiPrev ?? 50);
  const volumeOk = candle.volume >= (indicators.volumeAverage || 1) * 0.8;
  const wickOk = lowerWick > body * 0.5;
  return touched && closedBackAboveZoneEdge && aboveInvalidation && wickOk && rsiRecovering && volumeOk;
}

function fallbackZone(center, atrVal, type) {
  const lower = center - atrVal * 0.5;
  const upper = center + atrVal * 0.5;
  return { type, center, lower, upper, breakPrice: type === "supply" ? upper + atrVal : lower - atrVal };
}

function generateNarrative(decision, symbol, price, trends, scored, ind, confidence, trendStr, momentum, regime) {
  const dir = decision === "LONG_SETUP" ? "alta" : "baixa";
  const dirLabel = decision === "LONG_SETUP" ? "compra" : "venda";
  const aligned = Object.values(trends).filter((t) => normalizeTrend(t) === (dir === "alta" ? "bullish" : "bearish")).length;
  const total = Object.keys(trends).length;
  const rsiVal = ind.rsi ?? 50;
  const adxVal = ind.adx ?? 20;
  const volRatio = ind.volumeRatio ?? 1;
  const patterns = ind.candlePatterns?.patterns ?? [];
  const parts = [
    `${symbol} apresenta configuração de ${dirLabel} com pontuação ${scored.score}/100 e confiança ${confidence}.`,
    `Tendência ${trendStr} com ${aligned}/${total} períodos alinhados para ${dir} e movimento ${momentum}.`,
  ];
  if (regime === "trending") parts.push("Mercado em regime de tendência.");
  else if (regime === "breakout") parts.push("Rompimento detectado — alta probabilidade de continuação.");
  else if (regime === "volatile") parts.push("Atenção: mercado volátil, controle o tamanho da posição.");
  else parts.push("Mercado em consolidação — aguardar rompimento para maior convicção.");
  if (adxVal >= 30) parts.push(`ADX em ${adxVal.toFixed(0)} confirma força direcional.`);
  else if (adxVal < 15) parts.push(`ADX baixo (${adxVal.toFixed(0)}): tendência fraca, cautela recomendada.`);
  if (volRatio >= 1.5) parts.push(`Volume ${volRatio.toFixed(1)}x acima da média — forte participação.`);
  else if (volRatio < 0.7) parts.push(`Volume abaixo da média (${volRatio.toFixed(1)}x) — pode faltar força.`);
  const rsiDiv = ind.rsiDivergence ?? "none";
  if (rsiDiv !== "none") parts.push(`Divergência ${patternLabel(rsiDiv)} no RSI detectada.`);
  if (patterns.length) parts.push(`Padrões de candle: ${patterns.map(patternLabel).join(", ")}.`);
  if (ind.poc) parts.push(`POC 24h em ${ind.poc.toFixed(2)}; viés pelo POC: ${ind.pocBias}.`);
  const fib = ind.fibonacci;
  if (fib?.nearest) parts.push(`Preço próximo da zona de atração Fibonacci ${fib.nearest.label} (${fib.nearest.price.toFixed(2)}).`);
  return parts.join(" ");
}

export function marketFilters(indicators, spread, options = {}) {
  const reasons = [];
  if (spread > (options.maxSpread ?? 0.003)) reasons.push("spread elevado");
  if (indicators.volumeRatio < (options.minVolumeRatio ?? 0.5)) reasons.push("volume insuficiente");
  if (indicators.volatility > (options.maxVolatility ?? 0.05)) reasons.push("volatilidade acima do filtro");
  return reasons;
}

export function hasConflict(trends, setupTrend) {
  const trend4h = normalizeTrend(trends["4h"]);
  const trend1h = normalizeTrend(trends["1h"]);
  const setup = normalizeTrend(setupTrend);
  return (trend4h === "bullish" && trend1h === "bearish")
    || (trend4h === "bearish" && trend1h === "bullish")
    || (trend4h !== "sideways" && setup !== "sideways" && trend4h !== setup);
}

function zoneAlertSignal(candles, indicators) {
  const candle = last(candles);
  if (!candle) return null;
  const price = candle.close;
  const atrVal = indicators.atr || price * 0.01;
  const volumeAverage = indicators.volumeAverage || 1;
  const body = Math.abs(candle.close - candle.open) || 1e-9;
  const upperWick = candle.high - Math.max(candle.close, candle.open);
  const lowerWick = Math.min(candle.close, candle.open) - candle.low;
  const alerts = [];
  const approach = verificarAproximacaoZona(candles, indicators);
  if (approach) alerts.push(approach);
  for (const item of [
    { kind: "supply", zone: indicators.resistanceZone, direction: "venda", label: "Supply" },
    { kind: "demand", zone: indicators.supportZone, direction: "compra", label: "Demand" },
  ]) {
    const { kind, zone, direction, label } = item;
    if (!zone) continue;
    const distance = Math.min(Math.abs(price - zone.lower), Math.abs(price - zone.upper), Math.abs(price - zone.center));
    const touched = candle.low <= zone.upper && candle.high >= zone.lower;
    if (kind === "supply" && candle.close > zone.upper && candle.volume > volumeAverage * 1.3) {
      alerts.push(alertPayload("MICRO_BREAKOUT", "ROMPEU ZONA - Entre no sentido do rompimento com stop na borda oposta", "compra", zone, 3));
    } else if (kind === "demand" && candle.close < zone.lower && candle.volume > volumeAverage * 1.3) {
      alerts.push(alertPayload("MICRO_BREAKOUT", "ROMPEU ZONA - Entre no sentido do rompimento com stop na borda oposta", "venda", zone, 3));
    }
    if (touched && kind === "supply" && upperWick > body * 0.5) {
      alerts.push(alertPayload("REJECTION", "REJEIÇÃO CONFIRMADA - Entre na direção contrária à zona", "venda", zone, 2));
    } else if (touched && kind === "demand" && lowerWick > body * 0.5) {
      alerts.push(alertPayload("REJECTION", "REJEIÇÃO CONFIRMADA - Entre na direção contrária à zona", "compra", zone, 2));
    }
    if (distance <= atrVal * 0.5) {
      alerts.push(alertPayload("HOT_ZONE", "ZONA QUENTE - Prepare entrada", direction, zone, 1, label));
    }
  }
  return alerts.sort((a, b) => b.alertPriority - a.alertPriority)[0] ?? null;
}

export function verificarAproximacaoZona(candles, indicators, thresholdAtr = 0.5) {
  const candle = last(candles);
  if (!candle) return null;
  const atrVal = indicators.atr || candle.close * 0.01;
  const demand = indicators.supportZone;
  const supply = indicators.resistanceZone;
  const demandDistance = demand ? Math.abs(candle.close - demand.upper) : Number.POSITIVE_INFINITY;
  const supplyDistance = supply ? Math.abs(candle.close - supply.lower) : Number.POSITIVE_INFINITY;
  const threshold = atrVal * thresholdAtr;
  if (demand && demandDistance <= threshold && candle.close >= demand.upper) {
    return alertPayload(
      "HOT_ZONE",
      `ZONA QUENTE - Prepare COMPRA na região de ${demand.upper.toFixed(2)}. Aguarde vela de rejeição.`,
      "compra",
      demand,
      1.5,
      "Demand",
    );
  }
  if (supply && supplyDistance <= threshold && candle.close <= supply.lower) {
    return alertPayload(
      "HOT_ZONE",
      `ZONA QUENTE - Prepare VENDA na região de ${supply.lower.toFixed(2)}. Aguarde vela de rejeição.`,
      "venda",
      supply,
      1.5,
      "Supply",
    );
  }
  return null;
}

export function calculateProgressiveScore(candles, indicators, options = {}) {
  const candle = last(candles);
  if (!candle) return { score: 0, phaseLabel: "AGUARDAR", phase: "wait", reasons: ["sem candles suficientes"] };
  const atrVal = indicators.atr || candle.close * 0.01;
  const nearest = nearestZoneDistance(candle.close, indicators);
  const distanceScore = nearest.distance <= atrVal * 0.5
    ? 35
    : nearest.distance <= atrVal
      ? 25
      : nearest.distance <= atrVal * 2
        ? 10
        : 0;
  const volumeRatio = indicators.volumeRatio ?? 1;
  const volumeScore = volumeRatio >= 1.3 ? 20 : volumeRatio >= 1 ? 14 : volumeRatio >= 0.8 ? 8 : 0;
  const pocBias = options.useShortPoc ? indicators.pocShortBias : indicators.pocBias;
  const pocScore = nearest.kind === "demand" && pocBias === "altista" ? 15
    : nearest.kind === "supply" && pocBias === "baixista" ? 15
      : pocBias === "neutro" ? 6 : 0;
  const candleScore = candlePatternScore(candles, indicators, nearest.kind);
  const score = Math.min(100, Math.round(distanceScore + volumeScore + pocScore + candleScore));
  return {
    score,
    phase: score >= 85 ? "entry" : score >= 60 ? "hot" : score >= 30 ? "prepare" : "wait",
    phaseLabel: score >= 85 ? "ENTRADA VÁLIDA" : score >= 60 ? "ZONA QUENTE" : score >= 30 ? "PREPARE-SE" : "AGUARDAR",
    reasons: [
      `distância da zona: ${distanceScore}/35`,
      `volume: ${volumeScore}/20`,
      `alinhamento com POC: ${pocScore}/15`,
      `padrão de vela: ${candleScore}/30`,
    ],
  };
}

function nearestZoneDistance(price, indicators) {
  const demandDistance = indicators.supportZone ? Math.abs(price - indicators.supportZone.upper) : Number.POSITIVE_INFINITY;
  const supplyDistance = indicators.resistanceZone ? Math.abs(price - indicators.resistanceZone.lower) : Number.POSITIVE_INFINITY;
  return demandDistance <= supplyDistance
    ? { kind: "demand", distance: demandDistance }
    : { kind: "supply", distance: supplyDistance };
}

function candlePatternScore(candles, indicators, nearestKind) {
  const candle = last(candles);
  const body = Math.max(Math.abs(candle.close - candle.open), 1e-9);
  const lowerWick = Math.min(candle.close, candle.open) - candle.low;
  const upperWick = candle.high - Math.max(candle.close, candle.open);
  const patterns = indicators.candlePatterns?.patterns ?? [];
  const bullishRejection = nearestKind === "demand" && lowerWick > body * 0.5;
  const bearishRejection = nearestKind === "supply" && upperWick > body * 0.5;
  if ((bullishRejection || bearishRejection) && (indicators.volumeRatio ?? 1) >= 1.15) return 30;
  if (bullishRejection || bearishRejection) return 22;
  if (patterns.length) return 10;
  return 0;
}

function alertPayload(type, message, direction, zone, priority, label = "") {
  return {
    alertType: type,
    alertMessage: `${message} (${label || zone.type}: ${zone.lower.toFixed(2)} - ${zone.upper.toFixed(2)})`,
    alertDirection: direction,
    alertPriority: priority,
  };
}

export function waitSignal(symbol, timeframe, candles, reason, trends = {}, indicators = {}, zoneAlert = null, progressive = null) {
  const current = last(candles, { close: 0, closeTime: Date.now(), time: Date.now() / 1000 });
  const scoreState = progressive ?? calculateProgressiveScore(candles, indicators);
  const regime = indicators.regime ?? "ranging";
  const trendStr = indicators.trendStrength?.label ?? "moderada";
  const momentum = indicators.momentum ?? "estável";
  const narrative = `${symbol} sem configuração válida no momento. Regime: ${regimeLabel(regime)}, tendência: ${trendStr}, movimento: ${momentum}. Motivos: ${reason}. Aguardar nova estrutura com confirmação.`;
  return {
    id: `${symbol}:${timeframe}:WAIT:${Math.round(current.close)}`,
    timestamp: new Date(current.closeTime || current.time * 1000).toISOString(),
    symbol,
    timeframe,
    decision: "WAIT",
    score: scoreState.score,
    phase: scoreState.phase,
    phaseLabel: scoreState.phaseLabel,
    price: current.close,
    trends: { "4h": trends["4h"] ?? "sideways", "1h": trends["1h"] ?? "sideways", "15m": trends["15m"] ?? "sideways", "5m": trends["5m"] ?? "sideways" },
    reasons: [reason, ...(scoreState.reasons ?? [])],
    prerequisites: ["aguardar fechamento com confirmação de tendência, volume e risco/retorno"],
    cancelConditions: ["volume insuficiente", "conflito entre períodos", "relação risco/retorno inadequada"],
    entry: null,
    stop: null,
    targets: [],
    riskReward: 0,
    support: indicators.support,
    resistance: indicators.resistance,
    supportZone: indicators.supportZone,
    resistanceZone: indicators.resistanceZone,
    demandZones: indicators.demandZones ?? [],
    supplyZones: indicators.supplyZones ?? [],
    poc: indicators.poc,
    pocBias: indicators.pocBias,
    volatility: indicators.volatility ?? 0,
    volumeRatio: indicators.volumeRatio ?? 0,
    confidence: "baixa",
    trendStrength: trendStr,
    trendStrengthScore: indicators.trendStrength?.score ?? 0,
    momentum,
    regime,
    narrative,
    candlePatterns: indicators.candlePatterns?.patterns ?? [],
    divergences: { rsi: indicators.rsiDivergence ?? "none", macd: indicators.macdDivergence ?? "none" },
    fibonacci: indicators.fibonacci ?? {},
    adx: indicators.adx ?? 20,
    stochRsi: indicators.stochRsi ?? {},
    obv: indicators.obv ?? {},
    rsi: indicators.rsi ?? 50,
    macdData: indicators.macd ?? {},
    status: "Aguardando confirmação",
    alertType: zoneAlert?.alertType ?? "",
    alertMessage: zoneAlert?.alertMessage ?? "",
    alertDirection: zoneAlert?.alertDirection ?? "",
  };
}

function patternLabel(pattern) {
  const labels = {
    hammer: "martelo",
    bullish: "altista",
    bearish: "baixista",
    none: "nenhuma",
    shooting_star: "estrela cadente",
    pin_bar_bullish: "pin bar altista",
    pin_bar_bearish: "pin bar baixista",
    bullish_engulfing: "engolfo de alta",
    bearish_engulfing: "engolfo de baixa",
    morning_star: "estrela da manhã",
    evening_star: "estrela da noite",
  };
  return labels[pattern] ?? String(pattern).replaceAll("_", " ");
}

function regimeLabel(regime) {
  return {
    ranging: "lateral",
    trending: "em tendência",
    breakout: "rompimento",
    volatile: "volátil",
  }[regime] ?? regime;
}

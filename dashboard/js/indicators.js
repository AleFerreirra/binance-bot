// =========================================================================
// indicators.js — Professional-grade technical indicators (browser-side)
// =========================================================================

export function ema(values, period) {
  if (!values.length) return [];
  const multiplier = 2 / (period + 1);
  const result = [];
  let previous = Number(values[0]);
  for (const value of values) {
    previous = Number(value) * multiplier + previous * (1 - multiplier);
    result.push(previous);
  }
  return result;
}

export function rsi(values, period = 14) {
  if (values.length <= period) return 50;
  const series = rsiSeries(values, period);
  return last(series, 50);
}

export function rsiSeries(values, period = 14) {
  const result = Array(values.length).fill(50);
  if (values.length <= period) return result;
  let gain = 0;
  let loss = 0;
  for (let index = 1; index <= period; index += 1) {
    const diff = values[index] - values[index - 1];
    if (diff >= 0) gain += diff;
    else loss += Math.abs(diff);
  }
  gain /= period;
  loss /= period;
  result[period] = loss === 0 ? 100 : gain === 0 ? 0 : 100 - 100 / (1 + gain / loss);
  for (let index = period + 1; index < values.length; index += 1) {
    const diff = values[index] - values[index - 1];
    const currentGain = diff > 0 ? diff : 0;
    const currentLoss = diff < 0 ? Math.abs(diff) : 0;
    gain = (gain * (period - 1) + currentGain) / period;
    loss = (loss * (period - 1) + currentLoss) / period;
    result[index] = loss === 0 ? 100 : gain === 0 ? 0 : 100 - 100 / (1 + gain / loss);
  }
  return result;
}

export function atr(candles, period = 14) {
  if (candles.length <= period) return 0;
  const ranges = [];
  for (let index = 1; index < candles.length; index += 1) {
    const candle = candles[index];
    const previous = candles[index - 1];
    ranges.push(Math.max(
      candle.high - candle.low,
      Math.abs(candle.high - previous.close),
      Math.abs(candle.low - previous.close),
    ));
  }
  let smoothed = average(ranges.slice(0, period));
  for (let index = period; index < ranges.length; index += 1) {
    smoothed = (smoothed * (period - 1) + ranges[index]) / period;
  }
  return smoothed;
}

export function macd(values, fast = 12, slow = 26, signal = 9) {
  const fastEma = ema(values, fast);
  const slowEma = ema(values, slow);
  const line = fastEma.map((value, index) => value - slowEma[index]);
  const signalLine = ema(line, signal);
  const histogram = line.map((value, index) => value - signalLine[index]);
  return {
    macd: last(line, 0),
    signal: last(signalLine, 0),
    histogram: last(histogram, 0),
    histogramPrev: histogram.length > 1 ? histogram[histogram.length - 2] : 0,
    lineSeries: line,
    signalSeries: signalLine,
    histogramSeries: histogram,
  };
}

export function vwap(candles, period = 50) {
  const recent = candles.slice(-period);
  const volume = recent.reduce((sum, candle) => sum + candle.volume, 0);
  if (!volume) return last(candles)?.close ?? 0;
  const notional = recent.reduce((sum, candle) => {
    const typical = (candle.high + candle.low + candle.close) / 3;
    return sum + typical * candle.volume;
  }, 0);
  return notional / volume;
}

export function supportResistance(candles, period = 40) {
  const current = last(candles)?.close ?? 0;
  const atrValue = atr(candles, 14) || current * 0.01;
  const poc = pointOfControl(candles);
  const pocShort = pointOfControl(candles, 48, 24);
  const pivots = confirmedVolumePivots(candles, atrValue);
  const supplyZones = zonesFromPivots(pivots, "high", atrValue, current, poc);
  const demandZones = zonesFromPivots(pivots, "low", atrValue, current, poc);
  const resistanceZone = nearestZone(supplyZones, current, true);
  const supportZone = nearestZone(demandZones, current, false);
  return {
    support: supportZone?.center ?? current - atrValue,
    resistance: resistanceZone?.center ?? current + atrValue,
    supportZone,
    resistanceZone,
    demandZones,
    supplyZones,
    poc,
    pocShort,
    pocBias: current > poc ? "altista" : current < poc ? "baixista" : "neutro",
    pocShortBias: current > pocShort ? "altista" : current < pocShort ? "baixista" : "neutro",
    pivots,
  };
}

function confirmedVolumePivots(candles, atrValue, lookback = 5) {
  const volumeAverage = rollingAverage(candles.map((item) => item.volume), 20);
  const pivots = [];
  for (let index = lookback; index < candles.length - 1; index += 1) {
    const candle = candles[index];
    const next = candles[index + 1];
    const previous = candles.slice(index - lookback, index);
    if (candle.volume <= volumeAverage[index]) continue;
    if (candle.high > Math.max(...previous.map((item) => item.high)) && next.close < candle.high) {
      pivots.push(pivotPayload("high", index, candle.high, candle, atrValue, volumeAverage[index]));
    }
    if (candle.low < Math.min(...previous.map((item) => item.low)) && next.close > candle.low) {
      pivots.push(pivotPayload("low", index, candle.low, candle, atrValue, volumeAverage[index]));
    }
  }
  return pivots.slice(-30);
}

function pivotPayload(type, index, price, candle, atrValue, volumeAverage) {
  return {
    type,
    index,
    time: candle.time,
    price,
    volume: candle.volume,
    volumeRatio: candle.volume / Math.max(volumeAverage, 1e-9),
    atr: atrValue,
  };
}

function zonesFromPivots(pivots, kind, atrValue, current, poc) {
  return pivots
    .filter((pivot) => pivot.type === kind)
    .map((pivot) => {
      const center = pivot.price;
      const lower = center - atrValue * 0.5;
      const upper = center + atrValue * 0.5;
      const supply = kind === "high";
      return {
        type: supply ? "supply" : "demand",
        center,
        lower,
        upper,
        breakPrice: supply ? upper + atrValue : lower - atrValue,
        volumeRatio: pivot.volumeRatio,
        validByPoc: supply ? current < poc : current > poc,
        time: pivot.time,
      };
    })
    .filter((zone) => zone.type === "supply" ? current <= zone.breakPrice : current >= zone.breakPrice)
    .sort((a, b) => Number(a.validByPoc !== b.validByPoc) || Math.abs(a.center - current) - Math.abs(b.center - current))
    .slice(0, 5);
}

function nearestZone(zones, current, above) {
  const directional = above ? zones.filter((zone) => zone.center >= current) : zones.filter((zone) => zone.center <= current);
  const candidates = directional.length ? directional : zones;
  return candidates.length ? candidates.reduce((best, zone) => Math.abs(zone.center - current) < Math.abs(best.center - current) ? zone : best) : null;
}

function pointOfControl(candles, bins = 48, window = 96) {
  const recent = candles.slice(-window);
  const prices = recent.map((item) => (item.high + item.low + item.close) / 3);
  const volumes = recent.map((item) => item.volume);
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return last(candles)?.close ?? 0;
  const totals = Array(bins).fill(0);
  for (const [index, price] of prices.entries()) {
    const bucket = Math.min(bins - 1, Math.max(0, Math.floor(((price - low) / (high - low)) * bins)));
    totals[bucket] += volumes[index];
  }
  const maxIndex = totals.indexOf(Math.max(...totals));
  const step = (high - low) / bins;
  return low + step * (maxIndex + 0.5);
}

export function analyzeStructure(candles) {
  const recent = candles.slice(-12);
  const first = recent.slice(0, 6);
  const second = recent.slice(6);
  const firstHigh = Math.max(...first.map((item) => item.high));
  const firstLow = Math.min(...first.map((item) => item.low));
  const secondHigh = Math.max(...second.map((item) => item.high));
  const secondLow = Math.min(...second.map((item) => item.low));
  if (secondHigh > firstHigh && secondLow > firstLow) return "higher_highs_higher_lows";
  if (secondHigh < firstHigh && secondLow < firstLow) return "lower_highs_lower_lows";
  return "range";
}

// =========================================================================
// NEW: ADX (Average Directional Index)
// =========================================================================

export function adx(candles, period = 14) {
  if (candles.length < period * 2 + 1) return { adx: 20, plusDi: 25, minusDi: 25 };
  const trArr = [];
  const plusDmArr = [];
  const minusDmArr = [];
  for (let i = 1; i < candles.length; i++) {
    const curr = candles[i];
    const prev = candles[i - 1];
    trArr.push(Math.max(curr.high - curr.low, Math.abs(curr.high - prev.close), Math.abs(curr.low - prev.close)));
    const upMove = curr.high - prev.high;
    const downMove = prev.low - curr.low;
    plusDmArr.push(upMove > downMove && upMove > 0 ? upMove : 0);
    minusDmArr.push(downMove > upMove && downMove > 0 ? downMove : 0);
  }
  const smoothTr = smoothedAverage(trArr, period);
  const smoothPlusDm = smoothedAverage(plusDmArr, period);
  const smoothMinusDm = smoothedAverage(minusDmArr, period);
  const n = smoothTr.length;
  const plusDi = smoothTr[n - 1] ? 100 * smoothPlusDm[n - 1] / smoothTr[n - 1] : 25;
  const minusDi = smoothTr[n - 1] ? 100 * smoothMinusDm[n - 1] / smoothTr[n - 1] : 25;
  const diSum = plusDi + minusDi || 1;
  const dx = 100 * Math.abs(plusDi - minusDi) / diSum;
  // Simple ADX as SMA of last period DX values
  const dxArr = [];
  for (let i = 0; i < smoothTr.length; i++) {
    const pdi = smoothTr[i] ? 100 * smoothPlusDm[i] / smoothTr[i] : 25;
    const mdi = smoothTr[i] ? 100 * smoothMinusDm[i] / smoothTr[i] : 25;
    const s = pdi + mdi || 1;
    dxArr.push(100 * Math.abs(pdi - mdi) / s);
  }
  const adxVal = average(dxArr.slice(-period));
  return { adx: adxVal, plusDi, minusDi };
}

function smoothedAverage(arr, period) {
  const result = [];
  let sum = 0;
  for (let i = 0; i < arr.length; i++) {
    if (i < period) {
      sum += arr[i];
      result.push(sum / (i + 1));
    } else {
      sum = sum - sum / period + arr[i];
      result.push(sum / period);
    }
  }
  return result;
}

// =========================================================================
// NEW: Stochastic RSI
// =========================================================================

export function stochRsi(values, rsiPeriod = 14, kPeriod = 3, dPeriod = 3) {
  const rsiArr = rsiSeries(values, rsiPeriod);
  const n = rsiArr.length;
  if (n < rsiPeriod + kPeriod) return { k: 50, d: 50, signal: "neutral" };
  const stochArr = [];
  for (let i = 0; i < n; i++) {
    if (i < rsiPeriod) {
      stochArr.push(50);
      continue;
    }
    const slice = rsiArr.slice(Math.max(0, i - rsiPeriod + 1), i + 1);
    const rsiMin = Math.min(...slice);
    const rsiMax = Math.max(...slice);
    const range = rsiMax - rsiMin || 1;
    stochArr.push(((rsiArr[i] - rsiMin) / range) * 100);
  }
  const kArr = sma(stochArr, kPeriod);
  const dArr = sma(kArr, dPeriod);
  const k = last(kArr, 50);
  const d = last(dArr, 50);
  return {
    k,
    d,
    signal: k < 20 ? "oversold" : k > 80 ? "overbought" : "neutral",
  };
}

function sma(arr, period) {
  const result = [];
  for (let i = 0; i < arr.length; i++) {
    if (i < period - 1) {
      result.push(arr[i]);
    } else {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += arr[j];
      result.push(sum / period);
    }
  }
  return result;
}

// =========================================================================
// NEW: OBV (On-Balance Volume)
// =========================================================================

export function obv(candles, maPeriod = 20) {
  const obvArr = [0];
  for (let i = 1; i < candles.length; i++) {
    const dir = Math.sign(candles[i].close - candles[i - 1].close);
    obvArr.push(obvArr[i - 1] + dir * candles[i].volume);
  }
  const obvMa = sma(obvArr, maPeriod);
  const current = last(obvArr, 0);
  const maVal = last(obvMa, 0);
  return {
    value: current,
    ma: maVal,
    trend: current > maVal ? "bullish" : current < maVal ? "bearish" : "neutral",
  };
}

// =========================================================================
// NEW: Divergence detection
// =========================================================================

export function detectDivergence(prices, indicator, lookback = 20) {
  if (prices.length < lookback + 5 || indicator.length < lookback + 5) return "none";
  const p = prices.slice(-lookback);
  const ind = indicator.slice(-lookback);
  const validCount = p.filter((value, index) => Number.isFinite(value) && Number.isFinite(ind[index])).length;
  if (validCount < lookback * 0.75) return "none";
  const lows = swingPoints(p, "low");
  const highs = swingPoints(p, "high");
  if (lows.length >= 2) {
    const first = lows[lows.length - 2];
    const second = lows[lows.length - 1];
    if (p[second] < p[first] && ind[second] > ind[first]) return "bullish";
  }
  if (highs.length >= 2) {
    const first = highs[highs.length - 2];
    const second = highs[highs.length - 1];
    if (p[second] > p[first] && ind[second] < ind[first]) return "bearish";
  }
  return "none";
}

function swingPoints(values, mode, left = 2, right = 2) {
  const points = [];
  for (let index = left; index < values.length - right; index += 1) {
    const value = values[index];
    const window = values.slice(index - left, index + right + 1);
    if (!Number.isFinite(value) || window.some((item) => !Number.isFinite(item))) continue;
    if (mode === "low" && value === Math.min(...window) && value < values[index - 1] && value < values[index + 1]) {
      points.push(index);
    }
    if (mode === "high" && value === Math.max(...window) && value > values[index - 1] && value > values[index + 1]) {
      points.push(index);
    }
  }
  return points;
}

// =========================================================================
// NEW: Candle pattern detection
// =========================================================================

export function detectCandlePatterns(candles) {
  const patterns = [];
  if (candles.length < 3) return { patterns, bias: "neutral" };
  const curr = candles[candles.length - 1];
  const prev = candles[candles.length - 2];
  const body = Math.abs(curr.close - curr.open);
  const range = (curr.high - curr.low) || 1e-10;
  const upperWick = curr.high - Math.max(curr.close, curr.open);
  const lowerWick = Math.min(curr.close, curr.open) - curr.low;
  const prevBody = Math.abs(prev.close - prev.open);
  if (body / range < 0.1) patterns.push("doji");
  if (lowerWick > body * 2.5 && upperWick < body * 0.5 && curr.close > curr.open) patterns.push("hammer");
  if (upperWick > body * 2.5 && lowerWick < body * 0.5 && curr.close < curr.open) patterns.push("shooting_star");
  if (lowerWick > range * 0.6 && body < range * 0.25 && curr.close > curr.open) patterns.push("pin_bar_bullish");
  if (upperWick > range * 0.6 && body < range * 0.25 && curr.close < curr.open) patterns.push("pin_bar_bearish");
  if (prev.close < prev.open && curr.close > curr.open && curr.open <= prev.close && curr.close >= prev.open && body > prevBody) patterns.push("bullish_engulfing");
  if (prev.close > prev.open && curr.close < curr.open && curr.open >= prev.close && curr.close <= prev.open && body > prevBody) patterns.push("bearish_engulfing");
  // Morning star
  if (candles.length >= 3) {
    const c3 = candles[candles.length - 3];
    const c2 = candles[candles.length - 2];
    const c1 = candles[candles.length - 1];
    if (c3.close < c3.open && Math.abs(c2.close - c2.open) < Math.abs(c3.close - c3.open) * 0.3 && c1.close > c1.open && c1.close > (c3.open + c3.close) / 2)
      patterns.push("morning_star");
    if (c3.close > c3.open && Math.abs(c2.close - c2.open) < Math.abs(c3.close - c3.open) * 0.3 && c1.close < c1.open && c1.close < (c3.open + c3.close) / 2)
      patterns.push("evening_star");
  }
  const bullish = new Set(["hammer", "pin_bar_bullish", "bullish_engulfing", "morning_star"]);
  const bearish = new Set(["shooting_star", "pin_bar_bearish", "bearish_engulfing", "evening_star"]);
  const bullCount = patterns.filter((p) => bullish.has(p)).length;
  const bearCount = patterns.filter((p) => bearish.has(p)).length;
  return {
    patterns,
    bias: bullCount > bearCount ? "bullish" : bearCount > bullCount ? "bearish" : "neutral",
  };
}

// =========================================================================
// NEW: Fibonacci retracements
// =========================================================================

export function fibonacci(candles, lookback = 50) {
  const current = last(candles)?.close ?? 0;
  const atrValue = atr(candles, 14) || current * 0.01;
  const pivots = confirmedVolumePivots(candles, atrValue);
  const lows = pivots.filter((pivot) => pivot.type === "low");
  const highs = pivots.filter((pivot) => pivot.type === "high");
  if (!lows.length || !highs.length) return { levels: {}, zones: [], nearest: null };
  const low = lows[lows.length - 1];
  const high = highs[highs.length - 1];
  const start = low.index < high.index ? low.price : high.price;
  const end = low.index < high.index ? high.price : low.price;
  const diff = end - start;
  const zones = [0.382, 0.5, 0.618].map((ratio) => {
    const center = end - diff * ratio;
    return { label: `${(ratio * 100).toFixed(1)}%`, center, lower: center - atrValue * 0.5, upper: center + atrValue * 0.5 };
  });
  const levels = Object.fromEntries(zones.map((zone) => [zone.label, zone.center]));
  const nearest = zones.reduce((best, zone) => Math.abs(zone.center - current) < Math.abs(best.center - current) ? zone : best);
  return { levels, zones, nearest: { label: nearest.label, price: nearest.center, lower: nearest.lower, upper: nearest.upper } };
}

// =========================================================================
// NEW: Market regime classification
// =========================================================================

export function classifyRegime(indicators) {
  const { adxVal, volatility, breakoutUp, breakoutDown, bbWidth } = indicators;
  if (breakoutUp || breakoutDown) return "breakout";
  if ((adxVal ?? 20) >= 25 && (volatility ?? 0) < 0.04) return "trending";
  if ((volatility ?? 0) >= 0.04 || (bbWidth ?? 0) >= 0.08) return "volatile";
  return "ranging";
}

// =========================================================================
// NEW: Trend strength composite score
// =========================================================================

export function trendStrengthScore(indicators) {
  let score = 0;
  const adxVal = indicators.adxVal ?? 20;
  score += Math.min(30, adxVal * 0.75);
  const maTrend = indicators.maTrend ?? "neutral";
  if (maTrend.includes("strong")) score += 25;
  else if (maTrend.includes("weak")) score += 12;
  const structure = indicators.structure ?? "range";
  if (structure === "higher_highs_higher_lows" || structure === "lower_highs_lower_lows") score += 20;
  else score += 5;
  const hist = indicators.macdHistogram ?? 0;
  const histPrev = indicators.macdHistogramPrev ?? 0;
  if (Math.abs(hist) > Math.abs(histPrev) && hist * histPrev > 0) score += 15;
  else if (hist * histPrev > 0) score += 8;
  const volRatio = indicators.volumeRatio ?? 1;
  if (volRatio >= 1.5) score += 10;
  else if (volRatio >= 1.0) score += 5;
  const total = Math.min(100, Math.round(score));
  return {
    score: total,
    label: total >= 75 ? "forte" : total >= 45 ? "moderada" : "fraca",
  };
}

// =========================================================================
// Comprehensive calculateIndicators (upgraded)
// =========================================================================

export function calculateIndicators(candles) {
  const closes = candles.map((item) => item.close);
  const ema9 = ema(closes, 9);
  const ema21 = ema(closes, 21);
  const ema50 = ema(closes, 50);
  const ema200 = ema(closes, 200);
  const levels = supportResistance(candles);
  const current = last(candles);
  const currentAtr = atr(candles, 14);
  const volumeAverage = average(candles.slice(-20).map((item) => item.volume));
  const currentVwap = vwap(candles);
  const macdData = macd(closes);
  const rsiVal = rsi(closes);
  const rsiPrev = closes.length > 15 ? rsi(closes.slice(0, -1)) : 50;
  const rsiSeriesArr = rsiSeries(closes);
  const adxData = adx(candles);
  const stochRsiData = stochRsi(closes);
  const obvData = obv(candles);
  const candlePatterns = detectCandlePatterns(candles);
  const fibData = fibonacci(candles);
  const structure = analyzeStructure(candles);

  // MA trend classification
  const currentClose = current?.close ?? 0;
  const ema9Last = last(ema9, currentClose);
  const ema21Last = last(ema21, currentClose);
  const ema50Last = last(ema50, currentClose);
  const ema200Last = last(ema200, currentClose);
  let maTrend = "neutral";
  if (currentClose > ema9Last && ema9Last > ema21Last && ema21Last > ema50Last && currentClose > ema200Last) maTrend = "bullish_strong";
  else if (currentClose > ema9Last && currentClose > ema21Last && currentClose > ema200Last) maTrend = "bullish_weak";
  else if (currentClose < ema9Last && ema9Last < ema21Last && ema21Last < ema50Last && currentClose < ema200Last) maTrend = "bearish_strong";
  else if (currentClose < ema9Last && currentClose < ema21Last && currentClose < ema200Last) maTrend = "bearish_weak";

  const bbMiddle = last(sma(closes, 20), currentClose);
  const bbStd = stdDev(closes.slice(-20));
  const bbUpper = bbMiddle + bbStd * 2;
  const bbLower = bbMiddle - bbStd * 2;
  const bbWidth = bbMiddle ? (bbUpper - bbLower) / bbMiddle : 0;

  const volatility = current?.close ? currentAtr / current.close : 0;
  const volumeRatio = volumeAverage ? current.volume / volumeAverage : 1;

  // Breakout detection
  const prev20High = candles.length > 21 ? Math.max(...candles.slice(-21, -1).map((c) => c.high)) : levels.resistance;
  const prev20Low = candles.length > 21 ? Math.min(...candles.slice(-21, -1).map((c) => c.low)) : levels.support;
  const breakoutUp = levels.resistanceZone ? currentClose > levels.resistanceZone.breakPrice : currentClose > prev20High;
  const breakoutDown = levels.supportZone ? currentClose < levels.supportZone.breakPrice : currentClose < prev20Low;

  // Divergences
  const rsiDivergence = detectDivergence(closes, rsiSeriesArr);
  const macdDivergence = detectDivergence(closes, macdData.histogramSeries);

  // Regime
  const regime = classifyRegime({ adxVal: adxData.adx, volatility, breakoutUp, breakoutDown, bbWidth });

  // Trend strength
  const strength = trendStrengthScore({
    adxVal: adxData.adx,
    maTrend,
    structure,
    macdHistogram: macdData.histogram,
    macdHistogramPrev: macdData.histogramPrev,
    volumeRatio,
  });

  // Momentum state
  const macdAccel = Math.abs(macdData.histogram) > Math.abs(macdData.histogramPrev) * 1.05;
  const rsiAccel = Math.abs(rsiVal - 50) > Math.abs(rsiPrev - 50);
  const momentum = macdAccel && rsiAccel ? "acelerando" : !macdAccel && !rsiAccel ? "desacelerando" : "estável";

  return {
    ema9,
    ema21,
    ema50,
    ema200,
    rsi: rsiVal,
    rsiPrev,
    rsiSeries: rsiSeriesArr,
    macd: macdData,
    atr: currentAtr,
    volatility,
    volumeAverage,
    volumeRatio,
    vwap: currentVwap,
    support: levels.support,
    resistance: levels.resistance,
    supportZone: levels.supportZone,
    resistanceZone: levels.resistanceZone,
    demandZones: levels.demandZones,
    supplyZones: levels.supplyZones,
    poc: levels.poc,
    pocShort: levels.pocShort,
    pocBias: levels.pocBias,
    pocShortBias: levels.pocShortBias,
    confirmedPivots: levels.pivots,
    structure,
    distanceEma21: current?.close && last(ema21) ? (current.close - last(ema21)) / last(ema21) : 0,
    distanceVwap: current?.close && currentVwap ? (current.close - currentVwap) / currentVwap : 0,
    // New indicators
    adx: adxData.adx,
    plusDi: adxData.plusDi,
    minusDi: adxData.minusDi,
    stochRsi: stochRsiData,
    obv: obvData,
    candlePatterns,
    fibonacci: fibData,
    rsiDivergence,
    macdDivergence,
    maTrend,
    bbUpper,
    bbMiddle,
    bbLower,
    bbWidth,
    breakoutUp,
    breakoutDown,
    regime,
    trendStrength: strength,
    momentum,
  };
}

export function average(values) {
  return values.length ? values.reduce((sum, value) => sum + Number(value), 0) / values.length : 0;
}

function rollingAverage(values, period) {
  return values.map((_, index) => average(values.slice(Math.max(0, index - period + 1), index + 1)));
}

export function last(values, fallback = undefined) {
  return values.length ? values[values.length - 1] : fallback;
}

function stdDev(values) {
  if (values.length < 2) return 0;
  const avg = average(values);
  const squaredDiffs = values.map((v) => (v - avg) ** 2);
  return Math.sqrt(average(squaredDiffs));
}

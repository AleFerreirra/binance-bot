const REST_BASE = "https://api.binance.com/api/v3";
const WS_BASE = "wss://stream.binance.com:9443/ws";
const FX_BASE = "https://api.frankfurter.app";

export function parseKline(raw) {
  return {
    time: Math.floor(raw[0] / 1000),
    open: Number(raw[1]),
    high: Number(raw[2]),
    low: Number(raw[3]),
    close: Number(raw[4]),
    volume: Number(raw[5]),
    closeTime: raw[6],
  };
}

export async function fetchInitialCandles(symbol, interval, limit = 300) {
  const url = new URL(`${REST_BASE}/klines`);
  url.searchParams.set("symbol", symbol);
  url.searchParams.set("interval", interval);
  url.searchParams.set("limit", String(limit));
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Erro na API pública da Binance: ${response.status}`);
  }
  const rows = await response.json();
  return closedCandles(dedupeCandles(rows.map(parseKline)));
}

export async function fetchLocalCandles(symbol, interval, limit = 300) {
  const response = await fetch(`/api/candles?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&limit=${limit}`);
  if (!response.ok) {
    throw new Error(`Erro na API local de candles: ${response.status}`);
  }
  const payload = await response.json();
  if (!Array.isArray(payload.candles)) {
    throw new Error(payload.error || "A API local não retornou candles");
  }
  return closedCandles(dedupeCandles(payload.candles));
}

export async function fetchBackendSignal(symbol, timeframe) {
  const response = await fetch(`/api/signal?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`);
  if (!response.ok) {
    throw new Error(`Erro na API local de análise: ${response.status}`);
  }
  return response.json();
}

export async function fetchForexQuotes(pairs, FetchImpl = fetch) {
  const grouped = new Map();
  for (const pair of pairs) {
    const [base, quote] = pair.split("/");
    if (!base || !quote) continue;
    grouped.set(base, [...(grouped.get(base) ?? []), quote]);
  }

  const quotes = [];
  for (const [base, quoteSymbols] of grouped.entries()) {
    const url = new URL(`${FX_BASE}/latest`);
    url.searchParams.set("from", base);
    url.searchParams.set("to", quoteSymbols.join(","));
    const response = await FetchImpl(url);
    if (!response.ok) {
      throw new Error(`Erro na API pública de câmbio: ${response.status}`);
    }
    const payload = await response.json();
    for (const quote of quoteSymbols) {
      const rate = Number(payload.rates?.[quote]);
      if (Number.isFinite(rate)) {
        quotes.push({
          symbol: `${base}/${quote}`,
          price: rate,
          timestamp: payload.date ? new Date(`${payload.date}T00:00:00Z`).toISOString() : new Date().toISOString(),
        });
      }
    }
  }
  return quotes;
}

export function createKlineSocket({ symbol, interval, onCandle, onStatus, WebSocketImpl = WebSocket }) {
  let socket;
  let reconnectTimer;
  let closedByUser = false;
  let retry = 0;
  const stream = `${symbol.toLowerCase()}@kline_${interval}`;

  const connect = () => {
    onStatus?.("connecting");
    socket = new WebSocketImpl(`${WS_BASE}/${stream}`);
    socket.onopen = () => {
      retry = 0;
      onStatus?.("connected");
    };
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      const kline = payload.k;
      onCandle?.({
        time: Math.floor(kline.t / 1000),
        open: Number(kline.o),
        high: Number(kline.h),
        low: Number(kline.l),
        close: Number(kline.c),
        volume: Number(kline.v),
        closeTime: kline.T,
        closed: Boolean(kline.x),
      });
    };
    socket.onerror = () => onStatus?.("error");
    socket.onclose = () => {
      if (closedByUser) return;
      onStatus?.("disconnected");
      const delay = Math.min(30000, 1000 * 2 ** retry);
      retry += 1;
      reconnectTimer = setTimeout(connect, delay);
    };
  };

  connect();
  return {
    close() {
      closedByUser = true;
      clearTimeout(reconnectTimer);
      socket?.close();
    },
  };
}

export function mergeCandle(candles, candle) {
  const next = candles.slice();
  const last = next[next.length - 1];
  if (last?.time === candle.time) {
    next[next.length - 1] = { ...last, ...candle };
    return next;
  }
  if (last && candle.time < last.time) {
    return dedupeCandles(next.concat(candle));
  }
  next.push(candle);
  return next.slice(-500);
}

export function dedupeCandles(candles) {
  const map = new Map();
  for (const candle of candles) {
    if (Number.isFinite(candle.close) && candle.time) {
      map.set(candle.time, candle);
    }
  }
  return [...map.values()].sort((a, b) => a.time - b.time);
}

export function closedCandles(candles, now = Date.now()) {
  return candles.filter((candle) => candle.closed !== false && (!candle.closeTime || candle.closeTime <= now));
}

export function makeDemoFeed({ interval, onCandle, onStatus }) {
  let price = 79000;
  let index = 0;
  onStatus?.("connected");
  const ms = intervalToMs(interval);
  const timer = setInterval(() => {
    const open = price;
    const drift = Math.sin(index / 8) * 80 + (Math.random() - 0.45) * 140;
    price = Math.max(100, price + drift);
    const high = Math.max(open, price) + Math.random() * 80;
    const low = Math.min(open, price) - Math.random() * 80;
    onCandle?.({
      time: Math.floor((Date.now() + index * ms) / 1000),
      open,
      high,
      low,
      close: price,
      volume: 700 + Math.random() * 1000,
      closeTime: Date.now(),
      closed: true,
    });
    index += 1;
  }, 1200);
  return { close: () => clearInterval(timer) };
}

export function demoCandles(count = 320) {
  const candles = [];
  let price = 79000;
  const start = Math.floor(Date.now() / 1000) - count * 900;
  for (let index = 0; index < count; index += 1) {
    const open = price;
    price += Math.sin(index / 14) * 45 + (Math.random() - 0.48) * 110;
    const close = Math.max(100, price);
    candles.push({
      time: start + index * 900,
      open,
      high: Math.max(open, close) + 90,
      low: Math.min(open, close) - 90,
      close,
      volume: 900 + Math.sin(index / 5) * 180 + Math.random() * 420,
      closeTime: (start + index * 900) * 1000,
    });
  }
  return candles;
}

export function demoForexQuotes(pairs) {
  const baseRates = {
    "EUR/USD": 1.0850,
    "USD/JPY": 147.25,
    "GBP/USD": 1.2750,
  };
  return pairs.map((symbol, index) => ({
    symbol,
    price: (baseRates[symbol] ?? 1) * (1 + Math.sin(Date.now() / 60000 + index) * 0.002),
    timestamp: new Date().toISOString(),
  }));
}

function intervalToMs(interval) {
  const unit = interval.at(-1);
  const value = Number(interval.slice(0, -1));
  if (unit === "m") return value * 60 * 1000;
  if (unit === "h") return value * 60 * 60 * 1000;
  return 60 * 1000;
}

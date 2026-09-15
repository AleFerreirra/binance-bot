import { calculateIndicators } from "./indicators.js";

const COLORS = {
  ema9: "#f2b84b",
  ema21: "#62a8ff",
  ema50: "#a78bfa",
  ema200: "#e7edf7",
  support: "#20c997",
  resistance: "#ff5c7a",
  entry: "#62a8ff",
  stop: "#ff5c7a",
  target: "#20c997",
};

export function createMarketChart(container, chartApi = window.LightweightCharts) {
  if (!container) {
    throw new Error("Chart container is not available");
  }
  if (!chartApi?.createChart) {
    return createCanvasFallbackChart(container);
  }
  const chart = chartApi.createChart(container, {
    layout: { background: { color: "#111722" }, textColor: "#c9d4e7" },
    grid: { vertLines: { color: "#1d2635" }, horzLines: { color: "#1d2635" } },
    rightPriceScale: { borderColor: "#273348", autoScale: true },
    timeScale: {
      borderColor: "#273348",
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 8,
      barSpacing: 7,
    },
    crosshair: { mode: chartApi.CrosshairMode?.Normal ?? 0 },
    handleScroll: {
      mouseWheel: true,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: true,
    },
    handleScale: {
      axisPressedMouseMove: true,
      mouseWheel: true,
      pinch: true,
    },
  });
  const candles = addSeries(chart, chartApi, "Candlestick", {
    upColor: "#20c997",
    downColor: "#ff5c7a",
    borderVisible: false,
    wickUpColor: "#20c997",
    wickDownColor: "#ff5c7a",
  });
  const volume = addSeries(chart, chartApi, "Histogram", {
    priceFormat: { type: "volume" },
    priceScaleId: "",
    scaleMargins: { top: 0.78, bottom: 0 },
  });
  const emaSeries = {
    ema9: addSeries(chart, chartApi, "Line", { color: COLORS.ema9, lineWidth: 1 }),
    ema21: addSeries(chart, chartApi, "Line", { color: COLORS.ema21, lineWidth: 1 }),
    ema50: addSeries(chart, chartApi, "Line", { color: COLORS.ema50, lineWidth: 1 }),
    ema200: addSeries(chart, chartApi, "Line", { color: COLORS.ema200, lineWidth: 1 }),
  };
  let priceLines = [];
  let lastFirstTime = null;

  const resize = () => {
    const rect = container.getBoundingClientRect();
    chart.applyOptions({ width: rect.width, height: rect.height });
  };
  window.addEventListener("resize", resize);
  resize();

  return {
    chart,
    update(candleData, signal) {
      const indicators = calculateIndicators(candleData);
      candles.setData(candleData.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
      volume.setData(candleData.map((item) => ({
        time: item.time,
        value: item.volume,
        color: item.close >= item.open ? "rgba(32, 201, 151, 0.36)" : "rgba(255, 92, 122, 0.34)",
      })));
      for (const key of Object.keys(emaSeries)) {
        emaSeries[key].setData(indicators[key].map((value, index) => ({ time: candleData[index].time, value })));
      }
      priceLines.forEach((line) => candles.removePriceLine(line));
      priceLines = buildPriceLines(candles, signal);
      const firstTime = candleData[0]?.time ?? null;
      if (firstTime !== lastFirstTime) {
        chart.timeScale().fitContent();
        lastFirstTime = firstTime;
      }
    },
    destroy() {
      window.removeEventListener("resize", resize);
      chart.remove();
    },
  };
}

function addSeries(chart, chartApi, type, options) {
  const legacyName = `add${type}Series`;
  if (typeof chart[legacyName] === "function") {
    return chart[legacyName](options);
  }
  const seriesConstructor = chartApi[`${type}Series`];
  if (typeof chart.addSeries === "function" && seriesConstructor) {
    return chart.addSeries(seriesConstructor, options);
  }
  throw new Error(`A biblioteca de gráficos não suporta a série ${type} nesta versão`);
}

function createCanvasFallbackChart(container) {
  const canvas = document.createElement("canvas");
  canvas.className = "fallback-chart";
  container.replaceChildren(canvas);
  const context = canvas.getContext("2d");
  const viewport = { zoom: 1, offset: 0, dragging: false, dragX: 0 };
  let latestCandles = [];
  let latestSignal = {};
  const resize = () => {
    const rect = container.getBoundingClientRect();
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.max(320, Math.floor(rect.width * scale));
    canvas.height = Math.max(260, Math.floor(rect.height * scale));
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    context.setTransform(scale, 0, 0, scale, 0, 0);
    drawFallback(context, canvas, latestCandles, latestSignal, viewport);
  };
  window.addEventListener("resize", resize);
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const direction = event.deltaY > 0 ? -1 : 1;
    viewport.zoom = clamp(viewport.zoom * (direction > 0 ? 1.18 : 0.85), 1, 12);
    drawFallback(context, canvas, latestCandles, latestSignal, viewport);
  }, { passive: false });
  canvas.addEventListener("mousedown", (event) => {
    viewport.dragging = true;
    viewport.dragX = event.clientX;
    canvas.classList.add("dragging");
  });
  window.addEventListener("mousemove", (event) => {
    if (!viewport.dragging || !latestCandles.length) return;
    const visibleCount = visibleCandleCount(latestCandles, viewport);
    const pxPerCandle = canvas.clientWidth / Math.max(1, visibleCount);
    const delta = Math.round((event.clientX - viewport.dragX) / Math.max(1, pxPerCandle));
    if (delta) {
      viewport.offset = clamp(viewport.offset + delta, 0, Math.max(0, latestCandles.length - visibleCount));
      viewport.dragX = event.clientX;
      drawFallback(context, canvas, latestCandles, latestSignal, viewport);
    }
  });
  window.addEventListener("mouseup", () => {
    viewport.dragging = false;
    canvas.classList.remove("dragging");
  });
  resize();
  return {
    update(candleData, signal) {
      latestCandles = candleData;
      latestSignal = signal;
      viewport.offset = clamp(viewport.offset, 0, Math.max(0, candleData.length - visibleCandleCount(candleData, viewport)));
      drawFallback(context, canvas, candleData, signal, viewport);
    },
    destroy() {
      window.removeEventListener("resize", resize);
      canvas.remove();
    },
  };
}

function drawFallback(context, canvas, candles, signal, viewport = { zoom: 1, offset: 0 }) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#111722";
  context.fillRect(0, 0, width, height);
  const visibleCount = visibleCandleCount(candles, viewport);
  const maxOffset = Math.max(0, candles.length - visibleCount);
  const offset = clamp(viewport.offset, 0, maxOffset);
  const end = candles.length - offset;
  const data = candles.slice(Math.max(0, end - visibleCount), end);
  if (!data.length) return;
  const zoneValues = [
    signal.supportZone?.lower,
    signal.supportZone?.upper,
    signal.resistanceZone?.lower,
    signal.resistanceZone?.upper,
  ];
  const values = data.flatMap((item) => [item.high, item.low, signal.stop, ...(signal.targets ?? []), ...zoneValues]).filter(Number.isFinite);
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const top = 20;
  const bottom = height - 52;
  const xStep = width / data.length;
  const y = (price) => top + ((max - price) / range) * (bottom - top);

  context.strokeStyle = "#273348";
  context.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const yy = top + ((bottom - top) / 4) * i;
    context.beginPath();
    context.moveTo(0, yy);
    context.lineTo(width, yy);
    context.stroke();
  }

  data.forEach((candle, index) => {
    const x = index * xStep + xStep / 2;
    const up = candle.close >= candle.open;
    context.strokeStyle = up ? COLORS.support : COLORS.stop;
    context.fillStyle = context.strokeStyle;
    context.beginPath();
    context.moveTo(x, y(candle.high));
    context.lineTo(x, y(candle.low));
    context.stroke();
    const bodyTop = y(Math.max(candle.open, candle.close));
    const bodyHeight = Math.max(2, Math.abs(y(candle.open) - y(candle.close)));
    context.fillRect(x - Math.max(2, xStep * 0.32), bodyTop, Math.max(3, xStep * 0.64), bodyHeight);
  });

  drawZone(context, width, y, signal.supportZone, COLORS.support, "Zona demanda");
  drawZone(context, width, y, signal.resistanceZone, COLORS.resistance, "Zona supply");
  drawLevel(context, width, y, signal.stop, COLORS.stop, "Stop");
  for (const [index, target] of (signal.targets ?? []).entries()) {
    drawLevel(context, width, y, target, COLORS.target, `Alvo ${index + 1}`);
  }
}

function visibleCandleCount(candles, viewport) {
  return clamp(Math.round(120 / Math.max(1, viewport.zoom)), 20, Math.max(20, candles.length));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function drawLevel(context, width, y, price, color, label) {
  if (!Number.isFinite(price)) return;
  const yy = y(price);
  context.strokeStyle = color;
  context.fillStyle = color;
  context.setLineDash([6, 5]);
  context.beginPath();
  context.moveTo(0, yy);
  context.lineTo(width, yy);
  context.stroke();
  context.setLineDash([]);
  context.fillText(label, 10, yy - 5);
}

function drawZone(context, width, y, zone, color, label) {
  if (!zone || !Number.isFinite(zone.lower) || !Number.isFinite(zone.upper)) return;
  drawLevel(context, width, y, zone.lower, color, `${label} min`);
  drawLevel(context, width, y, zone.upper, color, `${label} max`);
}

export function buildPriceLines(series, signal) {
  const lines = [];
  if (signal.supportZone) {
    lines.push(series.createPriceLine({ price: signal.supportZone.lower, color: COLORS.support, lineWidth: 1, title: "Demanda min" }));
    lines.push(series.createPriceLine({ price: signal.supportZone.upper, color: COLORS.support, lineWidth: 1, title: "Demanda max" }));
  }
  if (signal.resistanceZone) {
    lines.push(series.createPriceLine({ price: signal.resistanceZone.lower, color: COLORS.resistance, lineWidth: 1, title: "Supply min" }));
    lines.push(series.createPriceLine({ price: signal.resistanceZone.upper, color: COLORS.resistance, lineWidth: 1, title: "Supply max" }));
  }
  if (signal.entry) {
    lines.push(series.createPriceLine({ price: signal.entry[0], color: COLORS.entry, lineWidth: 1, title: "Entrada min" }));
    lines.push(series.createPriceLine({ price: signal.entry[1], color: COLORS.entry, lineWidth: 1, title: "Entrada max" }));
  }
  if (Number.isFinite(signal.stop)) {
    lines.push(series.createPriceLine({ price: signal.stop, color: COLORS.stop, lineWidth: 2, title: "Stop" }));
  }
  for (const [index, target] of signal.targets.entries()) {
    if (Number.isFinite(target)) {
      lines.push(series.createPriceLine({ price: target, color: COLORS.target, lineWidth: 1, title: `Alvo ${index + 1}` }));
    }
  }
  return lines;
}

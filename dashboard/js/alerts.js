export function createAlertManager({ element, cooldownMs = 900000 }) {
  const LAST_ALERT_KEY = "binance-market-analyzer:last-alert-at:v1";
  const seen = new Map();
  let memoryLastAlertAt = 0;

  return {
    notify(signal) {
      if (signal.alertMessage) {
        return showAlert(signal.id, signal.alertMessage, signal.alertType);
      }
      if (!["LONG_SETUP", "SHORT_SETUP"].includes(signal.decision)) {
        return false;
      }
      return showAlert(signal.id, `Nova configuração válida: ${signal.symbol} ${signalLabel(signal.decision)} pontuação ${signal.score}/100`, "SIGNAL");
    },
    hasBeenQuiet(hours = 3) {
      const lastAlertAt = readLastAlertAt();
      return !lastAlertAt || Date.now() - lastAlertAt > hours * 60 * 60 * 1000;
    },
  };

  function showAlert(id, message, type) {
    const key = `${type}:${id}:${message}`;
    const now = Date.now();
    const previous = seen.get(key) ?? 0;
    if (now - previous < cooldownMs) {
      return false;
    }
    seen.set(key, now);
    writeLastAlertAt(now);
    element.hidden = false;
    element.textContent = message;
    setTimeout(() => {
      element.hidden = true;
    }, 8500);
    return true;
  }

  function readLastAlertAt() {
    try {
      return Number(globalThis.localStorage?.getItem(LAST_ALERT_KEY) ?? memoryLastAlertAt);
    } catch {
      return memoryLastAlertAt;
    }
  }

  function writeLastAlertAt(value) {
    memoryLastAlertAt = value;
    try {
      globalThis.localStorage?.setItem(LAST_ALERT_KEY, String(value));
    } catch {
      // Storage can be unavailable in private browsing or restricted contexts.
    }
  }
}

function signalLabel(decision) {
  return {
    LONG_SETUP: "COMPRA",
    SHORT_SETUP: "VENDA",
    WAIT: "AGUARDAR",
    INVALIDATED: "INVALIDADO",
  }[decision] ?? decision;
}

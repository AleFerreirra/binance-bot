const HISTORY_KEY = "binance-market-analyzer:history:v1";
const PREFS_KEY = "binance-market-analyzer:prefs:v1";

export function loadHistory() {
  return readJson(HISTORY_KEY, []);
}

export function saveSignal(signal) {
  const history = loadHistory();
  if (history[0]?.id === signal.id) return history;
  const next = [signal, ...history.filter((item) => item.id !== signal.id)].slice(0, 120);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  return next;
}

export function clearHistory() {
  localStorage.removeItem(HISTORY_KEY);
}

export function loadPrefs() {
  return readJson(PREFS_KEY, {});
}

export function savePrefs(prefs) {
  localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
}

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export const MARKET_SESSIONS = Object.freeze([
  { name: "Cripto", region: "Global", timeZone: "UTC", open: "00:00", close: "23:59", alwaysOpen: true },
  { name: "Ásia", region: "Tóquio", timeZone: "Asia/Tokyo", open: "09:00", close: "15:00" },
  { name: "Europa", region: "Londres", timeZone: "Europe/London", open: "08:00", close: "16:30" },
  { name: "EUA", region: "Nova York", timeZone: "America/New_York", open: "09:30", close: "16:00" },
  { name: "Brasil", region: "B3", timeZone: "America/Sao_Paulo", open: "10:00", close: "17:00" },
]);

export function getSessionState(session, now = new Date()) {
  if (session.alwaysOpen) {
    return { open: true, label: "Aberto 24h", localTime: formatSessionTime(now, session.timeZone) };
  }
  const minutes = localMinutes(now, session.timeZone);
  const openMinutes = clockToMinutes(session.open);
  const closeMinutes = clockToMinutes(session.close);
  const open = closeMinutes > openMinutes
    ? minutes >= openMinutes && minutes < closeMinutes
    : minutes >= openMinutes || minutes < closeMinutes;
  return {
    open,
    label: open ? "Aberto" : "Fechado",
    localTime: formatSessionTime(now, session.timeZone),
  };
}

export function getMarketClock(now = new Date()) {
  return MARKET_SESSIONS.map((session) => ({
    ...session,
    ...getSessionState(session, now),
  }));
}

function clockToMinutes(value) {
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

function localMinutes(now, timeZone) {
  const parts = new Intl.DateTimeFormat("pt-BR", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? 0);
  const minute = Number(parts.find((part) => part.type === "minute")?.value ?? 0);
  return hour * 60 + minute;
}

function formatSessionTime(now, timeZone) {
  return new Intl.DateTimeFormat("pt-BR", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(now);
}

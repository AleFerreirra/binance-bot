import logging
import threading
import time
from datetime import datetime
from typing import Dict

from logging_utils import mask_secret


logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, config):
        self.telegram_token = config.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = config.TELEGRAM_CHAT_ID
        self.discord_webhook = getattr(config, "DISCORD_WEBHOOK_URL", "")
        self.generic_webhook = getattr(config, "GENERIC_WEBHOOK_URL", "")
        self._last_sent: Dict[str, float] = {}
        self._signal_cooldown = int(getattr(config, "ALERT_COOLDOWN_SECONDS", 900))
        self._min_interval = {"CRITICAL": 0, "HIGH": 30, "SIGNAL": 0, "INFO": 60}
        self._lock = threading.Lock()

    def _should_send(self, severity: str) -> bool:
        with self._lock:
            now = time.time()
            interval = self._min_interval.get(severity, 60)
            if now - self._last_sent.get(severity, 0) < interval:
                return False
            self._last_sent[severity] = now
            return True

    def _post(self, url: str, payload: dict) -> bool:
        if not url:
            return False
        try:
            import requests
            response = requests.post(url, json=payload, timeout=10)
            if 200 <= response.status_code < 300:
                return True
            logger.warning("[ALERTA] webhook retornou status %s", response.status_code)
        except Exception as exc:
            logger.warning("[ALERTA] falha ao enviar webhook: %s", mask_secret(exc))
        return False

    def _send_telegram(self, text: str) -> bool:
        if not self.telegram_token or not self.telegram_chat_id:
            return False
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        return self._post(url, {"chat_id": self.telegram_chat_id, "text": text, "disable_web_page_preview": True})

    def alert(self, severity: str, title: str, message: str = "") -> None:
        if not self._should_send(severity):
            return
        clean_title = mask_secret(title)
        clean_message = mask_secret(message)
        text = f"[{severity}] {clean_title}\n{clean_message}\n{datetime.utcnow().isoformat()}Z"
        log_level = logging.CRITICAL if severity == "CRITICAL" else logging.WARNING if severity == "HIGH" else logging.INFO
        logger.log(
            log_level,
            "[ALERT] %s %s",
            severity,
            clean_title,
            extra={"alert_message": clean_message},
        )
        self._send_telegram(text)
        self._post(self.discord_webhook, {"content": text})
        self._post(self.generic_webhook, {"severity": severity, "title": clean_title, "message": clean_message})

    def market_signal(self, signal) -> None:
        now = time.time()
        with self._lock:
            last_sent = self._last_sent.get(signal.signal_id, 0)
            if now - last_sent < self._signal_cooldown:
                return
            self._last_sent[signal.signal_id] = now
        data = signal.as_dict()
        trends = data["tendencias"]
        entry = data["regiao_ideal_entrada"] or ["-", "-"]
        text = (
            f"{data['ativo']} - {data['decisao']}\n\n"
            f"Preco: {data['preco_atual']}\n"
            f"Tendencia 4h: {trends.get('4h', '-')}\n"
            f"Tendencia 1h: {trends.get('1h', '-')}\n"
            f"Estrutura 15m: {trends.get('15m', '-')}\n"
            f"Score: {data['score']}/100\n"
            f"Entrada ideal: {entry[0]} a {entry[1]}\n"
            f"Stop tecnico: {data['stop_loss_tecnico'] or '-'}\n"
            f"Alvos: {data['alvo_1'] or '-'} | {data['alvo_2'] or '-'} | {data['alvo_3'] or '-'}\n"
            f"R/R: {data['risco_retorno']}\n\n"
            f"Plano:\n- " + "\n- ".join(data["condicoes_antes_entrada"]) + "\n\n"
            f"Cancelar se:\n- " + "\n- ".join(data["condicoes_cancelam_sinal"]) + "\n\n"
            f"{data['aviso']}"
        )
        self.alert("SIGNAL", f"Sinal {data['decisao']}", text)

    def zone_alert(self, signal) -> None:
        """Dispatch zone alerts (HOT_ZONE, REJECTION, STOP_HUNT, MICRO_BREAKOUT)
        independently of the signal decision. This ensures zone proximity
        and rejection events reach Telegram even when decision is WAIT."""
        if not signal.alert_type:
            return
        now = time.time()
        alert_key = f"zone:{signal.symbol}:{signal.alert_type}:{signal.alert_direction}"
        with self._lock:
            if now - self._last_sent.get(alert_key, 0) < self._signal_cooldown:
                return
            self._last_sent[alert_key] = now
        emoji = {
            "HOT_ZONE": "\U0001f7e1",
            "REJECTION": "\U0001f534",
            "MICRO_BREAKOUT": "\U0001f7e2",
            "STOP_HUNT": "\u26a0\ufe0f",
        }
        text = (
            f"{emoji.get(signal.alert_type, '\U0001f4cd')} {signal.alert_type}\n"
            f"{signal.symbol} — {signal.alert_message}\n"
            f"Preco: {signal.current_price}\n"
            f"Direcao: {signal.alert_direction}\n"
            f"Score: {signal.score}/100"
        )
        self.alert("HIGH", f"Zona {signal.alert_type}", text)

    def trade_opened(self, symbol: str, side: str, quantity: str,
                     entry_price: str, stop_loss: str, take_profit: str,
                     regime: str = "", confidence: float = 0.0) -> None:
        self.alert(
            "TRADE",
            "Trade aberto",
            f"{symbol} {side} quantidade={quantity} entrada={entry_price} stop={stop_loss} alvo={take_profit} regime={regime} confianca={confidence:.0%}",
        )

    def trade_closed(self, symbol: str, exit_price: str, pnl: str) -> None:
        self.alert("TRADE", "Trade fechado", f"{symbol} saida={exit_price} pnl={pnl}")

    def circuit_breaker(self, reason: str) -> None:
        self.alert("CRITICAL", "Circuit breaker acionado", reason)

    def kill_switch(self) -> None:
        self.alert("CRITICAL", "Kill switch ativado", "Bot bloqueado pelo arquivo KILL_SWITCH")

    def incident(self, category: str, message: str, details: str = "") -> None:
        self.alert("CRITICAL", f"Incidente: {category}", f"{message}\n{details}")

    def bot_started(self, balance: str, symbol: str) -> None:
        self.alert("INFO", "Bot iniciado", f"simbolo={symbol} saldo={balance}")

    def bot_stopped(self, reason: str = "") -> None:
        self.alert("HIGH", "Bot parado", reason)

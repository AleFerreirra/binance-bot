import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from analysis_api import start_dashboard_server
from binance_client import BinanceClient
from config import Config
from logging_utils import setup_logging
from messages import pt_reason
from notifications import Notifier
from strategy import MarketAnalyzer, MarketSignal


logger = logging.getLogger(__name__)


def is_production() -> bool:
    return os.getenv("RENDER", "").lower() == "true" or os.getenv("APP_ENV", "").lower() == "production"


class AnalysisBot:
    def __init__(self, config: Config):
        self.config = config
        if not config.validate():
            raise ValueError("invalid configuration")
        setup_logging(config)
        self.dashboard_server = None if is_production() else start_dashboard_server(config, open_browser=True)
        self.notifier = Notifier(config)
        self.client = BinanceClient(config.API_KEY, config.API_SECRET, config)
        self.running = True
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        self.notifier.bot_started("analysis_only", ",".join(config.SYMBOLS))
        logger.info(
            "[INICIO] analisador inicializado em modo read-only",
            extra={"simbolos": config.SYMBOLS, "trading_mode": config.TRADING_MODE},
        )

    def signal_handler(self, sig, frame) -> None:
        logger.info("[PARADA] sinal de encerramento recebido", extra={"sinal": sig})
        self.running = False

    def run(self) -> None:
        logger.info("[INICIO] loop de analise iniciado")
        while self.running:
            try:
                analyses = self.cycle()
                self.write_health("ok", pt_reason("cycle completed"), analyses)
                time.sleep(self.config.CHECK_INTERVAL)
            except KeyboardInterrupt:
                self.running = False
            except Exception as exc:
                logger.exception("[ERRO] ciclo de analise falhou: %s", exc)
                self.write_health("degraded", str(exc), [])
                time.sleep(60)
        self.shutdown(pt_reason("loop stopped"))

    def cycle(self) -> list[dict]:
        results = []
        for symbol in self.config.SYMBOLS:
            signal_result = self.analyze_symbol(symbol)
            payload = signal_result.as_dict()
            results.append(payload)
            logger.info("[ANALISE] sinal gerado", extra=payload)
            self.notifier.market_signal(signal_result)
        return results

    def analyze_symbol(self, symbol: str) -> MarketSignal:
        timeframes = [
            self.config.CONTEXT_TIMEFRAME,
            self.config.CONFIRMATION_TIMEFRAME,
            self.config.SETUP_TIMEFRAME,
            self.config.REFINEMENT_TIMEFRAME,
        ]
        candles = {
            timeframe: self.client.get_klines(symbol, timeframe, self.config.KLINE_LIMIT, closed_only=True)
            for timeframe in dict.fromkeys(timeframes)
        }
        spread = self.client.get_spread_percent(symbol)
        analyzer = MarketAnalyzer(symbol, candles, self.config, spread_percent=spread)
        return analyzer.generate_signal()

    def write_health(self, status: str, message: str, analyses: list[dict]) -> None:
        payload = {
            "status": status,
            "message": message,
            "mode": self.config.TRADING_MODE,
            "symbols": self.config.SYMBOLS,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_analyses": analyses,
        }
        Path(self.config.HEALTH_CHECK_FILE).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def shutdown(self, reason: str) -> None:
        self.write_health("stopped", reason, [])
        self.notifier.bot_stopped(reason)
        if self.dashboard_server:
            self.dashboard_server.shutdown()
            self.dashboard_server.server_close()
        logger.info("[PARADA] analisador parado", extra={"motivo": reason})


if __name__ == "__main__":
    try:
        AnalysisBot(Config()).run()
    except Exception as exc:
        logging.basicConfig(level=logging.ERROR)
        logger.exception("[FATAL] falha ao iniciar analisador: %s", exc)
        sys.exit(1)

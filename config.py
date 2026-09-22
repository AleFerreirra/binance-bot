import logging
import os
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _decimal_env(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


class Config:
    """Central analysis-only configuration."""

    API_KEY = os.getenv("BINANCE_API_KEY", "")
    API_SECRET = os.getenv("BINANCE_API_SECRET", "")
    TRADING_MODE = os.getenv("TRADING_MODE", "analysis_only").lower()
    PAPER_TRADING = os.getenv("PAPER_TRADING", "false").lower() in {"1", "true", "yes"}

    SYMBOL = os.getenv("SYMBOL", "BNBUSDT").upper()
    SYMBOLS = [item.strip().upper() for item in os.getenv("SYMBOLS", SYMBOL).split(",") if item.strip()]
    BASE_ASSET = os.getenv("BASE_ASSET", "BNB").upper()
    QUOTE_ASSET = os.getenv("QUOTE_ASSET", "USDT").upper()
    TIMEFRAME = os.getenv("TIMEFRAME", "5m")
    CONTEXT_TIMEFRAME = os.getenv("CONTEXT_TIMEFRAME", "4h")
    CONFIRMATION_TIMEFRAME = os.getenv("CONFIRMATION_TIMEFRAME", "15m")
    SETUP_TIMEFRAME = os.getenv("SETUP_TIMEFRAME", "5m")
    REFINEMENT_TIMEFRAME = os.getenv("REFINEMENT_TIMEFRAME", "1m")
    CHECK_INTERVAL = _int_env("CHECK_INTERVAL", 180)
    KLINE_LIMIT = _int_env("KLINE_LIMIT", 250)
    COOLDOWN_SECONDS = _int_env("COOLDOWN_SECONDS", 300)
    ALERT_COOLDOWN_SECONDS = _int_env("ALERT_COOLDOWN_SECONDS", 900)

    MAX_POSITION_SIZE = _decimal_env("MAX_POSITION_SIZE", "0.05")
    RISK_PER_TRADE = _decimal_env("RISK_PER_TRADE", "0.005")
    STOP_LOSS_PERCENT = _decimal_env("STOP_LOSS_PERCENT", "0.02")
    TAKE_PROFIT_PERCENT = _decimal_env("TAKE_PROFIT_PERCENT", "0.04")
    MAX_DAILY_TRADES = _int_env("MAX_DAILY_TRADES", 5)
    MAX_DAILY_LOSS = _decimal_env("MAX_DAILY_LOSS", "0.03")
    MAX_WEEKLY_LOSS = _decimal_env("MAX_WEEKLY_LOSS", "0.06")
    MAX_MONTHLY_LOSS = _decimal_env("MAX_MONTHLY_LOSS", "0.10")
    MAX_DRAWDOWN = _decimal_env("MAX_DRAWDOWN", "0.12")
    MAX_TOTAL_EXPOSURE = _decimal_env("MAX_TOTAL_EXPOSURE", "0.20")
    MIN_ORDER_USDT = _decimal_env("MIN_ORDER_USDT", "10")
    MAX_SLIPPAGE_PERCENT = _decimal_env("MAX_SLIPPAGE_PERCENT", "0.005")
    COMMISSION_RATE = _decimal_env("COMMISSION_RATE", "0.001")

    RSI_PERIOD = _int_env("RSI_PERIOD", 14)
    RSI_OVERBOUGHT = Decimal(os.getenv("RSI_OVERBOUGHT", "70"))
    RSI_OVERSOLD = Decimal(os.getenv("RSI_OVERSOLD", "30"))
    BB_PERIOD = _int_env("BB_PERIOD", 20)
    BB_STD = Decimal(os.getenv("BB_STD", "2"))
    MA_SHORT = _int_env("MA_SHORT", 9)
    MA_MEDIUM = _int_env("MA_MEDIUM", 21)
    MA_LONG = _int_env("MA_LONG", 50)
    MA_TREND = _int_env("MA_TREND", 200)
    MACD_FAST = _int_env("MACD_FAST", 12)
    MACD_SLOW = _int_env("MACD_SLOW", 26)
    MACD_SIGNAL = _int_env("MACD_SIGNAL", 9)
    ADX_PERIOD = _int_env("ADX_PERIOD", 14)
    STOCH_RSI_PERIOD = _int_env("STOCH_RSI_PERIOD", 14)
    STOCH_RSI_K = _int_env("STOCH_RSI_K", 3)
    STOCH_RSI_D = _int_env("STOCH_RSI_D", 3)
    OBV_MA_PERIOD = _int_env("OBV_MA_PERIOD", 20)
    FIBONACCI_LOOKBACK = _int_env("FIBONACCI_LOOKBACK", 50)
    CANDLE_PATTERN_LOOKBACK = _int_env("CANDLE_PATTERN_LOOKBACK", 3)

    MIN_CONFIDENCE = Decimal(os.getenv("MIN_CONFIDENCE", "0.60"))
    TRENDING_SCORE_THRESHOLD = _int_env("TRENDING_SCORE_THRESHOLD", 3)
    RANGING_SCORE_THRESHOLD = _int_env("RANGING_SCORE_THRESHOLD", 3)
    VOLATILE_SCORE_THRESHOLD = _int_env("VOLATILE_SCORE_THRESHOLD", 4)
    BREAKOUT_SCORE_THRESHOLD = _int_env("BREAKOUT_SCORE_THRESHOLD", 3)
    MAX_VOLATILITY_FILTER = _decimal_env("MAX_VOLATILITY_FILTER", "0.05")
    MAX_SPREAD_FILTER = _decimal_env("MAX_SPREAD_FILTER", "0.003")
    MIN_VOLUME_RATIO = _decimal_env("MIN_VOLUME_RATIO", "0.50")
    MIN_QUOTE_VOLUME_USDT = _decimal_env("MIN_QUOTE_VOLUME_USDT", "100000")
    MIN_RISK_REWARD = _decimal_env("MIN_RISK_REWARD", "2")

    LOG_FILE = os.getenv("LOG_FILE", "trading_bot.log")
    LOG_MAX_BYTES = _int_env("LOG_MAX_BYTES", 5 * 1024 * 1024)
    LOG_BACKUP_COUNT = _int_env("LOG_BACKUP_COUNT", 5)
    DB_PATH = os.getenv("DB_PATH", "trading_bot.db")
    KILL_SWITCH_FILE = os.getenv("KILL_SWITCH_FILE", "KILL_SWITCH")
    HEALTH_CHECK_FILE = os.getenv("HEALTH_CHECK_FILE", "health_check.json")
    DASHBOARD_PORT = _int_env("DASHBOARD_PORT", 8765)
    BINANCE_PUBLIC_BASE_URL = os.getenv("BINANCE_PUBLIC_BASE_URL", "https://api.binance.com").rstrip("/")

    WATCHLIST_SYMBOLS = [
        item.strip().upper()
        for item in os.getenv(
            "WATCHLIST_SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,ADAUSDT,XRPUSDT,DOGEUSDT,AVAXUSDT"
        ).split(",")
        if item.strip()
    ]

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
    GENERIC_WEBHOOK_URL = os.getenv("GENERIC_WEBHOOK_URL", "")

    MAX_API_RETRIES = _int_env("MAX_API_RETRIES", 5)
    API_RETRY_DELAY = Decimal(os.getenv("API_RETRY_DELAY", "1"))
    API_TIMEOUT = _int_env("API_TIMEOUT", 20)
    API_RATE_LIMIT_WEIGHT = _int_env("API_RATE_LIMIT_WEIGHT", 1200)
    API_RATE_LIMIT_BUFFER = Decimal(os.getenv("API_RATE_LIMIT_BUFFER", "0.80"))

    @classmethod
    def masked_api_key(cls) -> str:
        if not cls.API_KEY:
            return ""
        return f"{cls.API_KEY[:4]}...{cls.API_KEY[-4:]}"

    @classmethod
    def validate_safety(cls) -> None:
        allowed_modes = {"analysis_only", "paper"}
        forbidden_modes = {"live", "real", "trade", "trading", "execution", "orders"}
        if cls.TRADING_MODE in forbidden_modes or cls.TRADING_MODE not in allowed_modes:
            raise ValueError(
                "TRADING_MODE must be analysis_only or paper. Real order execution is blocked."
            )
        if cls.TRADING_MODE == "paper":
            cls.PAPER_TRADING = True

    @classmethod
    def validate(cls) -> bool:
        errors = []
        try:
            cls.validate_safety()
        except ValueError as exc:
            errors.append(str(exc))
        if not (Decimal("0") < cls.MAX_POSITION_SIZE <= Decimal("0.10")):
            errors.append("MAX_POSITION_SIZE must be > 0 and <= 0.10")
        if not (Decimal("0") < cls.RISK_PER_TRADE <= Decimal("0.02")):
            errors.append("RISK_PER_TRADE must be > 0 and <= 0.02")
        if cls.TAKE_PROFIT_PERCENT <= cls.STOP_LOSS_PERCENT:
            errors.append("TAKE_PROFIT_PERCENT must be greater than STOP_LOSS_PERCENT")
        if cls.KLINE_LIMIT < max(cls.MA_TREND + 5, 220):
            errors.append("KLINE_LIMIT must include enough closed candles for MA200")
        if not (Decimal("0") < cls.MIN_CONFIDENCE <= Decimal("1")):
            errors.append("MIN_CONFIDENCE must be between 0 and 1")
        if cls.API_RATE_LIMIT_BUFFER <= 0 or cls.API_RATE_LIMIT_BUFFER > 1:
            errors.append("API_RATE_LIMIT_BUFFER must be in (0, 1]")
        if cls.MIN_RISK_REWARD < Decimal("2"):
            errors.append("MIN_RISK_REWARD must be at least 2")

        for error in errors:
            logger.error("[CONFIG] %s", error)
        return not errors

import logging
import socket
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable, Dict

import pandas as pd
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SymbolFilters:
    min_qty: Decimal
    max_qty: Decimal
    step_size: Decimal
    tick_size: Decimal
    min_notional: Decimal


class BinanceClient:
    """Read-only Binance public market-data client wrapper."""

    WEIGHTS = {
        "ping": 1,
        "time": 1,
        "ticker": 2,
        "book_ticker": 2,
        "klines": 2,
        "exchange_info": 10,
    }

    def __init__(self, api_key: str, api_secret: str, config=None):
        self.config = config
        requests_params = {"timeout": getattr(config, "API_TIMEOUT", 20)}
        self.client = Client(api_key or None, api_secret or None, requests_params=requests_params)
        self.public_base_url = str(getattr(config, "BINANCE_PUBLIC_BASE_URL", "https://api.binance.com")).rstrip("/")
        self.use_public_rest = self.public_base_url != "https://api.binance.com"
        self.session = requests.Session()
        self.max_retries = int(getattr(config, "MAX_API_RETRIES", 5))
        self.retry_delay = Decimal(str(getattr(config, "API_RETRY_DELAY", "1")))
        self.weight_limit = int(getattr(config, "API_RATE_LIMIT_WEIGHT", 1200))
        self.weight_buffer = Decimal(str(getattr(config, "API_RATE_LIMIT_BUFFER", "0.80")))
        self._weight_window_start = time.monotonic()
        self._used_weight = 0
        self._filters: Dict[str, SymbolFilters] = {}
        self.time_offset_ms = 0
        if self.use_public_rest:
            logger.info("[BINANCE] usando REST publico alternativo", extra={"base_url": self.public_base_url})
        else:
            self.sync_time()
            self.test_connection()

    def _consume_weight(self, weight: int) -> None:
        now = time.monotonic()
        if now - self._weight_window_start >= 60:
            self._weight_window_start = now
            self._used_weight = 0
        allowed = int(Decimal(self.weight_limit) * self.weight_buffer)
        if self._used_weight + weight > allowed:
            sleep_for = max(1, 60 - int(now - self._weight_window_start))
            logger.warning("[BINANCE] peso de requisicoes perto do limite; aguardando %ss", sleep_for)
            time.sleep(sleep_for)
            self._weight_window_start = time.monotonic()
            self._used_weight = 0
        self._used_weight += weight

    def _call(self, name: str, func: Callable, *args, **kwargs) -> Any:
        weight = self.WEIGHTS.get(name, 1)
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            self._consume_weight(weight)
            try:
                return func(*args, **kwargs)
            except BinanceAPIException as exc:
                last_error = exc
                if exc.code in {-1003, -1015, -1021}:
                    if exc.code == -1021:
                        self.sync_time()
                    delay = float(self.retry_delay * (Decimal(2) ** Decimal(attempt - 1)))
                    logger.warning("[BINANCE] erro temporario da API %s em %s; nova tentativa em %.1fs", exc.code, name, delay)
                    time.sleep(delay)
                    continue
                raise
            except (BinanceRequestException, RequestException, Timeout, RequestsConnectionError, socket.timeout) as exc:
                last_error = exc
                delay = float(self.retry_delay * (Decimal(2) ** Decimal(attempt - 1)))
                logger.warning("[BINANCE] erro de rede em %s; nova tentativa em %.1fs: %s", name, delay, exc)
                time.sleep(delay)
        raise RuntimeError(f"chamada Binance falhou apos todas as tentativas: {name}: {last_error}")

    def _public_get(self, path: str, **params) -> Any:
        url = f"{self.public_base_url}{path}"

        def request():
            response = self.session.get(url, params=params, timeout=int(getattr(self.config, "API_TIMEOUT", 20)))
            response.raise_for_status()
            return response.json() if response.content else {}

        return self._call("klines", request)

    def sync_time(self) -> None:
        server = self._call("time", self.client.get_server_time)
        local_ms = int(time.time() * 1000)
        self.time_offset_ms = int(server["serverTime"]) - local_ms
        self.client.timestamp_offset = self.time_offset_ms
        logger.info("[BINANCE] horario sincronizado", extra={"offset_ms": self.time_offset_ms})

    def test_connection(self) -> None:
        self._call("ping", self.client.ping)
        logger.info("[BINANCE] conexao publica ok")

    def get_symbol_filters(self, symbol: str) -> SymbolFilters:
        if symbol in self._filters:
            return self._filters[symbol]
        info = self._call("exchange_info", self.client.get_symbol_info, symbol)
        if not info:
            raise ValueError(f"simbolo nao encontrado: {symbol}")
        filters = {item["filterType"]: item for item in info["filters"]}
        lot = filters["LOT_SIZE"]
        price = filters["PRICE_FILTER"]
        notional = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {"minNotional": "10"}
        parsed = SymbolFilters(
            min_qty=Decimal(lot["minQty"]),
            max_qty=Decimal(lot["maxQty"]),
            step_size=Decimal(lot["stepSize"]),
            tick_size=Decimal(price["tickSize"]),
            min_notional=Decimal(notional.get("minNotional", "10")),
        )
        self._filters[symbol] = parsed
        return parsed

    @staticmethod
    def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
        if increment == 0:
            return value
        units = (value / increment).to_integral_value(rounding=ROUND_DOWN)
        return (units * increment).normalize()

    def adjust_price(self, symbol: str, price: Decimal) -> Decimal:
        filters = self.get_symbol_filters(symbol)
        adjusted = self._quantize_down(Decimal(price), filters.tick_size)
        if adjusted <= 0:
            raise ValueError(f"preco ajustado invalido para {symbol}: {adjusted}")
        return adjusted

    def adjust_quantity(self, symbol: str, quantity: Decimal) -> Decimal:
        filters = self.get_symbol_filters(symbol)
        adjusted = self._quantize_down(Decimal(quantity), filters.step_size)
        if adjusted < filters.min_qty:
            raise ValueError(f"quantidade {adjusted} abaixo do minimo minQty {filters.min_qty}")
        if adjusted > filters.max_qty:
            adjusted = self._quantize_down(filters.max_qty, filters.step_size)
        return adjusted

    def validate_notional(self, symbol: str, quantity: Decimal, price: Decimal) -> None:
        filters = self.get_symbol_filters(symbol)
        notional = Decimal(quantity) * Decimal(price)
        if quantity < filters.min_qty:
            raise ValueError(f"quantidade {quantity} abaixo do minimo minQty {filters.min_qty}")
        if notional < filters.min_notional:
            raise ValueError(f"valor nocional {notional} abaixo do minimo minNotional {filters.min_notional}")

    def get_current_price(self, symbol: str) -> Decimal:
        if self.use_public_rest:
            ticker = self._public_get("/api/v3/ticker/price", symbol=symbol)
            return Decimal(ticker["price"])
        ticker = self._call("ticker", self.client.get_symbol_ticker, symbol=symbol)
        return Decimal(ticker["price"])

    def get_book_ticker(self, symbol: str) -> Dict[str, Decimal]:
        if self.use_public_rest:
            book = self._public_get("/api/v3/ticker/bookTicker", symbol=symbol)
            return {
                "bid": Decimal(book["bidPrice"]),
                "ask": Decimal(book["askPrice"]),
                "bid_qty": Decimal(book["bidQty"]),
                "ask_qty": Decimal(book["askQty"]),
            }
        book = self._call("book_ticker", self.client.get_orderbook_ticker, symbol=symbol)
        return {
            "bid": Decimal(book["bidPrice"]),
            "ask": Decimal(book["askPrice"]),
            "bid_qty": Decimal(book["bidQty"]),
            "ask_qty": Decimal(book["askQty"]),
        }

    def get_spread_percent(self, symbol: str) -> Decimal:
        book = self.get_book_ticker(symbol)
        mid = (book["bid"] + book["ask"]) / Decimal("2")
        return (book["ask"] - book["bid"]) / mid if mid > 0 else Decimal("1")

    def get_klines(self, symbol: str, interval: str, limit: int = 250,
                   closed_only: bool = True) -> pd.DataFrame:
        if self.use_public_rest:
            klines = self._public_get("/api/v3/klines", symbol=symbol, interval=interval, limit=limit)
        else:
            klines = self._call("klines", self.client.get_klines, symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
        ])
        numeric = ["open", "high", "low", "close", "volume", "quote_asset_volume"]
        for col in numeric:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])
        if closed_only and not df.empty:
            now = pd.Timestamp.now(tz="UTC")
            df = df[df["close_time"] <= now]
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        if not df["timestamp"].is_monotonic_increasing:
            df = df.sort_values("timestamp")
        return df.reset_index(drop=True)

    @staticmethod
    def extract_fills(order: Dict) -> Dict[str, Decimal]:
        fills = order.get("fills", []) or []
        qty = Decimal("0")
        notional = Decimal("0")
        commission = Decimal("0")
        for fill in fills:
            fill_qty = Decimal(fill["qty"])
            fill_price = Decimal(fill["price"])
            qty += fill_qty
            notional += fill_qty * fill_price
            commission += Decimal(fill.get("commission", "0"))
        avg_price = notional / qty if qty > 0 else Decimal(order.get("price") or "0")
        return {"quantity": qty, "avg_price": avg_price, "commission": commission}

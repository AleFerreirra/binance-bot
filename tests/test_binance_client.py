from decimal import Decimal

import pytest

from binance_client import BinanceClient, SymbolFilters


def client_without_init():
    client = BinanceClient.__new__(BinanceClient)
    client._filters = {
        "BNBUSDT": SymbolFilters(
            min_qty=Decimal("0.001"),
            max_qty=Decimal("1000"),
            step_size=Decimal("0.001"),
            tick_size=Decimal("0.01"),
            min_notional=Decimal("10"),
        )
    }
    return client


def test_adjust_price_and_quantity_round_down():
    client = client_without_init()
    assert client.adjust_price("BNBUSDT", Decimal("321.239")) == Decimal("321.23")
    assert client.adjust_quantity("BNBUSDT", Decimal("1.2349")) == Decimal("1.234")


def test_validate_order_rejects_min_notional():
    client = client_without_init()
    with pytest.raises(ValueError):
        client.validate_notional("BNBUSDT", Decimal("0.01"), Decimal("100"))


def test_extract_fills_computes_weighted_average():
    order = {
        "fills": [
            {"qty": "1", "price": "100", "commission": "0.1"},
            {"qty": "2", "price": "110", "commission": "0.2"},
        ]
    }
    fills = BinanceClient.extract_fills(order)
    assert fills["quantity"] == Decimal("3")
    assert fills["avg_price"] == Decimal("106.6666666666666666666666667")
    assert fills["commission"] == Decimal("0.3")


def test_client_exposes_no_real_execution_methods():
    forbidden = {
        "place_market_order",
        "place_oco_sell",
        "cancel_open_orders",
        "close_position_market",
        "get_open_orders",
        "get_order",
        "get_my_trades",
        "get_account",
        "get_account_balance",
    }
    assert forbidden.isdisjoint(set(dir(BinanceClient)))


def test_public_client_accepts_missing_api_keys(monkeypatch):
    class FakeClient:
        timestamp_offset = 0

        def __init__(self, api_key, api_secret, requests_params=None):
            self.api_key = api_key
            self.api_secret = api_secret

        def get_server_time(self):
            return {"serverTime": 1}

        def ping(self):
            return {}

    monkeypatch.setattr("binance_client.Client", FakeClient)
    client = BinanceClient("", "", config=None)
    assert client.client.api_key is None
    assert client.client.api_secret is None


def test_public_rest_mode_skips_ping_and_uses_configured_base_url(monkeypatch):
    class FakeClient:
        timestamp_offset = 0

        def __init__(self, api_key, api_secret, requests_params=None):
            pass

        def get_server_time(self):
            raise AssertionError("sync_time should not run in public REST mode")

        def ping(self):
            raise AssertionError("ping should not run in public REST mode")

    class Config:
        API_TIMEOUT = 20
        MAX_API_RETRIES = 1
        API_RETRY_DELAY = Decimal("0")
        API_RATE_LIMIT_WEIGHT = 1200
        API_RATE_LIMIT_BUFFER = Decimal("0.80")
        BINANCE_PUBLIC_BASE_URL = "https://data-api.binance.vision"

    monkeypatch.setattr("binance_client.Client", FakeClient)
    client = BinanceClient("", "", Config)
    assert client.use_public_rest is True
    assert client.public_base_url == "https://data-api.binance.vision"

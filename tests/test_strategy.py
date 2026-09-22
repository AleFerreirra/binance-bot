from decimal import Decimal
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from strategy import AnalysisDecision, MarketAnalyzer, TimeframeAnalysis, Trend
from indicators import TechnicalIndicators


class DummyConfig:
    RSI_PERIOD = 14
    BB_PERIOD = 20
    BB_STD = Decimal("2")
    MA_SHORT = 9
    MA_MEDIUM = 21
    MA_LONG = 50
    MA_TREND = 200
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    MAX_VOLATILITY_FILTER = Decimal("0.50")
    MAX_SPREAD_FILTER = Decimal("0.003")
    MIN_VOLUME_RATIO = Decimal("0.10")
    MIN_QUOTE_VOLUME_USDT = Decimal("1")
    COMMISSION_RATE = Decimal("0.001")
    KLINE_LIMIT = 250
    SYMBOL = "BNBUSDT"
    CONTEXT_TIMEFRAME = "4h"
    CONFIRMATION_TIMEFRAME = "1h"
    SETUP_TIMEFRAME = "15m"
    REFINEMENT_TIMEFRAME = "5m"
    STOP_LOSS_PERCENT = Decimal("0.02")
    TAKE_PROFIT_PERCENT = Decimal("0.04")
    RISK_PER_TRADE = Decimal("0.005")
    MAX_POSITION_SIZE = Decimal("0.05")
    MIN_ORDER_USDT = Decimal("10")
    TRENDING_SCORE_THRESHOLD = 3
    RANGING_SCORE_THRESHOLD = 3
    VOLATILE_SCORE_THRESHOLD = 4
    BREAKOUT_SCORE_THRESHOLD = 3
    MIN_RISK_REWARD = Decimal("2")


def candles(rows=260):
    ts = pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC")
    close = pd.Series(range(100, 100 + rows), dtype=float)
    return pd.DataFrame({
        "timestamp": ts,
        "open": close - 0.5,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": [1000.0] * rows,
        "quote_asset_volume": [100000.0] * rows,
        "close_time": ts + pd.Timedelta(minutes=15),
    })


def price_action_dataframe():
    data = candles()
    high_idx = data.index[-30]
    low_idx = data.index[-18]
    data.loc[high_idx, ["open", "high", "low", "close", "volume"]] = [330.0, 360.0, 325.0, 340.0, 5000.0]
    data.loc[high_idx + 1, ["open", "high", "low", "close"]] = [340.0, 345.0, 320.0, 330.0]
    data.loc[low_idx, ["open", "high", "low", "close", "volume"]] = [310.0, 315.0, 280.0, 300.0, 6000.0]
    data.loc[low_idx + 1, ["open", "high", "low", "close"]] = [300.0, 320.0, 295.0, 310.0]
    return data


def test_rejects_insufficient_closed_candles():
    with pytest.raises(ValueError):
        MarketAnalyzer("BNBUSDT", {"4h": candles(50), "1h": candles(50), "15m": candles(50), "5m": candles(50)}, DummyConfig)


def test_spread_filter_blocks_signal():
    analyzer = MarketAnalyzer(
        "BNBUSDT",
        {"4h": candles(), "1h": candles(), "15m": candles(), "5m": candles()},
        DummyConfig,
        spread_percent=Decimal("0.01"),
    )
    signal = analyzer.generate_signal()
    assert signal.decision == AnalysisDecision.WAIT
    assert signal.reasons == ["spread elevado"]


def test_signal_uses_allowed_decisions_only():
    analyzer = MarketAnalyzer(
        "BNBUSDT",
        {"4h": candles(), "1h": candles(), "15m": candles(), "5m": candles()},
        DummyConfig,
        spread_percent=Decimal("0.001"),
    )
    assert analyzer.generate_signal().decision in set(AnalysisDecision)


def test_rsi_does_not_flatten_strong_uptrend_to_neutral():
    result = TechnicalIndicators(candles(), DummyConfig).calculate_all()
    assert result["rsi"] > 95


def test_pin_bar_requires_matching_candle_direction():
    data = candles()
    data.loc[data.index[-1], ["open", "high", "low", "close"]] = [120.0, 121.0, 100.0, 119.0]
    result = TechnicalIndicators(data, DummyConfig).calculate_all()
    assert "pin_bar_bullish" not in result["candle_patterns"]


def test_price_action_zones_use_confirmed_volume_pivots():
    data = price_action_dataframe()
    result = TechnicalIndicators(data, DummyConfig).calculate_all()
    assert result["supply_zones"]
    assert result["demand_zones"]
    assert result["nearest_supply_zone"]["lower"] < result["nearest_supply_zone"]["upper"]
    assert result["nearest_demand_zone"]["lower"] < result["nearest_demand_zone"]["upper"]
    assert result["poc_bias"] in {"altista", "baixista", "neutro"}
    assert "poc_short" in result


def test_breakout_uses_zone_break_price():
    result = TechnicalIndicators(price_action_dataframe(), DummyConfig).calculate_all()
    demand_break = result["nearest_demand_zone"]["break_price"]
    supply_break = result["nearest_supply_zone"]["break_price"]
    current = float(price_action_dataframe()["close"].iloc[-1])
    assert result["breakout_down"] == (current < demand_break)
    assert result["breakout_up"] == (current > supply_break)


def test_demand_rejection_rule_accepts_reversal_conditions():
    analyzer = MarketAnalyzer(
        "BNBUSDT",
        {"4h": candles(), "1h": candles(), "15m": candles(), "5m": candles()},
        DummyConfig,
        spread_percent=Decimal("0.001"),
    )
    zone = {"lower": Decimal("99"), "upper": Decimal("101"), "break_price": Decimal("97")}
    candle = pd.Series({"open": 100, "high": 101.5, "low": 98, "close": 100.5, "volume": 900})
    indicators = {"volume_sma": 1000, "rsi": 31, "rsi_prev": 28}
    assert analyzer._is_demand_rejection(candle, indicators, zone)


def test_signal_serializes_operational_alert_fields():
    analyzer = MarketAnalyzer(
        "BNBUSDT",
        {"4h": candles(), "1h": candles(), "15m": candles(), "5m": candles()},
        DummyConfig,
        spread_percent=Decimal("0.001"),
    )
    payload = analyzer.generate_signal().as_dict()
    assert "tipo_alerta" in payload
    assert "mensagem_alerta" in payload
    assert "direcao_alerta" in payload


def test_directional_targets_are_daytrade_r_multiples():
    analyzer = MarketAnalyzer(
        "BNBUSDT",
        {"4h": candles(), "1h": candles(), "15m": candles(), "5m": candles()},
        DummyConfig,
        spread_percent=Decimal("0.001"),
    )
    signal = analyzer._build_directional_signal(
        AnalysisDecision.SHORT_SETUP,
        Decimal("350"),
        "2026-01-01T00:00:00+00:00",
        {"4h": "bearish", "1h": "bearish", "15m": "bearish", "5m": "bearish"},
        85,
        ["teste"],
    )
    entry = sum(signal.ideal_entry_region) / Decimal("2")
    risk = signal.stop_loss - entry
    assert (entry - signal.target_1).quantize(Decimal("0.0001")) == risk.quantize(Decimal("0.0001"))
    assert (entry - signal.target_2).quantize(Decimal("0.0001")) == (risk * Decimal("1.5")).quantize(Decimal("0.0001"))
    assert (entry - signal.target_3).quantize(Decimal("0.0001")) == (risk * Decimal("2")).quantize(Decimal("0.0001"))
    assert signal.risk_reward == Decimal("2.00")


def test_backend_blocks_signal_outside_executable_entry_zone():
    analyzer = MarketAnalyzer(
        "BNBUSDT",
        {"4h": candles(), "1h": candles(), "15m": candles(), "5m": candles()},
        DummyConfig,
        spread_percent=Decimal("0.001"),
    )
    signal = analyzer._build_directional_signal(
        AnalysisDecision.LONG_SETUP,
        Decimal("350"),
        "2026-01-01T00:00:00+00:00",
        {"4h": "bullish", "1h": "bullish", "15m": "bullish", "5m": "bullish"},
        95,
        ["teste"],
    )
    blocked = analyzer._enforce_executable_entry(
        signal,
        Decimal("1"),
        {"atr": Decimal("1")},
        None,
    )
    assert blocked.decision == AnalysisDecision.WAIT
    assert blocked.score <= 59
    assert "fora da zona executavel" in blocked.reasons[0]


def test_backend_disallows_long_when_5m_trend_is_bearish():
    analyzer = MarketAnalyzer(
        "BNBUSDT",
        {"4h": candles(), "1h": candles(), "15m": candles(), "5m": candles()},
        DummyConfig,
        spread_percent=Decimal("0.001"),
    )
    current = analyzer.analyses["5m"]
    analyzer.analyses["5m"] = TimeframeAnalysis(
        timeframe=current.timeframe,
        trend=Trend.BEARISH,
        structure=current.structure,
        indicators=current.indicators,
    )
    assert not analyzer._trend_following_allowed(Trend.BULLISH)


def test_time_stop_flags_position_after_four_hours_without_target():
    opened = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    now = opened + timedelta(hours=4, minutes=1)
    result = MarketAnalyzer.verificar_time_stop(opened, now, target_1_hit=False)
    assert result["close"]
    assert result["reason"] == "TIME_STOP_4H_SEM_ALVO_1"

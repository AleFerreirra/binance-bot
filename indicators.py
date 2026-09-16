import logging
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


class TechnicalIndicators:
    def __init__(self, df: pd.DataFrame, config=None):
        self.df = df.copy()
        self.config = config
        self.indicators: Dict[str, float | str] = {}
        self.rsi_period = config.RSI_PERIOD if config else 14
        self.bb_period = config.BB_PERIOD if config else 20
        self.bb_std = float(config.BB_STD) if config else 2.0
        self.ma_short = config.MA_SHORT if config else 9
        self.ma_medium = config.MA_MEDIUM if config else 21
        self.ma_long = config.MA_LONG if config else 50
        self.ma_trend = config.MA_TREND if config else 200
        self.macd_fast = config.MACD_FAST if config else 12
        self.macd_slow = config.MACD_SLOW if config else 26
        self.macd_signal_period = config.MACD_SIGNAL if config else 9
        self.adx_period = getattr(config, "ADX_PERIOD", 14) if config else 14
        self.stoch_rsi_period = getattr(config, "STOCH_RSI_PERIOD", 14) if config else 14
        self.stoch_rsi_k = getattr(config, "STOCH_RSI_K", 3) if config else 3
        self.stoch_rsi_d = getattr(config, "STOCH_RSI_D", 3) if config else 3
        self.obv_ma_period = getattr(config, "OBV_MA_PERIOD", 20) if config else 20
        self.fib_lookback = getattr(config, "FIBONACCI_LOOKBACK", 50) if config else 50
        self.candle_lookback = getattr(config, "CANDLE_PATTERN_LOOKBACK", 3) if config else 3

    def calculate_all(self) -> Dict:
        self.calculate_rsi()
        self.calculate_bollinger_bands()
        self.calculate_moving_averages()
        self.calculate_macd()
        self.calculate_stochastic()
        self.calculate_atr()
        self.calculate_volume_profile()
        self.calculate_vwap()
        self.calculate_support_resistance()
        self.calculate_structure()
        self.calculate_adx()
        self.calculate_stochastic_rsi()
        self.calculate_obv()
        self.calculate_divergences()
        self.calculate_candle_patterns()
        self.calculate_fibonacci()
        self.calculate_trend_strength()
        self.calculate_momentum_state()
        self.classify_market_regime()
        return self.indicators

    def _safe_last(self, series: pd.Series, default: float) -> float:
        value = series.iloc[-1] if len(series) else np.nan
        return float(value) if pd.notna(value) and np.isfinite(value) else default

    # =========================================================================
    # Core indicators (preserved from original)
    # =========================================================================

    def calculate_rsi(self) -> None:
        delta = self.df["close"].diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1 / self.rsi_period, adjust=False, min_periods=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / self.rsi_period, adjust=False, min_periods=self.rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.mask((loss == 0) & (gain > 0), 100)
        rsi = rsi.mask((gain == 0) & (loss > 0), 0)
        self.indicators["rsi"] = self._safe_last(rsi, 50.0)
        self.indicators["rsi_prev"] = float(rsi.iloc[-2]) if len(rsi) > 1 and pd.notna(rsi.iloc[-2]) else 50.0
        self.indicators["rsi_series"] = rsi.tolist()

    def calculate_bollinger_bands(self) -> None:
        close = self.df["close"]
        middle = close.rolling(window=self.bb_period).mean()
        std = close.rolling(window=self.bb_period).std()
        upper = middle + (std * self.bb_std)
        lower = middle - (std * self.bb_std)
        current = float(close.iloc[-1])
        self.indicators["bb_upper"] = self._safe_last(upper, current * 1.05)
        self.indicators["bb_middle"] = self._safe_last(middle, current)
        self.indicators["bb_lower"] = self._safe_last(lower, current * 0.95)
        width = self.indicators["bb_upper"] - self.indicators["bb_lower"]
        middle_value = self.indicators["bb_middle"]
        self.indicators["bb_width"] = float(width / middle_value) if middle_value else 0.0
        self.indicators["bb_position"] = float((current - self.indicators["bb_lower"]) / width * 100) if width > 0 else 50.0

    def calculate_moving_averages(self) -> None:
        current = float(self.df["close"].iloc[-1])
        for period in sorted({self.ma_short, self.ma_medium, self.ma_long, self.ma_trend}):
            ema = self.df["close"].ewm(span=period, adjust=False).mean()
            value = self._safe_last(ema, current)
            self.indicators[f"ema_{period}"] = value
            self.indicators[f"ma_{period}"] = value
            self.indicators[f"distance_ema_{period}"] = (current - value) / value if value else 0.0
        short = self.indicators[f"ema_{self.ma_short}"]
        medium = self.indicators[f"ema_{self.ma_medium}"]
        long = self.indicators[f"ema_{self.ma_long}"]
        trend = self.indicators[f"ema_{self.ma_trend}"]
        if current > short > medium > long and current > trend:
            self.indicators["ma_trend"] = "bullish_strong"
        elif current > short and current > medium and current > trend:
            self.indicators["ma_trend"] = "bullish_weak"
        elif current < short < medium < long and current < trend:
            self.indicators["ma_trend"] = "bearish_strong"
        elif current < short and current < medium and current < trend:
            self.indicators["ma_trend"] = "bearish_weak"
        else:
            self.indicators["ma_trend"] = "neutral"

    def calculate_macd(self) -> None:
        close = self.df["close"]
        ema_fast = close.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.macd_slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=self.macd_signal_period, adjust=False).mean()
        hist = macd - signal
        self.indicators["macd"] = self._safe_last(macd, 0.0)
        self.indicators["macd_signal"] = self._safe_last(signal, 0.0)
        self.indicators["macd_hist"] = self._safe_last(hist, 0.0)
        self.indicators["macd_hist_prev"] = float(hist.iloc[-2]) if len(hist) > 1 and pd.notna(hist.iloc[-2]) else 0.0
        self.indicators["macd_series"] = macd.tolist()
        self.indicators["macd_signal_series"] = signal.tolist()
        self.indicators["macd_hist_series"] = hist.tolist()
        prev_macd = float(macd.iloc[-2]) if len(macd) > 1 and pd.notna(macd.iloc[-2]) else 0.0
        prev_signal = float(signal.iloc[-2]) if len(signal) > 1 and pd.notna(signal.iloc[-2]) else 0.0
        if self.indicators["macd"] > self.indicators["macd_signal"]:
            self.indicators["macd_signal_type"] = "bullish_cross" if prev_macd <= prev_signal else "bullish"
        elif self.indicators["macd"] < self.indicators["macd_signal"]:
            self.indicators["macd_signal_type"] = "bearish_cross" if prev_macd >= prev_signal else "bearish"
        else:
            self.indicators["macd_signal_type"] = "neutral"

    def calculate_stochastic(self) -> None:
        low_min = self.df["low"].rolling(window=14).min()
        high_max = self.df["high"].rolling(window=14).max()
        spread = (high_max - low_min).replace(0, np.nan)
        k = 100 * ((self.df["close"] - low_min) / spread)
        d = k.rolling(window=3).mean()
        self.indicators["stoch_k"] = self._safe_last(k, 50.0)
        self.indicators["stoch_d"] = self._safe_last(d, 50.0)
        if self.indicators["stoch_k"] < 20 and self.indicators["stoch_d"] < 20:
            self.indicators["stoch_signal"] = "oversold"
        elif self.indicators["stoch_k"] > 80 and self.indicators["stoch_d"] > 80:
            self.indicators["stoch_signal"] = "overbought"
        else:
            self.indicators["stoch_signal"] = "neutral"

    def calculate_atr(self) -> None:
        high_low = self.df["high"] - self.df["low"]
        high_close = (self.df["high"] - self.df["close"].shift()).abs()
        low_close = (self.df["low"] - self.df["close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        self.indicators["atr"] = self._safe_last(atr, 0.0)
        close = float(self.df["close"].iloc[-1])
        self.indicators["volatility"] = float(self.indicators["atr"] / close) if close else 0.0

    def calculate_volume_profile(self) -> None:
        volume_sma = self.df["volume"].rolling(window=20).mean()
        self.indicators["volume_sma"] = self._safe_last(volume_sma, 1.0)
        current_volume = float(self.df["volume"].iloc[-1])
        self.indicators["volume_ratio"] = current_volume / self.indicators["volume_sma"] if self.indicators["volume_sma"] > 0 else 1.0
        self.indicators["quote_volume"] = float(self.df.get("quote_asset_volume", self.df["close"] * self.df["volume"]).iloc[-1])

    def calculate_vwap(self) -> None:
        typical = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
        volume = self.df["volume"].replace(0, np.nan)
        rolling_notional = (typical * volume).rolling(window=50, min_periods=1).sum()
        rolling_volume = volume.rolling(window=50, min_periods=1).sum()
        vwap = rolling_notional / rolling_volume
        current = float(self.df["close"].iloc[-1])
        value = self._safe_last(vwap, current)
        self.indicators["vwap"] = value
        self.indicators["distance_vwap"] = (current - value) / value if value else 0.0

    def calculate_support_resistance(self) -> None:
        """Build price action zones from confirmed volume-backed swing points."""
        atr = float(self.indicators.get("atr", 0)) or float(self.df["close"].iloc[-1]) * 0.01
        volume_ma = self.df["volume"].rolling(window=20, min_periods=1).mean()
        current = float(self.df["close"].iloc[-1])
        poc = self._point_of_control()
        poc_short = self._point_of_control(window=24)
        bias = "altista" if current > poc else "baixista" if current < poc else "neutro"
        short_bias = "altista" if current > poc_short else "baixista" if current < poc_short else "neutro"
        pivots = self._confirmed_volume_pivots(volume_ma, atr)
        supply = self._zones_from_pivots(pivots, "high", atr, current, poc_short)
        demand = self._zones_from_pivots(pivots, "low", atr, current, poc_short)
        nearest_supply = self._nearest_zone(supply, current, above=True)
        nearest_demand = self._nearest_zone(demand, current, above=False)

        self.indicators["poc"] = poc
        self.indicators["poc_short"] = poc_short
        self.indicators["poc_bias"] = bias
        self.indicators["poc_short_bias"] = short_bias
        self.indicators["confirmed_pivots"] = pivots
        self.indicators["supply_zones"] = supply
        self.indicators["demand_zones"] = demand
        self.indicators["nearest_supply_zone"] = nearest_supply
        self.indicators["nearest_demand_zone"] = nearest_demand
        self.indicators["resistance_zone"] = nearest_supply
        self.indicators["support_zone"] = nearest_demand
        self.indicators["resistance_r1"] = nearest_supply["center"] if nearest_supply else current + atr
        self.indicators["support_s1"] = nearest_demand["center"] if nearest_demand else current - atr
        self.indicators["resistance_r2"] = nearest_supply["upper"] if nearest_supply else current + atr * 1.5
        self.indicators["support_s2"] = nearest_demand["lower"] if nearest_demand else current - atr * 1.5
        self.indicators["pivot"] = poc
        self.indicators["recent_high"] = nearest_supply["upper"] if nearest_supply else current + atr
        self.indicators["recent_low"] = nearest_demand["lower"] if nearest_demand else current - atr

    def _confirmed_volume_pivots(self, volume_ma: pd.Series, atr: float, lookback: int = 5) -> List[Dict]:
        pivots: List[Dict] = []
        for idx in range(lookback, len(self.df) - 1):
            row = self.df.iloc[idx]
            nxt = self.df.iloc[idx + 1]
            prev = self.df.iloc[idx - lookback:idx]
            volume_spike = float(row["volume"]) > float(volume_ma.iloc[idx])
            if not volume_spike:
                continue
            high = float(row["high"])
            low = float(row["low"])
            if high > float(prev["high"].max()) and float(nxt["close"]) < high:
                pivots.append(self._pivot_payload("high", idx, high, row, atr, volume_ma))
            if low < float(prev["low"].min()) and float(nxt["close"]) > low:
                pivots.append(self._pivot_payload("low", idx, low, row, atr, volume_ma))
        return pivots[-30:]

    def _pivot_payload(self, kind: str, idx: int, price: float, row: pd.Series, atr: float, volume_ma: pd.Series) -> Dict:
        return {
            "type": kind,
            "index": int(idx),
            "time": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
            "price": price,
            "volume": float(row["volume"]),
            "volume_ratio": float(row["volume"]) / max(float(volume_ma.iloc[idx]), 1e-9),
            "atr": atr,
        }

    def _zones_from_pivots(self, pivots: List[Dict], kind: str, atr: float, current: float, poc: float) -> List[Dict]:
        zones = []
        for pivot in [item for item in pivots if item["type"] == kind]:
            center = float(pivot["price"])
            lower = center - atr * 0.5
            upper = center + atr * 0.5
            if kind == "high":
                broken = current > upper + atr
                valid_by_poc = current < poc
                zone_type = "supply"
            else:
                broken = current < lower - atr
                valid_by_poc = current > poc
                zone_type = "demand"
            if broken:
                continue
            zones.append({
                "type": zone_type,
                "center": center,
                "lower": lower,
                "upper": upper,
                "break_price": upper + atr * 0.5 if kind == "high" else lower - atr * 0.5,
                "volume_ratio": pivot["volume_ratio"],
                "valid_by_poc": valid_by_poc,
                "time": pivot["time"],
            })
        return sorted(zones, key=lambda item: (not item["valid_by_poc"], abs(item["center"] - current)))[:5]

    def _nearest_zone(self, zones: List[Dict], current: float, above: bool) -> Dict | None:
        directional = [z for z in zones if z["center"] >= current] if above else [z for z in zones if z["center"] <= current]
        candidates = directional or zones
        return min(candidates, key=lambda item: abs(item["center"] - current)) if candidates else None

    def _point_of_control(self, bins: int = 48, window: int = 96) -> float:
        recent = self.df.tail(window)
        prices = ((recent["high"] + recent["low"] + recent["close"]) / 3).astype(float)
        volumes = recent["volume"].astype(float)
        low = float(prices.min())
        high = float(prices.max())
        if high <= low:
            return float(prices.iloc[-1])
        edges = np.linspace(low, high, bins + 1)
        bucket = np.clip(np.digitize(prices, edges) - 1, 0, bins - 1)
        totals = np.zeros(bins)
        for idx, volume in zip(bucket, volumes):
            totals[int(idx)] += float(volume)
        poc_idx = int(np.argmax(totals))
        return float((edges[poc_idx] + edges[poc_idx + 1]) / 2)

    def calculate_structure(self) -> None:
        recent = self.df.tail(12)
        first = recent.head(6)
        second = recent.tail(6)
        higher_high = float(second["high"].max()) > float(first["high"].max())
        higher_low = float(second["low"].min()) > float(first["low"].min())
        lower_high = float(second["high"].max()) < float(first["high"].max())
        lower_low = float(second["low"].min()) < float(first["low"].min())
        if higher_high and higher_low:
            structure = "higher_highs_higher_lows"
        elif lower_high and lower_low:
            structure = "lower_highs_lower_lows"
        else:
            structure = "range"
        current = float(self.df["close"].iloc[-1])
        high = float(self.df["high"].iloc[-1])
        low = float(self.df["low"].iloc[-1])
        supply_zone = self.indicators.get("nearest_supply_zone")
        demand_zone = self.indicators.get("nearest_demand_zone")
        previous_high = float(self.df["high"].iloc[-21:-1].max()) if len(self.df) > 21 else float(recent["high"].max())
        previous_low = float(self.df["low"].iloc[-21:-1].min()) if len(self.df) > 21 else float(recent["low"].min())
        supply_break = float(supply_zone["break_price"]) if supply_zone else previous_high
        demand_break = float(demand_zone["break_price"]) if demand_zone else previous_low
        supply_edge = float(supply_zone["upper"]) if supply_zone else previous_high
        demand_edge = float(demand_zone["lower"]) if demand_zone else previous_low
        self.indicators["structure"] = structure
        self.indicators["breakout_up"] = current > supply_break
        self.indicators["breakout_down"] = current < demand_break
        self.indicators["false_breakout_up"] = bool(high > supply_edge and current <= supply_edge)
        self.indicators["false_breakout_down"] = bool(low < demand_edge and current >= demand_edge)

    # =========================================================================
    # New professional-grade indicators
    # =========================================================================

    def calculate_adx(self) -> None:
        """Average Directional Index — measures trend strength (0-100)."""
        period = self.adx_period
        high = self.df["high"]
        low = self.df["low"]
        close = self.df["close"]
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        # When +DM > -DM, set -DM to 0 and vice versa
        mask = plus_dm > minus_dm
        minus_dm = minus_dm.where(~mask, 0)
        plus_dm = plus_dm.where(mask, 0)
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr_smooth = tr.rolling(window=period).mean()
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr_smooth.replace(0, np.nan))
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr_smooth.replace(0, np.nan))
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        adx = dx.rolling(window=period).mean()
        self.indicators["adx"] = self._safe_last(adx, 20.0)
        self.indicators["plus_di"] = self._safe_last(plus_di, 25.0)
        self.indicators["minus_di"] = self._safe_last(minus_di, 25.0)
        if self.indicators["adx"] < 20:
            self.indicators["adx_interpretation"] = "sem_tendencia"
        elif self.indicators["adx"] < 40:
            self.indicators["adx_interpretation"] = "tendencia_moderada"
        elif self.indicators["adx"] < 60:
            self.indicators["adx_interpretation"] = "tendencia_forte"
        else:
            self.indicators["adx_interpretation"] = "tendencia_extrema"

    def calculate_stochastic_rsi(self) -> None:
        """Stochastic RSI for momentum confluence."""
        delta = self.df["close"].diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1 / self.stoch_rsi_period, adjust=False, min_periods=self.stoch_rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / self.stoch_rsi_period, adjust=False, min_periods=self.stoch_rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_values = 100 - (100 / (1 + rs))
        rsi_values = rsi_values.mask((loss == 0) & (gain > 0), 100)
        rsi_values = rsi_values.mask((gain == 0) & (loss > 0), 0)
        rsi_min = rsi_values.rolling(window=self.stoch_rsi_period).min()
        rsi_max = rsi_values.rolling(window=self.stoch_rsi_period).max()
        rsi_range = (rsi_max - rsi_min).replace(0, np.nan)
        stoch_rsi = ((rsi_values - rsi_min) / rsi_range) * 100
        stoch_rsi_k = stoch_rsi.rolling(window=self.stoch_rsi_k).mean()
        stoch_rsi_d = stoch_rsi_k.rolling(window=self.stoch_rsi_d).mean()
        self.indicators["stoch_rsi_k"] = self._safe_last(stoch_rsi_k, 50.0)
        self.indicators["stoch_rsi_d"] = self._safe_last(stoch_rsi_d, 50.0)
        if self.indicators["stoch_rsi_k"] < 20:
            self.indicators["stoch_rsi_signal"] = "oversold"
        elif self.indicators["stoch_rsi_k"] > 80:
            self.indicators["stoch_rsi_signal"] = "overbought"
        else:
            self.indicators["stoch_rsi_signal"] = "neutral"

    def calculate_obv(self) -> None:
        """On-Balance Volume — confirms price moves with volume pressure."""
        close = self.df["close"]
        volume = self.df["volume"]
        direction = np.sign(close.diff().fillna(0))
        obv = (volume * direction).cumsum()
        obv_ma = obv.rolling(window=self.obv_ma_period).mean()
        self.indicators["obv"] = self._safe_last(obv, 0.0)
        self.indicators["obv_ma"] = self._safe_last(obv_ma, 0.0)
        if self.indicators["obv"] > self.indicators["obv_ma"]:
            self.indicators["obv_trend"] = "bullish"
        elif self.indicators["obv"] < self.indicators["obv_ma"]:
            self.indicators["obv_trend"] = "bearish"
        else:
            self.indicators["obv_trend"] = "neutral"

    def calculate_divergences(self) -> None:
        """Detect RSI and MACD divergences against price."""
        self.indicators["rsi_divergence"] = "none"
        self.indicators["macd_divergence"] = "none"
        if len(self.df) < 30:
            return
        close = self.df["close"].values
        # RSI divergence
        delta = pd.Series(close).diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1 / self.rsi_period, adjust=False, min_periods=self.rsi_period).mean()
        loss_s = (-delta.where(delta < 0, 0)).ewm(alpha=1 / self.rsi_period, adjust=False, min_periods=self.rsi_period).mean()
        rs = gain / loss_s.replace(0, np.nan)
        rsi_values = 100 - (100 / (1 + rs))
        rsi_values = rsi_values.mask((loss_s == 0) & (gain > 0), 100)
        rsi_values = rsi_values.mask((gain == 0) & (loss_s > 0), 0)
        rsi_arr = rsi_values.values
        self.indicators["rsi_divergence"] = self._find_divergence(close, rsi_arr, lookback=20)
        # MACD divergence
        macd_hist = self.indicators.get("macd_hist_series")
        if macd_hist and len(macd_hist) >= 30:
            hist_arr = np.array(macd_hist, dtype=float)
            self.indicators["macd_divergence"] = self._find_divergence(close, hist_arr, lookback=20)

    def _find_divergence(self, price: np.ndarray, indicator: np.ndarray, lookback: int = 20) -> str:
        """Compare last two swing lows/highs of price vs indicator."""
        if len(price) < lookback + 5:
            return "none"
        p = price[-lookback:]
        ind = indicator[-lookback:]
        valid = np.isfinite(p) & np.isfinite(ind)
        if valid.sum() < lookback * 0.75:
            return "none"
        p = np.where(valid, p, np.nan)
        ind = np.where(valid, ind, np.nan)
        lows = self._swing_points(p, mode="low")
        highs = self._swing_points(p, mode="high")
        if len(lows) >= 2:
            first, second = lows[-2], lows[-1]
            if p[second] < p[first] and ind[second] > ind[first]:
                return "bullish"
        if len(highs) >= 2:
            first, second = highs[-2], highs[-1]
            if p[second] > p[first] and ind[second] < ind[first]:
                return "bearish"
        return "none"

    def _swing_points(self, values: np.ndarray, mode: str, left: int = 2, right: int = 2) -> List[int]:
        points: List[int] = []
        for idx in range(left, len(values) - right):
            value = values[idx]
            if not np.isfinite(value):
                continue
            window = values[idx - left:idx + right + 1]
            if np.isnan(window).any():
                continue
            if mode == "low" and value == np.min(window) and value < values[idx - 1] and value < values[idx + 1]:
                points.append(idx)
            elif mode == "high" and value == np.max(window) and value > values[idx - 1] and value > values[idx + 1]:
                points.append(idx)
        return points

    def calculate_candle_patterns(self) -> None:
        """Detect key candlestick patterns in recent candles."""
        patterns: List[str] = []
        if len(self.df) < 3:
            self.indicators["candle_patterns"] = patterns
            self.indicators["candle_pattern_bias"] = "neutral"
            return
        curr = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        body = abs(float(curr["close"] - curr["open"]))
        range_ = float(curr["high"] - curr["low"]) or 1e-10
        upper_wick = float(curr["high"]) - max(float(curr["close"]), float(curr["open"]))
        lower_wick = min(float(curr["close"]), float(curr["open"])) - float(curr["low"])
        # Doji
        if body / range_ < 0.1:
            patterns.append("doji")
        # Hammer (bullish)
        if lower_wick > body * 2.5 and upper_wick < body * 0.5 and float(curr["close"]) > float(curr["open"]):
            patterns.append("hammer")
        # Inverted Hammer / Shooting Star (bearish)
        if upper_wick > body * 2.5 and lower_wick < body * 0.5 and float(curr["close"]) < float(curr["open"]):
            patterns.append("shooting_star")
        # Pin Bar Bullish
        if lower_wick > range_ * 0.6 and body < range_ * 0.25 and float(curr["close"]) > float(curr["open"]):
            patterns.append("pin_bar_bullish")
        # Pin Bar Bearish
        if upper_wick > range_ * 0.6 and body < range_ * 0.25 and float(curr["close"]) < float(curr["open"]):
            patterns.append("pin_bar_bearish")
        # Bullish Engulfing
        prev_body = abs(float(prev["close"] - prev["open"]))
        if (float(prev["close"]) < float(prev["open"])  # prev bearish
                and float(curr["close"]) > float(curr["open"])  # curr bullish
                and float(curr["open"]) <= float(prev["close"])
                and float(curr["close"]) >= float(prev["open"])
                and body > prev_body):
            patterns.append("bullish_engulfing")
        # Bearish Engulfing
        if (float(prev["close"]) > float(prev["open"])  # prev bullish
                and float(curr["close"]) < float(curr["open"])  # curr bearish
                and float(curr["open"]) >= float(prev["close"])
                and float(curr["close"]) <= float(prev["open"])
                and body > prev_body):
            patterns.append("bearish_engulfing")
        # Morning Star (3-candle bullish reversal)
        if len(self.df) >= 3:
            c3 = self.df.iloc[-3]
            c2 = self.df.iloc[-2]
            c1 = self.df.iloc[-1]
            c3_bearish = float(c3["close"]) < float(c3["open"])
            c2_small = abs(float(c2["close"] - c2["open"])) < abs(float(c3["close"] - c3["open"])) * 0.3
            c1_bullish = float(c1["close"]) > float(c1["open"])
            c1_recovers = float(c1["close"]) > (float(c3["open"]) + float(c3["close"])) / 2
            if c3_bearish and c2_small and c1_bullish and c1_recovers:
                patterns.append("morning_star")
        # Evening Star (3-candle bearish reversal)
        if len(self.df) >= 3:
            c3 = self.df.iloc[-3]
            c2 = self.df.iloc[-2]
            c1 = self.df.iloc[-1]
            c3_bullish = float(c3["close"]) > float(c3["open"])
            c2_small = abs(float(c2["close"] - c2["open"])) < abs(float(c3["close"] - c3["open"])) * 0.3
            c1_bearish = float(c1["close"]) < float(c1["open"])
            c1_drops = float(c1["close"]) < (float(c3["open"]) + float(c3["close"])) / 2
            if c3_bullish and c2_small and c1_bearish and c1_drops:
                patterns.append("evening_star")

        self.indicators["candle_patterns"] = patterns
        bullish = {"hammer", "pin_bar_bullish", "bullish_engulfing", "morning_star"}
        bearish = {"shooting_star", "pin_bar_bearish", "bearish_engulfing", "evening_star"}
        bull_count = sum(1 for p in patterns if p in bullish)
        bear_count = sum(1 for p in patterns if p in bearish)
        if bull_count > bear_count:
            self.indicators["candle_pattern_bias"] = "bullish"
        elif bear_count > bull_count:
            self.indicators["candle_pattern_bias"] = "bearish"
        else:
            self.indicators["candle_pattern_bias"] = "neutral"

    def calculate_fibonacci(self) -> None:
        """Build Fibonacci attraction zones anchored only on confirmed volume pivots."""
        pivots = self.indicators.get("confirmed_pivots", [])
        low_pivots = [p for p in pivots if p["type"] == "low"]
        high_pivots = [p for p in pivots if p["type"] == "high"]
        atr = float(self.indicators.get("atr", 0)) or float(self.df["close"].iloc[-1]) * 0.01
        current = float(self.df["close"].iloc[-1])
        if not low_pivots or not high_pivots:
            self.indicators["fib_attraction_zones"] = []
            self.indicators["fib_nearest_level"] = ""
            self.indicators["fib_nearest_price"] = None
            return
        low = low_pivots[-1]
        high = high_pivots[-1]
        swing_low = float(low["price"])
        swing_high = float(high["price"])
        if swing_high == swing_low:
            self.indicators["fib_attraction_zones"] = []
            return
        start, end = (swing_low, swing_high) if low["index"] < high["index"] else (swing_high, swing_low)
        diff = end - start
        zones = []
        for label, ratio in (("38.2%", 0.382), ("50%", 0.5), ("61.8%", 0.618)):
            center = end - diff * ratio
            zones.append({"label": label, "center": center, "lower": center - atr * 0.5, "upper": center + atr * 0.5})
            self.indicators[f"fib_{label.replace('.', '').replace('%', '')}"] = center
        nearest = min(zones, key=lambda item: abs(item["center"] - current))
        self.indicators["fib_attraction_zones"] = zones
        self.indicators["fib_nearest_level"] = nearest["label"]
        self.indicators["fib_nearest_price"] = nearest["center"]

    def calculate_trend_strength(self) -> None:
        """Composite trend strength score from 0-100."""
        score = 0
        # ADX contribution (0-30)
        adx = self.indicators.get("adx", 20)
        score += min(30, adx * 0.75)
        # EMA alignment (0-25)
        ma_trend = str(self.indicators.get("ma_trend", "neutral"))
        if "strong" in ma_trend:
            score += 25
        elif "weak" in ma_trend:
            score += 12
        # Structure (0-20)
        structure = str(self.indicators.get("structure", "range"))
        if structure in ("higher_highs_higher_lows", "lower_highs_lower_lows"):
            score += 20
        elif structure == "range":
            score += 5
        # MACD histogram momentum (0-15)
        hist = self.indicators.get("macd_hist", 0)
        hist_prev = self.indicators.get("macd_hist_prev", 0)
        if abs(hist) > abs(hist_prev) and hist * hist_prev > 0:
            score += 15  # accelerating
        elif hist * hist_prev > 0:
            score += 8
        # Volume confirmation (0-10)
        vol_ratio = self.indicators.get("volume_ratio", 1)
        if vol_ratio >= 1.5:
            score += 10
        elif vol_ratio >= 1.0:
            score += 5
        self.indicators["trend_strength_score"] = min(100, int(score))
        if score >= 75:
            self.indicators["trend_strength"] = "forte"
        elif score >= 45:
            self.indicators["trend_strength"] = "moderada"
        else:
            self.indicators["trend_strength"] = "fraca"

    def calculate_momentum_state(self) -> None:
        """Classify momentum as accelerating, stable, or decelerating."""
        hist = self.indicators.get("macd_hist", 0)
        hist_prev = self.indicators.get("macd_hist_prev", 0)
        rsi = self.indicators.get("rsi", 50)
        rsi_prev = self.indicators.get("rsi_prev", 50)
        macd_accel = abs(hist) > abs(hist_prev) * 1.05
        rsi_accel = abs(rsi - 50) > abs(rsi_prev - 50)
        if macd_accel and rsi_accel:
            self.indicators["momentum"] = "acelerando"
        elif not macd_accel and not rsi_accel:
            self.indicators["momentum"] = "desacelerando"
        else:
            self.indicators["momentum"] = "estavel"

    def classify_market_regime(self) -> None:
        """Classify market into: trending, ranging, volatile, breakout."""
        adx = self.indicators.get("adx", 20)
        volatility = self.indicators.get("volatility", 0)
        breakout_up = self.indicators.get("breakout_up", False)
        breakout_down = self.indicators.get("breakout_down", False)
        bb_width = self.indicators.get("bb_width", 0)
        if breakout_up or breakout_down:
            regime = "breakout"
        elif adx >= 25 and volatility < 0.04:
            regime = "trending"
        elif volatility >= 0.04 or bb_width >= 0.08:
            regime = "volatile"
        else:
            regime = "ranging"
        self.indicators["market_regime"] = regime

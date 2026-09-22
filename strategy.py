from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Mapping, Tuple

import pandas as pd

from indicators import TechnicalIndicators


class AnalysisDecision(Enum):
    LONG_SETUP = "LONG_SETUP"
    SHORT_SETUP = "SHORT_SETUP"
    WAIT = "WAIT"
    INVALIDATED = "INVALIDATED"


class Trend(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"


@dataclass(frozen=True)
class TimeframeAnalysis:
    timeframe: str
    trend: Trend
    structure: str
    indicators: Dict


@dataclass(frozen=True)
class MarketSignal:
    symbol: str
    timestamp: str
    current_price: Decimal
    dominant_direction: str
    timeframe_trends: Dict[str, str]
    score: int
    decision: AnalysisDecision
    reasons: List[str]
    ideal_entry_region: Tuple[Decimal, Decimal] | None
    stop_loss: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    risk_reward: Decimal
    invalidation_level: Decimal | None
    prerequisites: List[str] = field(default_factory=list)
    cancel_conditions: List[str] = field(default_factory=list)
    confidence_level: str = "media"
    trend_strength: str = "moderada"
    momentum: str = "estavel"
    market_regime: str = "ranging"
    narrative: str = ""
    key_levels: Dict = field(default_factory=dict)
    candle_patterns: List[str] = field(default_factory=list)
    divergences: Dict[str, str] = field(default_factory=dict)
    detailed_indicators: Dict = field(default_factory=dict)
    alert_type: str = ""
    alert_message: str = ""
    alert_direction: str = ""
    warning: str = "Sinal educacional; nao ha garantia de lucro."

    @property
    def signal_id(self) -> str:
        entry = self.ideal_entry_region or (Decimal("0"), Decimal("0"))
        return f"{self.symbol}:{self.decision.value}:{entry[0]}:{entry[1]}:{self.invalidation_level}"

    def as_dict(self) -> Dict:
        return {
            "ativo": self.symbol,
            "data_hora": self.timestamp,
            "preco_atual": str(self.current_price),
            "direcao_predominante": self.dominant_direction,
            "tendencias": self.timeframe_trends,
            "score": self.score,
            "decisao": self.decision.value,
            "justificativa": self.reasons,
            "regiao_ideal_entrada": [str(x) for x in self.ideal_entry_region] if self.ideal_entry_region else None,
            "stop_loss_tecnico": str(self.stop_loss) if self.stop_loss else None,
            "alvo_1": str(self.target_1) if self.target_1 else None,
            "alvo_2": str(self.target_2) if self.target_2 else None,
            "alvo_3": str(self.target_3) if self.target_3 else None,
            "risco_retorno": str(self.risk_reward),
            "nivel_invalidation": str(self.invalidation_level) if self.invalidation_level else None,
            "condicoes_antes_entrada": self.prerequisites,
            "condicoes_cancelam_sinal": self.cancel_conditions,
            "confianca": self.confidence_level,
            "forca_tendencia": self.trend_strength,
            "momentum": self.momentum,
            "regime_mercado": self.market_regime,
            "narrativa": self.narrative,
            "niveis_chave": self.key_levels,
            "padroes_candle": self.candle_patterns,
            "divergencias": self.divergences,
            "indicadores_detalhados": self.detailed_indicators,
            "tipo_alerta": self.alert_type,
            "mensagem_alerta": self.alert_message,
            "direcao_alerta": self.alert_direction,
            "aviso": self.warning,
            "signal_id": self.signal_id,
        }


class MarketAnalyzer:
    REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}

    def __init__(
        self,
        symbol: str,
        candles_by_timeframe: Mapping[str, pd.DataFrame],
        config=None,
        spread_percent: Decimal | None = None,
    ):
        self.symbol = symbol
        self.config = config
        self.spread_percent = spread_percent
        self.candles_by_timeframe = {
            timeframe: self._validated_closed_candles(df)
            for timeframe, df in candles_by_timeframe.items()
        }
        self.timeframes = {
            "context": getattr(config, "CONTEXT_TIMEFRAME", "4h"),
            "confirmation": getattr(config, "CONFIRMATION_TIMEFRAME", "1h"),
            "setup": getattr(config, "SETUP_TIMEFRAME", "15m"),
            "refinement": getattr(config, "REFINEMENT_TIMEFRAME", "5m"),
        }
        self.analyses = self._analyze_timeframes()

    def generate_signal(self) -> MarketSignal:
        setup_tf = self.timeframes["setup"]
        setup = self.analyses[setup_tf]
        ind = setup.indicators
        price = Decimal(str(self.candles_by_timeframe[setup_tf]["close"].iloc[-1]))
        timestamp = self.candles_by_timeframe[setup_tf]["close_time"].iloc[-1].isoformat()
        filters_ok, filter_reasons = self._market_filters()
        trends = {tf: analysis.trend.value for tf, analysis in self.analyses.items()}
        dominant = self._dominant_direction()
        score_long, long_reasons = self._direction_score(Trend.BULLISH)
        score_short, short_reasons = self._direction_score(Trend.BEARISH)
        zone_alert = self._zone_alert(price, timestamp, trends, dominant)

        if not filters_ok:
            return self._wait(price, timestamp, trends, dominant, filter_reasons, zone_alert)
        if bool(ind.get("false_breakout_up")):
            return self._invalidated(price, timestamp, trends, dominant, ["falso rompimento no periodo de setup"])

        trigger_signal = self._entry_trigger_signal(price, timestamp, trends, zone_alert)
        if trigger_signal:
            return trigger_signal

        reversal_signal = self._reversal_zone_signal(price, timestamp, trends, zone_alert)
        if reversal_signal:
            return reversal_signal

        continuation_signal = self._breakdown_continuation_signal(price, timestamp, trends, zone_alert)
        if continuation_signal:
            return continuation_signal

        if self._has_major_conflict():
            if zone_alert and zone_alert["priority"] >= 2:
                return self._wait(price, timestamp, trends, dominant,
                                 ["conflito entre periodos — alerta de zona ativo"], zone_alert)
            return self._wait(price, timestamp, trends, dominant, ["conflito relevante entre periodos"], zone_alert)

        setup_regime = str(self.analyses[self.timeframes["setup"]].indicators.get("market_regime", "ranging"))
        score_threshold = 60 if setup_regime in ("ranging", "volatile") else 70

        if score_long > score_short and score_long >= score_threshold:
            signal = self._build_directional_signal(AnalysisDecision.LONG_SETUP, price, timestamp, trends, score_long, long_reasons)
        elif score_short > score_long and score_short >= score_threshold:
            signal = self._build_directional_signal(AnalysisDecision.SHORT_SETUP, price, timestamp, trends, score_short, short_reasons)
        elif score_long == score_short and score_long >= score_threshold:
            if dominant == "baixa":
                signal = self._build_directional_signal(AnalysisDecision.SHORT_SETUP, price, timestamp, trends, score_short, short_reasons)
            elif dominant == "alta":
                signal = self._build_directional_signal(AnalysisDecision.LONG_SETUP, price, timestamp, trends, score_long, long_reasons)
            else:
                return self._wait(price, timestamp, trends, dominant, ["scores empatados com direcao indefinida"], zone_alert)
        else:
            return self._wait(price, timestamp, trends, dominant, long_reasons + short_reasons or ["sem confirmacao suficiente"], zone_alert)

        if signal.risk_reward < Decimal(str(getattr(self.config, "MIN_RISK_REWARD", Decimal("2")))):
            return self._wait(
                price,
                timestamp,
                trends,
                dominant,
                signal.reasons + ["relacao risco/retorno inferior a 1:2"],
                zone_alert,
            )
        if zone_alert:
            signal = replace(
                signal,
                alert_type=zone_alert["type"],
                alert_message=zone_alert["message"],
                alert_direction=zone_alert["direction"],
            )
        return signal

    def _validated_closed_candles(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = self.REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"missing required candle columns: {sorted(missing)}")
        clean = df.copy().dropna(subset=list(self.REQUIRED_COLUMNS))
        if "close_time" in clean.columns:
            now = pd.Timestamp.now(tz="UTC")
            clean = clean[pd.to_datetime(clean["close_time"], utc=True) <= now]
        min_len = max(getattr(self.config, "MA_TREND", 200), 50) if self.config else 200
        if len(clean) < min_len:
            raise ValueError(f"not enough closed candles: {len(clean)} < {min_len}")
        clean = clean.drop_duplicates(subset=["timestamp"], keep="last")
        if not clean["timestamp"].is_monotonic_increasing:
            clean = clean.sort_values("timestamp")
        if clean[["open", "high", "low", "close", "volume"]].le(0).any().any():
            raise ValueError("candle data contains non-positive OHLCV values")
        return clean.reset_index(drop=True)

    def _analyze_timeframes(self) -> Dict[str, TimeframeAnalysis]:
        analyses = {}
        for timeframe, df in self.candles_by_timeframe.items():
            indicators = TechnicalIndicators(df, self.config).calculate_all()
            analyses[timeframe] = TimeframeAnalysis(
                timeframe=timeframe,
                trend=self._classify_trend(indicators),
                structure=str(indicators.get("structure", "range")),
                indicators=indicators,
            )
        return analyses

    def _classify_trend(self, indicators: Dict) -> Trend:
        ma_trend = str(indicators.get("ma_trend", "neutral"))
        structure = str(indicators.get("structure", "range"))
        macd = str(indicators.get("macd_signal_type", "neutral"))
        if ma_trend.startswith("bullish") and structure != "lower_highs_lower_lows" and macd.startswith("bullish"):
            return Trend.BULLISH
        if ma_trend.startswith("bearish") and structure != "higher_highs_higher_lows" and macd.startswith("bearish"):
            return Trend.BEARISH
        return Trend.SIDEWAYS

    def _market_filters(self) -> Tuple[bool, List[str]]:
        setup = self.analyses[self.timeframes["setup"]].indicators
        reasons = []
        if self.config:
            if setup.get("volatility", 0) > float(self.config.MAX_VOLATILITY_FILTER):
                reasons.append("volatilidade acima do filtro")
            if self.spread_percent is not None and self.spread_percent > self.config.MAX_SPREAD_FILTER:
                reasons.append("spread elevado")
            if setup.get("volume_ratio", 1) < float(self.config.MIN_VOLUME_RATIO):
                reasons.append("volume insuficiente")
            if setup.get("quote_volume", 0) < float(self.config.MIN_QUOTE_VOLUME_USDT):
                reasons.append("baixa liquidez")
        return not reasons, reasons

    def _has_major_conflict(self) -> bool:
        context = self.analyses[self.timeframes["context"]].trend
        confirmation = self.analyses[self.timeframes["confirmation"]].trend
        setup = self.analyses[self.timeframes["setup"]].trend
        return (
            context == Trend.BULLISH and confirmation == Trend.BEARISH
            or context == Trend.BEARISH and confirmation == Trend.BULLISH
            or setup != Trend.SIDEWAYS and context != Trend.SIDEWAYS and setup != context
        )

    def _dominant_direction(self) -> str:
        context = self.analyses[self.timeframes["context"]].trend
        confirmation = self.analyses[self.timeframes["confirmation"]].trend
        if context == confirmation and context != Trend.SIDEWAYS:
            return "alta" if context == Trend.BULLISH else "baixa"
        return "indefinida"

    # =========================================================================
    # Professional scoring with dynamic confluence
    # =========================================================================

    def _direction_score(self, direction: Trend) -> Tuple[int, List[str]]:
        setup = self.analyses[self.timeframes["setup"]]
        ind = setup.indicators
        score = 0
        reasons = []

        # --- Multi-timeframe alignment (0-44) ---
        aligned_count = 0
        for label in ["context", "confirmation"]:
            trend = self.analyses[self.timeframes[label]].trend
            if trend == direction:
                score += 20
                aligned_count += 1
                reasons.append(f"{self.timeframes[label]} alinhado com {direction.value}")
            elif trend == Trend.SIDEWAYS:
                score += 5

        if setup.trend == direction:
            score += 15
            aligned_count += 1
            reasons.append(f"{setup.timeframe} confirma a direcao")

        poc_bias = str(ind.get("poc_bias", "neutro"))
        poc_short_bias = str(ind.get("poc_short_bias", "neutro"))
        if (direction == Trend.BULLISH and poc_short_bias == "altista") or (direction == Trend.BEARISH and poc_short_bias == "baixista"):
            score += 8
            reasons.append(f"POC 6h confirma vies {poc_short_bias}")
        elif (direction == Trend.BULLISH and poc_short_bias == "baixista") or (direction == Trend.BEARISH and poc_short_bias == "altista"):
            score -= 8
            reasons.append("POC 6h contra a direcao")
        if poc_bias != poc_short_bias:
            reasons.append(f"POC 24h apenas como contexto macro: {poc_bias}")

        # Confluence bonus: when 3+ timeframes agree, double the base weight
        if aligned_count >= 3:
            score += 12
            reasons.append("confluencia de 3+ timeframes")

        # --- Breakout (0-15) ---
        if direction == Trend.BULLISH and ind.get("breakout_up"):
            score += 15
            reasons.append("rompimento de resistencia recente")
        if direction == Trend.BEARISH and ind.get("breakout_down"):
            score += 15
            reasons.append("rompimento de suporte recente")

        # --- EMA/VWAP position (0-10) ---
        if direction == Trend.BULLISH and float(ind.get("distance_ema_21", 0)) >= 0 and float(ind.get("distance_vwap", 0)) >= 0:
            score += 10
            reasons.append("preco acima da EMA 21 e VWAP")
        if direction == Trend.BEARISH and float(ind.get("distance_ema_21", 0)) <= 0 and float(ind.get("distance_vwap", 0)) <= 0:
            score += 10
            reasons.append("preco abaixo da EMA 21 e VWAP")

        # --- Volume (0-10) ---
        if ind.get("volume_ratio", 1) >= 1.2:
            score += 10
            reasons.append(f"volume {ind.get('volume_ratio', 1):.2f}x a media")

        # --- RSI zone (0-10) ---
        rsi = float(ind.get("rsi", 50))
        if direction == Trend.BULLISH and 45 <= rsi <= 70:
            score += 10
            reasons.append(f"RSI saudavel para alta: {rsi:.1f}")
        if direction == Trend.BEARISH and 30 <= rsi <= 55:
            score += 10
            reasons.append(f"RSI saudavel para baixa: {rsi:.1f}")

        # --- NEW: ADX trend strength bonus/penalty (-10 to +12) ---
        adx = float(ind.get("adx", 20))
        if adx >= 30:
            score += 12
            reasons.append(f"ADX forte ({adx:.0f}): tendencia definida")
        elif adx >= 20:
            score += 5
        elif adx < 15:
            score -= 10
            reasons.append(f"ADX fraco ({adx:.0f}): sem tendencia definida")

        # --- NEW: Divergence bonus (0-12) ---
        rsi_div = str(ind.get("rsi_divergence", "none"))
        macd_div = str(ind.get("macd_divergence", "none"))
        if direction == Trend.BULLISH:
            if rsi_div == "bullish":
                score += 8
                reasons.append("divergencia altista no RSI")
            if macd_div == "bullish":
                score += 4
                reasons.append("divergencia altista no MACD")
        if direction == Trend.BEARISH:
            if rsi_div == "bearish":
                score += 8
                reasons.append("divergencia baixista no RSI")
            if macd_div == "bearish":
                score += 4
                reasons.append("divergencia baixista no MACD")

        # --- NEW: Candle pattern confirmation (0-10) ---
        candle_bias = str(ind.get("candle_pattern_bias", "neutral"))
        patterns = ind.get("candle_patterns", [])
        if direction == Trend.BULLISH and candle_bias == "bullish":
            score += 10
            reasons.append(f"padrao de candle altista: {', '.join(patterns)}")
        elif direction == Trend.BEARISH and candle_bias == "bearish":
            score += 10
            reasons.append(f"padrao de candle baixista: {', '.join(patterns)}")

        # --- NEW: OBV confirmation (0-8) ---
        obv_trend = str(ind.get("obv_trend", "neutral"))
        if (direction == Trend.BULLISH and obv_trend == "bullish") or \
           (direction == Trend.BEARISH and obv_trend == "bearish"):
            score += 8
            reasons.append("OBV confirma pressao de volume na direcao")

        # --- NEW: Stochastic RSI confluence (0-8) ---
        stoch_rsi = str(ind.get("stoch_rsi_signal", "neutral"))
        if direction == Trend.BULLISH and stoch_rsi == "oversold":
            score += 8
            reasons.append("Stochastic RSI em sobrevenda (oportunidade)")
        elif direction == Trend.BEARISH and stoch_rsi == "overbought":
            score += 8
            reasons.append("Stochastic RSI em sobrecompra (oportunidade)")

        # --- NEW: RSI in extreme zone AGAINST direction = penalty (-8) ---
        if direction == Trend.BULLISH and rsi > 80:
            score -= 8
            reasons.append(f"RSI sobrecomprado ({rsi:.0f}): risco de reversao")
        if direction == Trend.BEARISH and rsi < 20:
            score -= 8
            reasons.append(f"RSI sobrevendido ({rsi:.0f}): risco de reversao")

        # --- Penalty: recent price action against direction (-12) ---
        refinement_tf = self.timeframes["refinement"]
        if refinement_tf in self.analyses:
            ref_trend = self.analyses[refinement_tf].trend
            if direction == Trend.BULLISH and ref_trend == Trend.BEARISH:
                score -= 12
                reasons.append("acao de preco recente contra direcao de compra")
            elif direction == Trend.BEARISH and ref_trend == Trend.BULLISH:
                score -= 12
                reasons.append("acao de preco recente contra direcao de venda")

        return min(max(score, 0), 100), reasons

    def _entry_trigger_signal(
        self,
        price: Decimal,
        timestamp: str,
        trends: Dict[str, str],
        zone_alert: Dict | None,
    ) -> MarketSignal | None:
        setup_ind = self.analyses[self.timeframes["setup"]].indicators
        setup_df = self.candles_by_timeframe[self.timeframes["setup"]]
        refinement_tf = self.timeframes["refinement"]
        if refinement_tf not in self.candles_by_timeframe:
            return None
        trigger_df = self.candles_by_timeframe[refinement_tf]
        trigger_ind = self.analyses.get(refinement_tf)
        if trigger_ind is None or trigger_df.empty:
            return None
        confirmation = self._confirmar_entrada(setup_df.iloc[-1], trigger_df.iloc[-1], setup_ind, trigger_ind.indicators)
        if not confirmation["valid"]:
            return None

        direction = Trend.BULLISH if confirmation["direction"] == "compra" else Trend.BEARISH
        decision = AnalysisDecision.LONG_SETUP if direction == Trend.BULLISH else AnalysisDecision.SHORT_SETUP
        trigger_price = Decimal(str(trigger_df["close"].iloc[-1]))
        trigger_timestamp = trigger_df["close_time"].iloc[-1].isoformat()
        score_base, reasons = self._direction_score(direction)
        signal = self._build_directional_signal(
            decision,
            trigger_price,
            trigger_timestamp,
            trends,
            max(85, min(100, score_base + 18)),
            [*reasons, *confirmation["reasons"]],
        )
        if zone_alert:
            signal = replace(
                signal,
                alert_type=zone_alert["type"],
                alert_message=zone_alert["message"],
                alert_direction=zone_alert["direction"],
            )
        return signal

    def _confirmar_entrada(self, setup_candle: pd.Series, trigger_candle: pd.Series, setup_ind: Dict, trigger_ind: Dict) -> Dict:
        close_15 = Decimal(str(setup_candle["close"]))
        atr = Decimal(str(setup_ind.get("atr", 0))) or close_15 * Decimal("0.01")
        demand = setup_ind.get("nearest_demand_zone")
        supply = setup_ind.get("nearest_supply_zone")
        open_5 = Decimal(str(trigger_candle["open"]))
        close_5 = Decimal(str(trigger_candle["close"]))
        high_5 = Decimal(str(trigger_candle["high"]))
        low_5 = Decimal(str(trigger_candle["low"]))
        body = max(abs(close_5 - open_5), Decimal("0.00000001"))
        lower_wick = min(close_5, open_5) - low_5
        upper_wick = high_5 - max(close_5, open_5)
        patterns = set(trigger_ind.get("candle_patterns", []))
        volume_ok = Decimal(str(trigger_ind.get("volume_ratio", 0))) >= Decimal("1")
        bullish_pattern = lower_wick > body * Decimal("0.5") or {"pin_bar_bullish", "bullish_engulfing"} & patterns
        bearish_pattern = upper_wick > body * Decimal("0.5") or {"pin_bar_bearish", "bearish_engulfing"} & patterns

        near_demand = demand and abs(close_15 - Decimal(str(demand["upper"]))) <= atr
        near_supply = supply and abs(close_15 - Decimal(str(supply["lower"]))) <= atr
        if near_demand and bullish_pattern and volume_ok:
            return {
                "valid": True,
                "direction": "compra",
                "reasons": [
                    "contexto 15m proximo da zona de demanda",
                    "gatilho 5m confirmou padrao comprador com volume",
                ],
            }
        if near_supply and bearish_pattern and volume_ok:
            return {
                "valid": True,
                "direction": "venda",
                "reasons": [
                    "contexto 15m proximo da zona de supply",
                    "gatilho 5m confirmou padrao vendedor com volume",
                ],
            }
        return {"valid": False, "reasons": ["gatilho 5m ainda sem padrao e volume confirmados"]}

    def _reversal_zone_signal(
        self,
        price: Decimal,
        timestamp: str,
        trends: Dict[str, str],
        zone_alert: Dict | None,
    ) -> MarketSignal | None:
        setup_ind = self.analyses[self.timeframes["setup"]].indicators
        setup_df = self.candles_by_timeframe[self.timeframes["setup"]]
        demand_zone = setup_ind.get("nearest_demand_zone")
        if not demand_zone or not self._is_demand_rejection(setup_df.iloc[-1], setup_ind, demand_zone):
            return None

        score_long, reasons = self._direction_score(Trend.BULLISH)
        score = max(70, min(100, score_long + 20))
        reasons = reasons + [
            "rejeicao confirmada em zona de demanda",
            "RSI saindo de sobrevenda",
            "volume minimo de reversao confirmado",
        ]
        signal = self._build_directional_signal(
            AnalysisDecision.LONG_SETUP,
            price,
            timestamp,
            trends,
            score,
            reasons,
        )
        if signal.risk_reward < Decimal(str(getattr(self.config, "MIN_RISK_REWARD", Decimal("2")))):
            return self._wait(
                price,
                timestamp,
                trends,
                "alta",
                signal.reasons + ["reversao em demanda sem relacao risco/retorno minima"],
                zone_alert,
            )
        if zone_alert:
            signal = replace(
                signal,
                alert_type=zone_alert["type"],
                alert_message=zone_alert["message"],
                alert_direction=zone_alert["direction"],
            )
        return signal

    def _breakdown_continuation_signal(
        self,
        price: Decimal,
        timestamp: str,
        trends: Dict[str, str],
        zone_alert: Dict | None,
    ) -> MarketSignal | None:
        setup_ind = self.analyses[self.timeframes["setup"]].indicators
        setup_df = self.candles_by_timeframe[self.timeframes["setup"]]
        demand_zone = setup_ind.get("nearest_demand_zone")
        if not demand_zone:
            return None
        candle = setup_df.iloc[-1]
        close = Decimal(str(candle["close"]))
        volume = Decimal(str(candle["volume"]))
        volume_sma = Decimal(str(setup_ind.get("volume_sma", 1))) or Decimal("1")
        below_break = close < Decimal(str(demand_zone["break_price"]))
        volume_break = volume > volume_sma * Decimal("1.3")
        below_trend_refs = (
            Decimal(str(setup_ind.get("distance_ema_21", 0))) <= 0
            and Decimal(str(setup_ind.get("distance_vwap", 0))) <= 0
        )
        if not (below_break and volume_break and below_trend_refs):
            return None
        if not self._is_continuation_context(Trend.BEARISH):
            return None

        score_short, reasons = self._direction_score(Trend.BEARISH)
        score = max(70, min(100, score_short + 15))
        reasons = reasons + [
            "fechamento abaixo do break_price da zona de demanda",
            "volume de rompimento acima de 1.3x a media",
            "preco abaixo da EMA 21 e VWAP",
        ]
        signal = self._build_directional_signal(
            AnalysisDecision.SHORT_SETUP,
            price,
            timestamp,
            trends,
            score,
            reasons,
        )
        if signal.risk_reward < Decimal(str(getattr(self.config, "MIN_RISK_REWARD", Decimal("2")))):
            return self._wait(
                price,
                timestamp,
                trends,
                "baixa",
                signal.reasons + ["rompimento sem relacao risco/retorno minima"],
                zone_alert,
            )
        if zone_alert:
            signal = replace(
                signal,
                alert_type=zone_alert["type"],
                alert_message=zone_alert["message"],
                alert_direction=zone_alert["direction"],
            )
        return signal

    def _is_continuation_context(self, direction: Trend) -> bool:
        context = self.analyses[self.timeframes["context"]].trend
        confirmation = self.analyses[self.timeframes["confirmation"]].trend
        setup = self.analyses[self.timeframes["setup"]].trend
        return setup == direction and confirmation == direction and context == direction

    def _is_demand_rejection(self, candle: pd.Series, ind: Dict, demand_zone: Dict) -> bool:
        close = Decimal(str(candle["close"]))
        open_ = Decimal(str(candle["open"]))
        high = Decimal(str(candle["high"]))
        low = Decimal(str(candle["low"]))
        volume = Decimal(str(candle["volume"]))
        lower = Decimal(str(demand_zone["lower"]))
        upper = Decimal(str(demand_zone["upper"]))
        break_price = Decimal(str(demand_zone["break_price"]))
        volume_sma = Decimal(str(ind.get("volume_sma", 1))) or Decimal("1")
        body = max(abs(close - open_), Decimal("0.00000001"))
        lower_wick = min(close, open_) - low
        touched = low <= upper and high >= lower
        closed_back_above_zone_edge = close >= lower
        above_invalidation = close > break_price
        rsi = Decimal(str(ind.get("rsi", 50)))
        rsi_prev = Decimal(str(ind.get("rsi_prev", 50)))
        rsi_recovering = rsi_prev <= Decimal("35") and rsi > rsi_prev
        volume_ok = volume >= volume_sma * Decimal("0.8")
        wick_ok = lower_wick > body * Decimal("0.5")
        return bool(touched and closed_back_above_zone_edge and above_invalidation and wick_ok and rsi_recovering and volume_ok)

    def _zone_alert(self, price: Decimal, timestamp: str, trends: Dict[str, str], dominant: str) -> Dict | None:
        setup_ind = self.analyses[self.timeframes["setup"]].indicators
        setup_df = self.candles_by_timeframe[self.timeframes["setup"]]
        candle = setup_df.iloc[-1]
        atr = Decimal(str(setup_ind.get("atr", 0))) or price * Decimal("0.01")
        volume = Decimal(str(candle["volume"]))
        volume_sma = Decimal(str(setup_ind.get("volume_sma", 1))) or Decimal("1")
        # 5-candle volume average for rejection confirmation
        vol_5 = Decimal(str(setup_df["volume"].tail(5).mean()))
        close = Decimal(str(candle["close"]))
        open_ = Decimal(str(candle["open"]))
        high = Decimal(str(candle["high"]))
        low = Decimal(str(candle["low"]))
        body = abs(close - open_)
        upper_wick = high - max(close, open_)
        lower_wick = min(close, open_) - low
        alerts: List[Dict] = []
        for kind, zone, direction, label in (
            ("supply", setup_ind.get("nearest_supply_zone"), "venda", "Supply"),
            ("demand", setup_ind.get("nearest_demand_zone"), "compra", "Demand"),
        ):
            if not zone:
                continue
            lower = Decimal(str(zone["lower"]))
            upper = Decimal(str(zone["upper"]))
            distance = min(abs(price - lower), abs(price - upper))
            touched = low <= upper and high >= lower

            # ═══ MICRO_BREAKOUT: closes beyond zone with volume > 1.3x mean ═══
            if kind == "supply" and close > upper and volume > volume_sma * Decimal("1.3"):
                alerts.append(self._alert_payload(
                    "MICRO_BREAKOUT",
                    "\U0001f7e2 ROMPEU COM FORCA — Entrada a favor do rompimento, stop na borda oposta",
                    "compra", zone, 3))
            elif kind == "demand" and close < lower and volume > volume_sma * Decimal("1.3"):
                alerts.append(self._alert_payload(
                    "MICRO_BREAKOUT",
                    "\U0001f7e2 ROMPEU COM FORCA — Entrada a favor do rompimento, stop na borda oposta",
                    "venda", zone, 3))

            # ═══ STOP_HUNT: wick beyond zone but close back inside ═══
            if kind == "supply" and high > upper and close <= upper and close >= lower:
                if volume > volume_sma * Decimal("1.2"):
                    alerts.append(self._alert_payload(
                        "STOP_HUNT",
                        "\u26a0\ufe0f FALSO ROMPIMENTO — Preco rompeu e voltou. Aguardar confirmacao contraria",
                        "venda", zone, 4))
            elif kind == "demand" and low < lower and close >= lower and close <= upper:
                if volume > volume_sma * Decimal("1.2"):
                    alerts.append(self._alert_payload(
                        "STOP_HUNT",
                        "\u26a0\ufe0f FALSO ROMPIMENTO — Preco rompeu e voltou. Aguardar confirmacao contraria",
                        "compra", zone, 4))

            # ═══ REJECTION: touches zone edge, wick > 50% body, volume > 5-candle avg ═══
            if touched and kind == "supply" and upper_wick > body * Decimal("0.5") and volume > vol_5:
                alerts.append(self._alert_payload(
                    "REJECTION",
                    "\U0001f534 REJEICAO CONFIRMADA — Pavio longo + volume. Prepare short",
                    "venda", zone, 2))
            elif touched and kind == "demand" and lower_wick > body * Decimal("0.5") and volume > vol_5:
                alerts.append(self._alert_payload(
                    "REJECTION",
                    "\U0001f534 REJEICAO CONFIRMADA — Pavio longo + volume. Prepare long",
                    "compra", zone, 2))

            # ═══ HOT_ZONE: price within 0.3 ATR of zone edge ═══
            if distance <= atr * Decimal("0.3"):
                alerts.append(self._alert_payload(
                    "HOT_ZONE",
                    f"\U0001f7e1 ZONA QUENTE — A {float(distance):.0f} pts da borda. Prepare entrada",
                    direction, zone, 1, label))
        if not alerts:
            return None
        return max(alerts, key=lambda item: item["priority"])

    def _alert_payload(self, alert_type: str, message: str, direction: str, zone: Dict, priority: int, label: str = "") -> Dict:
        return {
            "type": alert_type,
            "message": f"{message} ({label or zone.get('type', 'zona')}: {zone['lower']:.2f} - {zone['upper']:.2f})",
            "direction": direction,
            "zone": zone,
            "priority": priority,
        }

    def _build_directional_signal(
        self,
        decision: AnalysisDecision,
        price: Decimal,
        timestamp: str,
        trends: Dict[str, str],
        score: int,
        reasons: List[str],
    ) -> MarketSignal:
        ind = self.analyses[self.timeframes["setup"]].indicators
        atr = Decimal(str(ind.get("atr", 0))) or price * Decimal("0.01")
        demand_zone = self._zone_as_decimal(ind.get("nearest_demand_zone"), price - atr)
        supply_zone = self._zone_as_decimal(ind.get("nearest_supply_zone"), price + atr)
        min_stop_percent = Decimal(str(getattr(self.config, "STOP_LOSS_PERCENT", Decimal("0.02"))))
        if decision == AnalysisDecision.LONG_SETUP:
            entry_low = demand_zone["lower"]
            entry_high = demand_zone["upper"]
            entry_reference = (entry_low + entry_high) / Decimal("2")
            technical_stop = demand_zone["break_price"] - atr * Decimal("0.1")
            minimum_distance_stop = entry_reference * (Decimal("1") - min_stop_percent)
            stop = min(technical_stop, minimum_distance_stop)
            targets = self._calcular_alvos(entry_reference, stop, long=True)
            invalidation = stop
            prerequisites = [
                "aguardar fechamento do candle dentro ou acima da zona de demanda",
                "confirmar reteste sem fechamento abaixo da borda externa da zona + ATR",
                "manter volume igual ou acima da media",
                "gatilho de entrada deve fechar no 5m com padrao e volume",
            ]
            cancel = ["fechamento abaixo do stop tecnico", "perda do contexto de 4h/1h", "spread ou liquidez fora do filtro", "time stop: 4h sem atingir alvo 1 ou fechamento as 22h BRT"]
        else:
            entry_low = supply_zone["lower"]
            entry_high = supply_zone["upper"]
            entry_reference = (entry_low + entry_high) / Decimal("2")
            technical_stop = supply_zone["break_price"]
            minimum_distance_stop = entry_reference * (Decimal("1") + min_stop_percent)
            stop = max(technical_stop, minimum_distance_stop)
            targets = self._calcular_alvos(entry_reference, stop, long=False)
            invalidation = stop
            prerequisites = [
                "aguardar fechamento do candle dentro ou abaixo da zona de supply",
                "confirmar rejeicao sem fechamento acima da borda externa da zona + ATR",
                "manter volume confirmando o movimento",
                "gatilho de entrada deve fechar no 5m com padrao e volume",
            ]
            cancel = ["fechamento acima do stop tecnico", "recuperacao do contexto de 4h/1h", "spread ou liquidez fora do filtro", "time stop: 4h sem atingir alvo 1 ou fechamento as 22h BRT"]

        entry_mid = (entry_low + entry_high) / Decimal("2")
        risk = max(abs(entry_mid - stop), Decimal("0.00000001"))
        reward = abs(targets[0] - entry_mid)
        rr = (reward / risk).quantize(Decimal("0.01"))
        dominant = "alta" if decision == AnalysisDecision.LONG_SETUP else "baixa"

        # Classify confidence
        confidence = self._classify_confidence(score, ind)
        trend_str = str(ind.get("trend_strength", "moderada"))
        momentum_str = str(ind.get("momentum", "estavel"))
        regime = str(ind.get("market_regime", "ranging"))
        narrative = self._generate_narrative(
            decision, price, trends, score, reasons, ind, confidence, trend_str, momentum_str, regime
        )
        key_levels = self._build_key_levels(ind, entry_low, entry_high, stop, targets)

        return MarketSignal(
            symbol=self.symbol,
            timestamp=timestamp,
            current_price=price,
            dominant_direction=dominant,
            timeframe_trends=trends,
            score=score,
            decision=decision,
            reasons=reasons,
            ideal_entry_region=(entry_low, entry_high),
            stop_loss=stop,
            target_1=targets[0],
            target_2=targets[1],
            target_3=targets[2],
            risk_reward=rr.quantize(Decimal("0.01")),
            invalidation_level=invalidation,
            prerequisites=prerequisites,
            cancel_conditions=cancel,
            confidence_level=confidence,
            trend_strength=trend_str,
            momentum=momentum_str,
            market_regime=regime,
            narrative=narrative,
            key_levels=key_levels,
            candle_patterns=ind.get("candle_patterns", []),
            divergences={
                "rsi": str(ind.get("rsi_divergence", "none")),
                "macd": str(ind.get("macd_divergence", "none")),
            },
            detailed_indicators=self._extract_detailed_indicators(ind),
        )

    def _calcular_alvos(self, entry_reference: Decimal, stop: Decimal, long: bool) -> Tuple[Decimal, Decimal, Decimal]:
        risk = max(abs(entry_reference - stop), Decimal("0.00000001"))
        multiples = (Decimal("1.0"), Decimal("1.5"), Decimal("2.0"))
        if long:
            return tuple(entry_reference + risk * multiple for multiple in multiples)
        return tuple(entry_reference - risk * multiple for multiple in multiples)

    @staticmethod
    def verificar_time_stop(opened_at, now, target_1_hit: bool, market_close_hour_brt: int = 22) -> Dict:
        elapsed_hours = (now - opened_at).total_seconds() / 3600
        if elapsed_hours >= 4 and not target_1_hit:
            return {"close": True, "reason": "TIME_STOP_4H_SEM_ALVO_1"}
        if getattr(now, "hour", None) is not None and now.hour >= market_close_hour_brt:
            return {"close": True, "reason": "FECHAMENTO_MERCADO_22H_BRT"}
        return {"close": False, "reason": ""}

    def _zone_as_decimal(self, zone: Dict | None, fallback_center: Decimal) -> Dict[str, Decimal]:
        if not zone:
            atr = fallback_center.copy_abs() * Decimal("0.01")
            return {
                "center": fallback_center,
                "lower": fallback_center - atr * Decimal("0.5"),
                "upper": fallback_center + atr * Decimal("0.5"),
                "break_price": fallback_center,
            }
        return {
            "center": Decimal(str(zone["center"])),
            "lower": Decimal(str(zone["lower"])),
            "upper": Decimal(str(zone["upper"])),
            "break_price": Decimal(str(zone["break_price"])),
        }

    def _classify_confidence(self, score: int, ind: Dict) -> str:
        """Classify signal confidence as baixa/media/alta/muito_alta."""
        adx = float(ind.get("adx", 20))
        vol_ratio = float(ind.get("volume_ratio", 1))
        if score >= 85 and adx >= 30 and vol_ratio >= 1.2:
            return "muito_alta"
        elif score >= 75 and adx >= 20:
            return "alta"
        elif score >= 65:
            return "media"
        return "baixa"

    def _generate_narrative(
        self,
        decision: AnalysisDecision,
        price: Decimal,
        trends: Dict[str, str],
        score: int,
        reasons: List[str],
        ind: Dict,
        confidence: str,
        trend_str: str,
        momentum_str: str,
        regime: str,
    ) -> str:
        """Generate analyst-style narrative text."""
        direction = "alta" if decision == AnalysisDecision.LONG_SETUP else "baixa"
        dir_label = "compra" if direction == "alta" else "venda"

        # Count aligned timeframes
        aligned = sum(1 for v in trends.values() if v == ("bullish" if direction == "alta" else "bearish"))
        total = len(trends)

        rsi = float(ind.get("rsi", 50))
        adx = float(ind.get("adx", 20))
        vol_ratio = float(ind.get("volume_ratio", 1))
        patterns = ind.get("candle_patterns", [])

        parts = [
            f"{self.symbol} apresenta configuracao de {dir_label} com score {score}/100 "
            f"e confianca {confidence.replace('_', ' ')}.",
        ]

        parts.append(
            f"A tendencia e {trend_str} com {aligned}/{total} timeframes alinhados para {direction} "
            f"e momentum {momentum_str}."
        )

        if regime == "trending":
            parts.append("O mercado esta em regime de tendencia.")
        elif regime == "breakout":
            parts.append("Rompimento detectado — alta probabilidade de continuacao.")
        elif regime == "volatile":
            parts.append("Atencao: mercado volatil, controle o tamanho da posicao.")
        else:
            parts.append("Mercado em consolidacao — aguardar rompimento para maior convicao.")

        if adx >= 30:
            parts.append(f"ADX em {adx:.0f} confirma forca direcional.")
        elif adx < 15:
            parts.append(f"ADX baixo ({adx:.0f}): tendencia fraca, cautela recomendada.")

        if vol_ratio >= 1.5:
            parts.append(f"Volume {vol_ratio:.1f}x acima da media — forte participacao.")
        elif vol_ratio < 0.7:
            parts.append(f"Volume abaixo da media ({vol_ratio:.1f}x) — pode faltar forca.")

        rsi_div = str(ind.get("rsi_divergence", "none"))
        if rsi_div != "none":
            parts.append(f"Divergencia {rsi_div} no RSI detectada.")

        if patterns:
            parts.append(f"Padroes de candle: {', '.join(p.replace('_', ' ') for p in patterns)}.")

        poc = ind.get("poc")
        poc_bias = ind.get("poc_bias")
        if poc:
            parts.append(f"POC 24h em {Decimal(str(poc)).quantize(Decimal('0.01'))}; vies pelo POC: {poc_bias}.")
        fib_nearest = ind.get("fib_nearest_level", "")
        fib_price = ind.get("fib_nearest_price")
        if fib_nearest and fib_price:
            parts.append(f"Preco proximo da zona de atracao Fibonacci {fib_nearest} ({Decimal(str(fib_price)).quantize(Decimal('0.01'))}).")

        return " ".join(parts)

    def _build_key_levels(self, ind: Dict, entry_low, entry_high, stop, targets) -> Dict:
        """Build key price action zones including POC and Fibonacci attraction zones."""
        levels = {
            "poc": str(ind.get("poc", "")),
            "vies_poc": str(ind.get("poc_bias", "")),
            "vwap": str(ind.get("vwap", "")),
            "zona_demanda": ind.get("nearest_demand_zone"),
            "zona_supply": ind.get("nearest_supply_zone"),
            "zonas_demanda": ind.get("demand_zones", []),
            "zonas_supply": ind.get("supply_zones", []),
            "zonas_atracao_fibonacci": ind.get("fib_attraction_zones", []),
        }
        return levels

    def _extract_detailed_indicators(self, ind: Dict) -> Dict:
        """Extract a serializable subset of indicators for the dashboard."""
        keys = [
            "rsi", "rsi_prev", "macd", "macd_signal", "macd_hist",
            "adx", "plus_di", "minus_di", "adx_interpretation",
            "stoch_rsi_k", "stoch_rsi_d", "stoch_rsi_signal",
            "obv_trend", "bb_upper", "bb_middle", "bb_lower", "bb_width", "bb_position",
            "atr", "volatility", "volume_ratio", "vwap",
            "trend_strength", "trend_strength_score", "momentum", "market_regime",
            "stoch_k", "stoch_d", "stoch_signal",
            "poc", "poc_bias", "fib_nearest_level", "fib_nearest_price",
        ]
        result = {}
        for key in keys:
            val = ind.get(key)
            if val is not None:
                result[key] = str(val) if not isinstance(val, (int, float, str, bool)) else val
        for key in ("nearest_demand_zone", "nearest_supply_zone", "demand_zones", "supply_zones", "fib_attraction_zones"):
            if key in ind:
                result[key] = ind[key]
        return result

    def _wait(
        self,
        price: Decimal,
        timestamp: str,
        trends: Dict[str, str],
        dominant: str,
        reasons: List[str],
        zone_alert: Dict | None = None,
    ) -> MarketSignal:
        setup_ind = self.analyses[self.timeframes["setup"]].indicators
        regime = str(setup_ind.get("market_regime", "ranging"))
        trend_str = str(setup_ind.get("trend_strength", "moderada"))
        momentum_str = str(setup_ind.get("momentum", "estavel"))
        narrative = (
            f"{self.symbol} sem configuracao valida no momento. "
            f"Regime: {regime}, tendencia: {trend_str}, momentum: {momentum_str}. "
            f"Motivos: {'; '.join(reasons)}. "
            f"Aguardar nova estrutura com confirmacao de tendencia e volume."
        )
        return MarketSignal(
            symbol=self.symbol,
            timestamp=timestamp,
            current_price=price,
            dominant_direction=dominant,
            timeframe_trends=trends,
            score=56 if reasons else 50,
            decision=AnalysisDecision.WAIT,
            reasons=reasons or ["mercado sem confirmacao objetiva"],
            ideal_entry_region=None,
            stop_loss=None,
            target_1=None,
            target_2=None,
            target_3=None,
            risk_reward=Decimal("0"),
            invalidation_level=None,
            prerequisites=[
                "aguardar fechamento fora das bordas das zonas confirmadas por ATR e volume",
            ],
            cancel_conditions=["novo conflito entre periodos", "volume abaixo do minimo", "spread acima do filtro"],
            confidence_level="baixa",
            trend_strength=trend_str,
            momentum=momentum_str,
            market_regime=regime,
            narrative=narrative,
            key_levels=self._build_key_levels(setup_ind, None, None, None, None),
            candle_patterns=setup_ind.get("candle_patterns", []),
            divergences={
                "rsi": str(setup_ind.get("rsi_divergence", "none")),
                "macd": str(setup_ind.get("macd_divergence", "none")),
            },
            detailed_indicators=self._extract_detailed_indicators(setup_ind),
            alert_type=zone_alert["type"] if zone_alert else "",
            alert_message=zone_alert["message"] if zone_alert else "",
            alert_direction=zone_alert["direction"] if zone_alert else "",
        )

    def _invalidated(self, price: Decimal, timestamp: str, trends: Dict[str, str], dominant: str, reasons: List[str]) -> MarketSignal:
        setup_ind = self.analyses[self.timeframes["setup"]].indicators
        return MarketSignal(
            symbol=self.symbol,
            timestamp=timestamp,
            current_price=price,
            dominant_direction=dominant,
            timeframe_trends=trends,
            score=0,
            decision=AnalysisDecision.INVALIDATED,
            reasons=reasons,
            ideal_entry_region=None,
            stop_loss=None,
            target_1=None,
            target_2=None,
            target_3=None,
            risk_reward=Decimal("0"),
            invalidation_level=None,
            prerequisites=["aguardar nova estrutura limpa"],
            cancel_conditions=["sinal ja invalidado"],
            confidence_level="baixa",
            trend_strength=str(setup_ind.get("trend_strength", "fraca")),
            momentum=str(setup_ind.get("momentum", "estavel")),
            market_regime=str(setup_ind.get("market_regime", "ranging")),
            narrative=f"{self.symbol} sinal invalidado: {'; '.join(reasons)}. Aguardar nova estrutura.",
            candle_patterns=setup_ind.get("candle_patterns", []),
            divergences={
                "rsi": str(setup_ind.get("rsi_divergence", "none")),
                "macd": str(setup_ind.get("macd_divergence", "none")),
            },
            detailed_indicators=self._extract_detailed_indicators(setup_ind),
        )


AdaptiveStrategy = MarketAnalyzer
Signal = AnalysisDecision

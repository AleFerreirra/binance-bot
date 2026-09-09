import argparse
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List

import numpy as np
import pandas as pd

from config import Config
from strategy import AnalysisDecision, MarketAnalyzer


@dataclass
class BacktestTrade:
    entry_time: str
    exit_time: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl: Decimal


class Backtester:
    def __init__(self, data: pd.DataFrame, config=Config,
                 initial_capital: Decimal = Decimal("1000"),
                 commission: Decimal = None,
                 spread: Decimal = Decimal("0.001"),
                 slippage: Decimal = Decimal("0.001")):
        self.data = data.copy()
        self.config = config
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission = commission if commission is not None else config.COMMISSION_RATE
        self.spread = spread
        self.slippage = slippage
        self.position_qty = Decimal("0")
        self.entry_price = Decimal("0")
        self.entry_time = ""
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[Decimal] = []

    def run(self) -> Dict:
        min_window = max(self.config.KLINE_LIMIT, self.config.MA_TREND + 5)
        for idx in range(min_window, len(self.data)):
            window = self.data.iloc[:idx].copy()
            close = Decimal(str(window["close"].iloc[-1]))
            timestamp = str(window["timestamp"].iloc[-1])
            mark_equity = self.cash + self.position_qty * close
            self.equity_curve.append(mark_equity)
            analyzer = MarketAnalyzer(
                getattr(self.config, "SYMBOL", "BACKTEST"),
                {
                    getattr(self.config, "CONTEXT_TIMEFRAME", "4h"): window,
                    getattr(self.config, "CONFIRMATION_TIMEFRAME", "1h"): window,
                    getattr(self.config, "SETUP_TIMEFRAME", "15m"): window,
                    getattr(self.config, "REFINEMENT_TIMEFRAME", "5m"): window,
                },
                self.config,
                spread_percent=self.spread,
            )
            signal = analyzer.generate_signal()
            if self.position_qty == 0 and signal.decision == AnalysisDecision.LONG_SETUP:
                self._open(timestamp, close)
            elif self.position_qty > 0 and signal.decision in {AnalysisDecision.SHORT_SETUP, AnalysisDecision.INVALIDATED}:
                self._close(timestamp, close)
            elif self.position_qty > 0:
                stop = self.entry_price * (Decimal("1") - self.config.STOP_LOSS_PERCENT)
                take = self.entry_price * (Decimal("1") + self.config.TAKE_PROFIT_PERCENT)
                if close <= stop or close >= take:
                    self._close(timestamp, close)
        if self.position_qty > 0:
            last = self.data.iloc[-1]
            self._close(str(last["timestamp"]), Decimal(str(last["close"])))
        return self.metrics()

    def _buy_price(self, close: Decimal) -> Decimal:
        return close * (Decimal("1") + self.spread / Decimal("2") + self.slippage)

    def _sell_price(self, close: Decimal) -> Decimal:
        return close * (Decimal("1") - self.spread / Decimal("2") - self.slippage)

    def _open(self, timestamp: str, close: Decimal) -> None:
        entry = self._buy_price(close)
        risk_per_unit = entry * self.config.STOP_LOSS_PERCENT
        risk_budget = self.cash * self.config.RISK_PER_TRADE
        qty_by_risk = risk_budget / risk_per_unit
        qty_by_exposure = (self.cash * self.config.MAX_POSITION_SIZE) / entry
        qty = min(qty_by_risk, qty_by_exposure)
        notional = qty * entry
        if notional < self.config.MIN_ORDER_USDT:
            return
        fee = notional * self.commission
        self.cash -= notional + fee
        self.position_qty = qty
        self.entry_price = entry
        self.entry_time = timestamp

    def _close(self, timestamp: str, close: Decimal) -> None:
        exit_price = self._sell_price(close)
        notional = self.position_qty * exit_price
        fee = notional * self.commission
        pnl = (exit_price - self.entry_price) * self.position_qty - fee
        self.cash += notional - fee
        self.trades.append(BacktestTrade(self.entry_time, timestamp, self.entry_price, exit_price, self.position_qty, pnl))
        self.position_qty = Decimal("0")
        self.entry_price = Decimal("0")

    def metrics(self) -> Dict:
        equity = np.array([float(x) for x in self.equity_curve], dtype=float)
        returns = pd.Series(equity).pct_change().dropna() if len(equity) else pd.Series(dtype=float)
        peak = np.maximum.accumulate(equity) if len(equity) else np.array([])
        drawdowns = (equity - peak) / peak if len(equity) else np.array([0])
        max_drawdown = float(abs(np.nanmin(drawdowns))) if len(drawdowns) else 0.0
        pnls = [float(t.pnl) for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        downside = returns[returns < 0]
        sharpe = float((returns.mean() / returns.std()) * np.sqrt(365)) if len(returns) > 1 and returns.std() else 0.0
        sortino = float((returns.mean() / downside.std()) * np.sqrt(365)) if len(downside) > 1 and downside.std() else 0.0
        total_return = (float(self.cash) - float(self.initial_capital)) / float(self.initial_capital)
        calmar = total_return / max_drawdown if max_drawdown else 0.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss else float("inf") if gross_profit else 0.0
        return {
            "initial_capital": float(self.initial_capital),
            "final_equity": float(self.cash),
            "total_return": total_return,
            "max_drawdown": max_drawdown,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "profit_factor": profit_factor,
            "win_rate": len(wins) / len(pnls) if pnls else 0.0,
            "expectancy": float(np.mean(pnls)) if pnls else 0.0,
            "trades": len(self.trades),
            "equity_curve": [float(x) for x in self.equity_curve],
        }


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "timestamp" not in df.columns:
        raise ValueError("CSV must include timestamp column")
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("--capital", default="1000")
    args = parser.parse_args()
    metrics = Backtester(load_csv(args.csv), initial_capital=Decimal(args.capital)).run()
    print(pd.Series(metrics).drop(labels=["equity_curve"]).to_string())


if __name__ == "__main__":
    main()

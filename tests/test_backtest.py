from decimal import Decimal

import pandas as pd

from backtest import Backtester
from tests.test_strategy import DummyConfig, candles


def test_backtest_returns_required_metrics():
    data = candles(320)
    result = Backtester(
        data,
        config=DummyConfig,
        initial_capital=Decimal("1000"),
        spread=Decimal("0.001"),
        slippage=Decimal("0.001"),
    ).run()
    for key in [
        "equity_curve", "max_drawdown", "sharpe", "sortino", "calmar",
        "profit_factor", "win_rate", "expectancy",
    ]:
        assert key in result
    assert isinstance(result["equity_curve"], list)

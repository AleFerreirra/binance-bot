from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from database import Database
from risk_manager import RiskManager


class DummyConfig:
    KILL_SWITCH_FILE = "__missing_kill_switch__"
    MAX_DAILY_TRADES = 2
    MAX_DAILY_LOSS = Decimal("0.03")
    MAX_WEEKLY_LOSS = Decimal("0.06")
    MAX_MONTHLY_LOSS = Decimal("0.10")
    MAX_DRAWDOWN = Decimal("0.12")
    MAX_TOTAL_EXPOSURE = Decimal("0.20")
    RISK_PER_TRADE = Decimal("0.01")
    MAX_POSITION_SIZE = Decimal("0.05")
    MIN_ORDER_USDT = Decimal("10")
    STOP_LOSS_PERCENT = Decimal("0.02")


def make_test_db() -> Database:
    root = Path.cwd() / ".test_artifacts"
    root.mkdir(exist_ok=True)
    return Database(str(root / f"bot_{uuid4().hex}.db"))


def test_position_size_uses_minimum_of_risk_and_exposure():
    db = make_test_db()
    risk = RiskManager(DummyConfig, db)
    qty, notional = risk.position_size(Decimal("1000"), Decimal("100"), Decimal("98"))
    assert qty == Decimal("0.5")
    assert notional == Decimal("50.0")


def test_exposure_limit_blocks_new_trade():
    db = make_test_db()
    risk = RiskManager(DummyConfig, db)
    decision = risk.can_open_trade(Decimal("1000"), Decimal("250"))
    assert not decision.allowed
    assert "exposicao" in decision.reason


def test_minimum_balance_for_trade_explains_small_accounts():
    db = make_test_db()
    risk = RiskManager(DummyConfig, db)
    assert risk.minimum_balance_for_trade() == Decimal("200")

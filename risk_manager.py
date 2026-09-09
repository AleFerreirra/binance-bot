import logging
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Tuple

from database import Database
from messages import pt_reason


logger = logging.getLogger(__name__)


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(self, config, db: Database, notifier=None):
        self.config = config
        self.db = db
        self.notifier = notifier

    def kill_switch_active(self) -> bool:
        return os.path.exists(self.config.KILL_SWITCH_FILE)

    def check_circuit_breakers(self, balance: Decimal) -> RiskDecision:
        if self.kill_switch_active():
            return RiskDecision(False, pt_reason("kill switch file is present"))
        today = date.today().isoformat()
        metrics = self.db.get_or_create_daily_metrics(today, balance)
        daily_pnl = Decimal(str(metrics.get("total_pnl") or "0"))
        weekly_pnl = self.db.get_period_pnl(7)
        monthly_pnl = self.db.get_period_pnl(30)
        peak = self.db.get_peak_balance()
        drawdown = Decimal("0")
        if peak > 0 and balance < peak:
            drawdown = (peak - balance) / peak

        checks = [
            (daily_pnl <= -(balance * self.config.MAX_DAILY_LOSS), pt_reason("daily loss limit reached")),
            (weekly_pnl <= -(balance * self.config.MAX_WEEKLY_LOSS), pt_reason("weekly loss limit reached")),
            (monthly_pnl <= -(balance * self.config.MAX_MONTHLY_LOSS), pt_reason("monthly loss limit reached")),
            (drawdown >= self.config.MAX_DRAWDOWN, pt_reason("max drawdown reached")),
        ]
        for failed, reason in checks:
            if failed:
                logger.critical("[RISCO] circuit breaker acionado: %s", reason)
                if self.notifier:
                    self.notifier.circuit_breaker(reason)
                return RiskDecision(False, reason)
        return RiskDecision(True)

    def can_open_trade(self, balance: Decimal, current_exposure: Decimal) -> RiskDecision:
        breaker = self.check_circuit_breakers(balance)
        if not breaker.allowed:
            return breaker
        today = date.today().isoformat()
        if self.db.get_daily_trade_count(today) >= self.config.MAX_DAILY_TRADES:
            return RiskDecision(False, pt_reason("max daily trades reached"))
        if balance <= 0:
            return RiskDecision(False, pt_reason("no quote balance"))
        exposure_ratio = current_exposure / balance if balance > 0 else Decimal("1")
        if exposure_ratio >= self.config.MAX_TOTAL_EXPOSURE:
            return RiskDecision(False, pt_reason("max exposure reached"))
        return RiskDecision(True)

    def minimum_balance_for_trade(self) -> Decimal:
        """Minimum quote balance needed to satisfy min order under configured risk caps."""
        risk_notional_fraction = self.config.RISK_PER_TRADE / self.config.STOP_LOSS_PERCENT
        usable_fraction = min(self.config.MAX_POSITION_SIZE, risk_notional_fraction)
        if usable_fraction <= 0:
            return Decimal("Infinity")
        return self.config.MIN_ORDER_USDT / usable_fraction

    def position_size(self, balance: Decimal, entry_price: Decimal,
                      stop_loss: Decimal) -> Tuple[Decimal, Decimal]:
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            raise ValueError("stop loss deve ser diferente do preco de entrada")
        risk_budget = balance * self.config.RISK_PER_TRADE
        qty_by_risk = risk_budget / risk_per_unit
        qty_by_exposure = (balance * self.config.MAX_POSITION_SIZE) / entry_price
        quantity = min(qty_by_risk, qty_by_exposure)
        notional = quantity * entry_price
        if notional < self.config.MIN_ORDER_USDT:
            min_balance = self.minimum_balance_for_trade()
            raise ValueError(
                f"valor calculado da posicao ({notional:.8f} USDT) ficou abaixo "
                f"do minimo configurado ({self.config.MIN_ORDER_USDT} USDT). "
                f"Com os parametros atuais, saldo recomendado para operar: "
                f"{min_balance:.2f} USDT"
            )
        return quantity, notional

    def record_daily_mark(self, balance: Decimal) -> None:
        today = date.today().isoformat()
        metrics = self.db.get_or_create_daily_metrics(today, balance)
        start = Decimal(str(metrics["starting_balance"]))
        pnl = balance - start
        peak = max(self.db.get_peak_balance(), start, balance)
        drawdown = (peak - balance) / peak if peak > 0 and balance < peak else Decimal("0")
        self.db.update_daily_metrics(
            today,
            ending_balance=balance,
            total_pnl=pnl,
            max_drawdown=drawdown,
        )

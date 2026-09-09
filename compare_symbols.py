import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Dict, List

import pandas as pd
import requests

from backtest import Backtester
from config import Config


BINANCE_REST = "https://api.binance.com"


@dataclass
class SymbolReport:
    symbol: str
    spread_percent: float
    avg_quote_volume: float
    final_equity: float
    total_return: float
    max_drawdown: float
    sharpe: float
    sortino: float
    calmar: float
    profit_factor: float
    win_rate: float
    expectancy: float
    trades: int
    score: float


def quote_asset(symbol: str) -> str:
    if symbol.endswith("USDT"):
        return "USDT"
    raise ValueError(f"simbolo ainda nao suportado pelo comparador: {symbol}")


def base_asset(symbol: str) -> str:
    return symbol.replace(quote_asset(symbol), "")


def make_config(symbol: str):
    cfg = SimpleNamespace(**{
        name: value
        for name, value in Config.__dict__.items()
        if name.isupper()
    })
    cfg.SYMBOL = symbol
    cfg.BASE_ASSET = base_asset(symbol)
    cfg.QUOTE_ASSET = quote_asset(symbol)
    return cfg


def get_json(path: str, params: Dict) -> Dict | List:
    response = requests.get(f"{BINANCE_REST}{path}", params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    raw = get_json("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    df = pd.DataFrame(raw, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume", "quote_asset_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    now = pd.Timestamp.now(tz="UTC")
    return df[df["close_time"] <= now].dropna().reset_index(drop=True)


def fetch_spread(symbol: str) -> Decimal:
    book = get_json("/api/v3/ticker/bookTicker", {"symbol": symbol})
    bid = Decimal(book["bidPrice"])
    ask = Decimal(book["askPrice"])
    mid = (bid + ask) / Decimal("2")
    return (ask - bid) / mid if mid > 0 else Decimal("1")


def score_report(metrics: Dict, spread_percent: Decimal, avg_quote_volume: float) -> float:
    liquidity_score = min(avg_quote_volume / 10_000_000, 1.0)
    spread_penalty = min(float(spread_percent) * 1000, 1.0)
    drawdown_penalty = min(metrics["max_drawdown"], 1.0)
    return (
        metrics["total_return"] * 2.0
        + metrics["sharpe"] * 0.5
        + metrics["profit_factor"] * 0.1
        + liquidity_score * 0.5
        - drawdown_penalty
        - spread_penalty
    )


def analyze_symbol(symbol: str, interval: str, limit: int, capital: Decimal) -> SymbolReport:
    cfg = make_config(symbol)
    data = fetch_klines(symbol, interval, limit)
    spread = fetch_spread(symbol)
    avg_quote_volume = float(data["quote_asset_volume"].tail(100).mean())
    metrics = Backtester(
        data,
        config=cfg,
        initial_capital=capital,
        spread=spread,
        slippage=Config.MAX_SLIPPAGE_PERCENT,
    ).run()
    return SymbolReport(
        symbol=symbol,
        spread_percent=float(spread),
        avg_quote_volume=avg_quote_volume,
        final_equity=metrics["final_equity"],
        total_return=metrics["total_return"],
        max_drawdown=metrics["max_drawdown"],
        sharpe=metrics["sharpe"],
        sortino=metrics["sortino"],
        calmar=metrics["calmar"],
        profit_factor=metrics["profit_factor"],
        win_rate=metrics["win_rate"],
        expectancy=metrics["expectancy"],
        trades=metrics["trades"],
        score=score_report(metrics, spread, avg_quote_volume),
    )


def print_table(reports: List[SymbolReport]) -> None:
    rows = sorted(reports, key=lambda item: item.score, reverse=True)
    print("\nComparacao de simbolos pela estrategia atual")
    print("-" * 118)
    print(
        f"{'Simbolo':<10} {'Score':>8} {'Retorno':>10} {'DD max':>10} "
        f"{'Sharpe':>8} {'PF':>8} {'Win%':>8} {'Trades':>8} {'Spread':>10} {'Vol USDT':>14}"
    )
    print("-" * 118)
    for item in rows:
        print(
            f"{item.symbol:<10} {item.score:>8.3f} {item.total_return:>9.2%} "
            f"{item.max_drawdown:>9.2%} {item.sharpe:>8.2f} "
            f"{item.profit_factor:>8.2f} {item.win_rate:>7.1%} "
            f"{item.trades:>8} {item.spread_percent:>9.4%} "
            f"{item.avg_quote_volume:>14,.0f}"
        )
    print("-" * 118)
    print(f"Melhor candidato pelo score: {rows[0].symbol}")
    print("Observacao: score nao e garantia de lucro; use como filtro para teste controlado.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compara BTCUSDT, ETHUSDT e outros simbolos pela estrategia atual.")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "BNBUSDT"])
    parser.add_argument("--interval", default=Config.TIMEFRAME)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--capital", default="1000")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    reports = [
        analyze_symbol(symbol.upper(), args.interval, args.limit, Decimal(args.capital))
        for symbol in args.symbols
    ]
    if args.json:
        print(json.dumps([item.__dict__ for item in reports], indent=2, default=str))
    else:
        print_table(reports)


if __name__ == "__main__":
    main()

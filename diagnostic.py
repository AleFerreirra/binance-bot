from config import Config
from binance_client import BinanceClient


def run_diagnostics():
    """Run a read-only public market-data diagnostic."""
    config = Config()
    config.validate_safety()
    client = BinanceClient(config.API_KEY, config.API_SECRET, config)

    print("\n" + "=" * 60)
    print("BINANCE PUBLIC MARKET DATA DIAGNOSTIC")
    print("=" * 60)
    print(f"Mode: {config.TRADING_MODE}")
    print(f"Symbols: {', '.join(config.SYMBOLS)}")
    print("No account, margin, futures, leverage, order, or cancel endpoint is used.")

    for symbol in config.SYMBOLS:
        price = client.get_current_price(symbol)
        spread = client.get_spread_percent(symbol)
        candles = client.get_klines(symbol, config.SETUP_TIMEFRAME, limit=10)
        print(f"\n{symbol}")
        print(f"  Price: {price}")
        print(f"  Spread: {spread:.6%}")
        print(f"  Closed candles fetched: {len(candles)}")

    print("\n[OK] Public data access is working.")
    print("=" * 60)


if __name__ == "__main__":
    run_diagnostics()

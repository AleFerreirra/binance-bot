from config import Config


def main() -> None:
    config = Config()
    config.validate_safety()
    print("Analysis-only safety limits")
    print("=" * 40)
    print(f"TRADING_MODE={config.TRADING_MODE}")
    print(f"SYMBOLS={','.join(config.SYMBOLS)}")
    print(f"Timeframes={config.CONTEXT_TIMEFRAME},{config.CONFIRMATION_TIMEFRAME},{config.SETUP_TIMEFRAME},{config.REFINEMENT_TIMEFRAME}")
    print(f"Max spread={config.MAX_SPREAD_FILTER}")
    print(f"Min volume ratio={config.MIN_VOLUME_RATIO}")
    print(f"Min quote volume={config.MIN_QUOTE_VOLUME_USDT}")
    print(f"Min risk/reward={config.MIN_RISK_REWARD}")
    print("Real execution endpoints are not part of the application flow.")


if __name__ == "__main__":
    main()

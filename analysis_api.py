import json
import os
import threading
import traceback
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from binance_client import BinanceClient
from config import Config
from strategy import MarketAnalyzer


ROOT = Path(__file__).resolve().parent
DASHBOARD_DIR = ROOT / "dashboard"
LOCAL_HOST = "127.0.0.1"
PRODUCTION_HOST = "0.0.0.0"
ALLOWED_TIMEFRAMES = {"5m", "15m", "1h", "4h"}


def is_production() -> bool:
    return os.getenv("RENDER", "").lower() == "true" or os.getenv("APP_ENV", "").lower() == "production"


def runtime_host() -> str:
    return PRODUCTION_HOST if is_production() else LOCAL_HOST


def runtime_port(config: Config) -> int:
    return int(os.getenv("PORT", str(config.DASHBOARD_PORT)))


def selected_config(config: Config, timeframe: str) -> Config:
    """Validate chart timeframe while keeping day-trade setup on 15m and trigger on 5m."""
    if timeframe not in ALLOWED_TIMEFRAMES:
        raise ValueError(f"timeframe invalido: {timeframe}")
    config.SETUP_TIMEFRAME = "15m"
    config.REFINEMENT_TIMEFRAME = "5m"
    return config


class AnalysisHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in {"/health", "/healthz", "/api/health"}:
            self.handle_health()
            return
        if parsed.path == "/api/signal":
            self.handle_signal(parsed.query)
            return
        if parsed.path == "/api/candles":
            self.handle_candles(parsed.query)
            return
        if parsed.path == "/api/analysis":
            self.handle_analysis(parsed.query)
            return
        if parsed.path == "/api/multi":
            self.handle_multi(parsed.query)
            return
        if parsed.path == "/api/market-overview":
            self.handle_market_overview()
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def handle_health(self):
        self.send_json({
            "status": "ok",
            "mode": Config.TRADING_MODE,
            "service": "binance-bot-dashboard",
        })

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def handle_signal(self, query):
        try:
            config = Config()
            config.validate_safety()
            params = parse_qs(query)
            symbol = params.get("symbol", [config.SYMBOLS[0]])[0].upper()
            chart_timeframe = params.get("timeframe", [config.SETUP_TIMEFRAME])[0]
            config = selected_config(config, chart_timeframe)
            setup_timeframe = config.SETUP_TIMEFRAME
            timeframes = {
                config.CONTEXT_TIMEFRAME,
                config.CONFIRMATION_TIMEFRAME,
                setup_timeframe,
                chart_timeframe,
                config.REFINEMENT_TIMEFRAME,
            }
            client = BinanceClient(config.API_KEY, config.API_SECRET, config)
            candles = {
                timeframe: client.get_klines(symbol, timeframe, config.KLINE_LIMIT, closed_only=True)
                for timeframe in timeframes
            }
            spread = client.get_spread_percent(symbol)
            signal = MarketAnalyzer(symbol, candles, config, spread_percent=spread).generate_signal()
            self.send_json(signal.as_dict())
        except Exception as exc:
            self.send_json({"error": str(exc), "trace": traceback.format_exc()}, status=500)

    def handle_candles(self, query):
        try:
            config = Config()
            config.validate_safety()
            params = parse_qs(query)
            symbol = params.get("symbol", [config.SYMBOLS[0]])[0].upper()
            interval = params.get("interval", [config.SETUP_TIMEFRAME])[0]
            limit = int(params.get("limit", [config.KLINE_LIMIT])[0])
            client = BinanceClient(config.API_KEY, config.API_SECRET, config)
            df = client.get_klines(symbol, interval, min(limit, 500), closed_only=True)
            candles = [
                {
                    "time": int(row["timestamp"].timestamp()),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "closeTime": int(row["close_time"].timestamp() * 1000),
                }
                for _, row in df.iterrows()
            ]
            self.send_json({"symbol": symbol, "interval": interval, "candles": candles})
        except Exception as exc:
            self.send_json({"error": str(exc), "trace": traceback.format_exc()}, status=500)

    def handle_analysis(self, query):
        """Return detailed indicator data for a single symbol."""
        try:
            config = Config()
            config.validate_safety()
            params = parse_qs(query)
            symbol = params.get("symbol", [config.SYMBOLS[0]])[0].upper()
            chart_timeframe = params.get("timeframe", [config.SETUP_TIMEFRAME])[0]
            config = selected_config(config, chart_timeframe)
            setup_timeframe = config.SETUP_TIMEFRAME
            timeframes = {
                config.CONTEXT_TIMEFRAME,
                config.CONFIRMATION_TIMEFRAME,
                setup_timeframe,
                chart_timeframe,
                config.REFINEMENT_TIMEFRAME,
            }
            client = BinanceClient(config.API_KEY, config.API_SECRET, config)
            candles = {
                timeframe: client.get_klines(symbol, timeframe, config.KLINE_LIMIT, closed_only=True)
                for timeframe in timeframes
            }
            spread = client.get_spread_percent(symbol)
            analyzer = MarketAnalyzer(symbol, candles, config, spread_percent=spread)
            signal = analyzer.generate_signal()
            # Build per-timeframe indicator summary
            tf_data = {}
            for tf, analysis in analyzer.analyses.items():
                ind = analysis.indicators
                tf_data[tf] = {
                    "trend": analysis.trend.value,
                    "structure": analysis.structure,
                    "rsi": ind.get("rsi"),
                    "macd_hist": ind.get("macd_hist"),
                    "adx": ind.get("adx"),
                    "volume_ratio": ind.get("volume_ratio"),
                    "trend_strength": ind.get("trend_strength"),
                    "momentum": ind.get("momentum"),
                    "market_regime": ind.get("market_regime"),
                }
            payload = {
                **signal.as_dict(),
                "timeframe_indicators": tf_data,
            }
            self.send_json(payload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_multi(self, query):
        """Return signals for multiple symbols at once."""
        try:
            config = Config()
            config.validate_safety()
            params = parse_qs(query)
            raw_symbols = params.get("symbols", [",".join(config.WATCHLIST_SYMBOLS)])[0]
            symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
            chart_timeframe = params.get("timeframe", [config.SETUP_TIMEFRAME])[0]
            config = selected_config(config, chart_timeframe)
            setup_timeframe = config.SETUP_TIMEFRAME
            timeframes = {
                config.CONTEXT_TIMEFRAME,
                config.CONFIRMATION_TIMEFRAME,
                setup_timeframe,
                chart_timeframe,
                config.REFINEMENT_TIMEFRAME,
            }
            client = BinanceClient(config.API_KEY, config.API_SECRET, config)
            results = []
            for symbol in symbols:
                try:
                    candles = {
                        tf: client.get_klines(symbol, tf, config.KLINE_LIMIT, closed_only=True)
                        for tf in timeframes
                    }
                    spread = client.get_spread_percent(symbol)
                    signal = MarketAnalyzer(symbol, candles, config, spread_percent=spread).generate_signal()
                    results.append(signal.as_dict())
                except Exception as exc:
                    results.append({"ativo": symbol, "error": str(exc)})
            self.send_json({"signals": results})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_market_overview(self):
        """Return ticker data for all watchlist symbols."""
        try:
            config = Config()
            config.validate_safety()
            client = BinanceClient(config.API_KEY, config.API_SECRET, config)
            tickers = []
            for symbol in config.WATCHLIST_SYMBOLS:
                try:
                    price = client.get_current_price(symbol)
                    tickers.append({
                        "symbol": symbol,
                        "price": str(price),
                    })
                except Exception:
                    tickers.append({"symbol": symbol, "price": None})
            self.send_json({"tickers": tickers})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def dashboard_url(config: Config) -> str:
    return f"http://{LOCAL_HOST}:{runtime_port(config)}"


def print_dashboard_routes(config: Config) -> None:
    host = runtime_host()
    port = runtime_port(config)
    public_host = os.getenv("RENDER_EXTERNAL_URL", f"http://{LOCAL_HOST}:{port}")
    print(f"Dashboard read-only em {public_host}")
    print(f"API local de analise em http://{host}:{port}/api/signal?symbol=BTCUSDT&timeframe=15m")
    print(f"Candles publicos em http://{host}:{port}/api/candles?symbol=BTCUSDT&interval=15m")
    print(f"Multi-pair em http://{host}:{port}/api/multi")
    print(f"Market overview em http://{host}:{port}/api/market-overview")


def open_dashboard(config: Config) -> None:
    webbrowser.open(dashboard_url(config), new=2)


def start_dashboard_server(config: Config | None = None, open_browser: bool = True) -> ThreadingHTTPServer | None:
    config = config or Config()
    host = runtime_host()
    port = runtime_port(config)
    try:
        server = ThreadingHTTPServer((host, port), AnalysisHandler)
    except OSError:
        if open_browser:
            open_dashboard(config)
        print(f"Dashboard já parece estar em uso em {dashboard_url(config)}")
        return None

    thread = threading.Thread(target=server.serve_forever, name="dashboard-api", daemon=True)
    thread.start()
    print_dashboard_routes(config)
    if open_browser:
        open_dashboard(config)
    return server


def main():
    config = Config()
    server = ThreadingHTTPServer((runtime_host(), runtime_port(config)), AnalysisHandler)
    print_dashboard_routes(config)
    if not is_production():
        open_dashboard(config)
    server.serve_forever()


if __name__ == "__main__":
    main()

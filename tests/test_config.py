import pytest

from config import Config


def test_analysis_only_mode_is_allowed(monkeypatch):
    monkeypatch.setattr(Config, "TRADING_MODE", "analysis_only")
    Config.validate_safety()


def test_real_execution_mode_is_blocked(monkeypatch):
    monkeypatch.setattr(Config, "TRADING_MODE", "live")
    with pytest.raises(ValueError, match="Real order execution is blocked"):
        Config.validate_safety()

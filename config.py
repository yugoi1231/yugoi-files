"""Configuration for T8 trading bot."""
import os

USE_TESTNET = bool(int(os.getenv("USE_TESTNET", "1")))
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")

MODE = os.getenv("MODE", "SWING")  # SWING or SCALP
AUTO_TRADE = bool(int(os.getenv("AUTO_TRADE", "0")))
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.005"))  # 0.5%
LEVERAGE = int(os.getenv("LEVERAGE", "5"))

# Volume multiplier for volume filter
VOLUME_MULTIPLIER = 1.5 if MODE.upper() == "SWING" else 1.3
UNIVERSE_LIMIT = int(os.getenv("UNIVERSE_LIMIT", "20"))

STATE_FILE = os.getenv("STATE_FILE", "state.json")

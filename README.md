# T8 Trading Bot

T8 is a modular futures trading system for Binance USDT perpetual contracts. It scans the most active symbols,
calculates multiple technical strategies on several timeframes and executes trades only when a consensus of
strategies aligns with higher timeframe trends. Risk is managed through ATR based stops and fixed fractional
position sizing.

## Features
- Universe scanning of top USDT futures markets
- Multi‑indicator consensus (EMA, Bollinger Bands, VWAP, RSI, MACD, ATR)
- High‑timeframe trend alignment (1h/4h)
- Volume confirmation filters
- ATR‑based dynamic stop loss and trailing take‑profit
- Risk based position sizing
- Swing and scalp modes
- Optional auto trading or signal only mode
- Discord webhook notifications
- Binance testnet support and path check script

## Quick start (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
setx BINANCE_API_KEY "your_key"
setx BINANCE_API_SECRET "your_secret"
setx DISCORD_WEBHOOK "https://discord.com/api/webhooks/..."
python pathcheck.py  # optional environment test
python t8_bot.py     # run the bot
```

## Configuration
Most settings can be adjusted via environment variables in `config.py`:
- `USE_TESTNET` (1 or 0)
- `MODE` (`SWING` or `SCALP`)
- `AUTO_TRADE` (1 to place orders)
- `RISK_PER_TRADE` (fraction of equity, default 0.005)

State such as equity and open positions is stored in `state.json` and
reloaded on startup.
```

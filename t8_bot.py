"""Implementation of the T8 trading bot.

The bot scans Binance USDT perpetual futures, calculates a set of
technical indicators on multiple timeframes and generates trade signals
only when several strategies agree with the higher timeframe trend.
Risk is managed through ATR based stops and fixed fractional sizing.
"""
from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
from binance.client import Client
from binance.enums import *
from binance.streams import BinanceSocketManager
from ta.volatility import BollingerBands
from ta.trend import EMAIndicator, MACD, VWAPIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

import config
import requests


@dataclass
class Signal:
    symbol: str
    side: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    strategies: List[str]
    score: float


class T8Bot:
    def __init__(self) -> None:
        self.client = Client(config.API_KEY, config.API_SECRET, testnet=config.USE_TESTNET)
        self.state = self._load_state()
        self.mode = config.MODE.upper()
        self.volume_multiplier = config.VOLUME_MULTIPLIER
        self.universe: List[str] = []

    # ----- State management -------------------------------------------------
    def _load_state(self) -> Dict:
        try:
            with open(config.STATE_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"equity": 0.0, "positions": {}, "subscribed": []}

    def _save_state(self) -> None:
        with open(config.STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2)

    # ----- Universe scanning -------------------------------------------------
    def scan_universe(self) -> None:
        """Scan Binance futures markets and select top symbols."""
        tickers = self.client.futures_ticker()
        df = pd.DataFrame(tickers)
        df = df[df["symbol"].str.endswith("USDT")]
        df["quoteVolume"] = df["quoteVolume"].astype(float)
        df["priceChangePercent"] = df["priceChangePercent"].astype(float)
        df = df.sort_values("quoteVolume", ascending=False).head(config.UNIVERSE_LIMIT)
        self.universe = df["symbol"].tolist()

    # ----- Indicator calculations ------------------------------------------
    def fetch_klines(self, symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
        klines = self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_base", "taker_quote", "ignore"])
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ema20"] = EMAIndicator(df["close"], window=20).ema_indicator()
        df["ema50"] = EMAIndicator(df["close"], window=50).ema_indicator()
        df["ema200"] = EMAIndicator(df["close"], window=200).ema_indicator()
        bb = BollingerBands(df["close"], window=20, window_dev=2)
        df["bb_high"] = bb.bollinger_hband()
        df["bb_low"] = bb.bollinger_lband()
        df["bb_width"] = (df["bb_high"] - df["bb_low"]) / df["close"]
        df["vwap"] = VWAPIndicator(df["high"], df["low"], df["close"], df["volume"], window=20).vwap()
        df["rsi"] = RSIIndicator(df["close"], window=14).rsi()
        macd = MACD(df["close"])
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        atr = AverageTrueRange(df["high"], df["low"], df["close"], window=14)
        df["atr"] = atr.average_true_range()
        df.dropna(inplace=True)
        return df

    # ----- Strategy evaluation ---------------------------------------------
    def ema_cross(self, df: pd.DataFrame) -> bool:
        return df["ema20"].iloc[-1] > df["ema50"].iloc[-1] > df["ema200"].iloc[-1]

    def breakout_with_volume(self, df: pd.DataFrame) -> bool:
        high = df["high"].iloc[-2]
        close = df["close"].iloc[-1]
        vol = df["volume"].iloc[-1]
        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
        return close > high and vol > avg_vol * self.volume_multiplier

    def bollinger_squeeze_breakout(self, df: pd.DataFrame) -> bool:
        width = df["bb_width"].rolling(20).mean().iloc[-1]
        prev_width = df["bb_width"].rolling(20).mean().iloc[-2]
        close = df["close"].iloc[-1]
        bb_high = df["bb_high"].iloc[-1]
        return prev_width < 0.05 and width > prev_width and close > bb_high

    def trend_pullback(self, df: pd.DataFrame) -> bool:
        close = df["close"].iloc[-1]
        ema20 = df["ema20"].iloc[-1]
        ema50 = df["ema50"].iloc[-1]
        return close > ema50 and ema20 > ema50 and close <= ema20 * 1.01

    def rsi_trend_bounce(self, df: pd.DataFrame) -> bool:
        rsi = df["rsi"].iloc[-1]
        return rsi > 50 and rsi - df["rsi"].iloc[-2] > 5

    def vwap_reclaim(self, df: pd.DataFrame) -> bool:
        close = df["close"].iloc[-1]
        vwap = df["vwap"].iloc[-1]
        return close > vwap and df["close"].iloc[-2] < df["vwap"].iloc[-2]

    def high_timeframe_alignment(self, df1h: pd.DataFrame, df4h: pd.DataFrame, side: str) -> bool:
        if side == "LONG":
            return df1h["ema50"].iloc[-1] > df1h["ema200"].iloc[-1] and df4h["ema50"].iloc[-1] > df4h["ema200"].iloc[-1]
        else:
            return df1h["ema50"].iloc[-1] < df1h["ema200"].iloc[-1] and df4h["ema50"].iloc[-1] < df4h["ema200"].iloc[-1]

    def volume_filter(self, df: pd.DataFrame) -> bool:
        vol = df["volume"].iloc[-1]
        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
        return vol > avg_vol * self.volume_multiplier

    def evaluate_symbol(self, symbol: str) -> Optional[Signal]:
        df15 = self.add_indicators(self.fetch_klines(symbol, Client.KLINE_INTERVAL_15MINUTE))
        df1h = self.add_indicators(self.fetch_klines(symbol, Client.KLINE_INTERVAL_1HOUR))
        df4h = self.add_indicators(self.fetch_klines(symbol, Client.KLINE_INTERVAL_4HOUR))

        strategies = []
        if self.ema_cross(df15):
            strategies.append("ema_cross")
        if self.breakout_with_volume(df15):
            strategies.append("breakout_vol")
        if self.bollinger_squeeze_breakout(df15):
            strategies.append("bb_squeeze")
        if self.trend_pullback(df15):
            strategies.append("pullback")
        if self.rsi_trend_bounce(df15):
            strategies.append("rsi_bounce")
        if self.vwap_reclaim(df15):
            strategies.append("vwap_reclaim")

        required = 3 if self.mode == "SWING" else 2
        if len(strategies) < required:
            return None

        side = "LONG" if df15["close"].iloc[-1] > df15["ema200"].iloc[-1] else "SHORT"
        if not self.high_timeframe_alignment(df1h, df4h, side):
            return None
        if not self.volume_filter(df15):
            return None

        atr = df15["atr"].iloc[-1]
        entry = df15["close"].iloc[-1]
        stop = entry - atr * 1.5 if side == "LONG" else entry + atr * 1.5
        rr = atr * 1.5
        tp1 = entry + 1.8 * rr if side == "LONG" else entry - 1.8 * rr
        tp2 = entry + 3.0 * rr if side == "LONG" else entry - 3.0 * rr

        score = self.orderbook_score(symbol)

        return Signal(symbol, side, entry, stop, tp1, tp2, strategies, score)

    # ----- Orderbook and sentiment -----------------------------------------
    def orderbook_score(self, symbol: str) -> float:
        depth = self.client.futures_order_book(symbol=symbol, limit=50)
        bid_vol = sum(float(b[1]) for b in depth["bids"])
        ask_vol = sum(float(a[1]) for a in depth["asks"])
        return bid_vol / (ask_vol + 1e-6)

    # ----- Position sizing --------------------------------------------------
    def position_size(self, entry: float, stop: float) -> float:
        risk_capital = self.state.get("equity", 0) * config.RISK_PER_TRADE
        sl_fraction = abs(entry - stop) / entry
        qty = risk_capital / sl_fraction / entry
        return math.floor(qty * 1000) / 1000  # truncate to 3 decimals

    # ----- Trade execution --------------------------------------------------
    def execute(self, signal: Signal) -> None:
        qty = self.position_size(signal.entry, signal.stop)
        msg = {
            "symbol": signal.symbol,
            "side": signal.side,
            "entry": signal.entry,
            "stop": signal.stop,
            "tp1": signal.tp1,
            "tp2": signal.tp2,
            "qty": qty,
            "strategies": ",".join(signal.strategies),
            "score": round(signal.score, 2),
        }
        if config.AUTO_TRADE and qty > 0:
            self.client.futures_create_order(
                symbol=signal.symbol,
                side=SIDE_BUY if signal.side == "LONG" else SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=qty,
            )
        self.notify(msg)

    # ----- Notifications ----------------------------------------------------
    def notify(self, message: Dict) -> None:
        if not config.DISCORD_WEBHOOK:
            print(message)
            return
        color = 3066993 if message["side"] == "LONG" else 15158332
        payload = {
            "embeds": [
                {
                    "title": f"{message['symbol']} {message['side']}",
                    "description": f"Entry {message['entry']:.4f}\nStop {message['stop']:.4f}\nTP1 {message['tp1']:.4f}\nTP2 {message['tp2']:.4f}",
                    "color": color,
                    "fields": [
                        {"name": "Qty", "value": str(message["qty"])},
                        {"name": "Strategies", "value": message["strategies"]},
                        {"name": "Score", "value": str(message["score"])}
                    ],
                    "footer": {"text": "AUTO" if config.AUTO_TRADE else "TEST"}
                }
            ]
        }
        try:
            requests.post(config.DISCORD_WEBHOOK, json=payload, timeout=5)
        except Exception as exc:
            print("Webhook error", exc)

    # ----- Run loop ---------------------------------------------------------
    async def run(self) -> None:
        while True:
            self.scan_universe()
            for symbol in self.universe:
                try:
                    signal = self.evaluate_symbol(symbol)
                    if signal:
                        self.execute(signal)
                except Exception as exc:
                    print("Error evaluating", symbol, exc)
            await asyncio.sleep(300)  # rescan every 5 minutes


if __name__ == "__main__":
    bot = T8Bot()
    asyncio.run(bot.run())

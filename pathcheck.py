"""Send a tiny test order to verify environment and credentials."""
from binance.client import Client
import config


def path_check(symbol: str = "BTCUSDT") -> None:
    client = Client(config.API_KEY, config.API_SECRET, testnet=config.USE_TESTNET)
    client.futures_change_leverage(symbol=symbol, leverage=config.LEVERAGE)
    try:
        order = client.futures_create_order(
            symbol=symbol,
            side="BUY",
            type="MARKET",
            quantity=0.001,
        )
        client.futures_cancel_all_open_orders(symbol=symbol)
        print("Test order placed and cancelled", order["orderId"])
    except Exception as exc:
        print("Path check failed:", exc)


if __name__ == "__main__":
    path_check()

from asyncio import sleep
import asyncio
import logging
from datetime import datetime, timezone, time, timedelta
from typing import Union, Optional

from signalrcore.hub_connection_builder import HubConnectionBuilder
from config import MARKET_HUB_URL

from connector import Connector


class Websocket:
    symbol: str
    last_price: float = None
    _connector: Connector = None
    _candles_poped = 0

    def __init__(self, symbol: str, connector: Connector):
        self.symbol = symbol
        self._connector = connector

        self.buckets = {i: [] for i in range(20)}
        self.buckets_set = set()

    def _login_function(self):
        return self._connector._token

    def set_first_timestamp(self, ts):
        if not self._first_timestamp:
            self._first_timestamp = ts

    def _get_bucket_index(self, offset=0) -> int:
        bucket_now = datetime.now().minute // 3
        return (bucket_now - offset) % 20

    def pop_bucket(self) -> tuple[Optional[list[float]], int]:

        last_bucket = self._get_bucket_index(offset=1)

        try:
            self.buckets_set.remove(last_bucket)
        except KeyError:
            return None, -1

        data = self.buckets.get(last_bucket)
        self.buckets[last_bucket] = []
        self._candles_poped += 1
        return data, self._candles_poped

    def get_current_bucket(self):
        current_bucket = self._get_bucket_index(offset=0)
        return self.buckets[current_bucket]

    def run(self):
        hub_connection = (
            HubConnectionBuilder()
            .with_url(
                f"{MARKET_HUB_URL}?access_token={self._login_function()}",
                options={
                    "skip_negotiation": True,
                    "access_token_factory": self._login_function,
                },
            )
            # .configure_logging(logging.DEBUG)
            .with_automatic_reconnect(
                {
                    "type": "raw",
                    "keep_alive_interval": 10,
                    "reconnect_interval": 5,
                    "max_attempts": 5,
                }
            )
            .build()
        )

        def handle_trade(data):
            _symbol, trades = data

            prices = [t["price"] for t in trades]

            bucket = int(trades[0]["timestamp"][14:16]) // 3  # 3 min hardcoded
            self.buckets_set.add(bucket)
            self.buckets[bucket].extend(prices)

            self.last_price = trades[0]["price"]

        def subscribe():
            hub_connection.send("SubscribeContractTrades", [self.symbol])
            hub_connection.on("GatewayTrade", handle_trade)

        def on_open():
            print("WS connection opened and handshake received ready to send messages")
            subscribe()

        def on_reconnect():
            print("WS reconnected")
            subscribe()

        hub_connection.on_open(on_open)

        hub_connection.on_reconnect(on_reconnect)
        hub_connection.on_close(lambda e: print(f"rad connection closed -> {e}"))
        hub_connection.on_error(lambda e: print(f"rad err -> {e}"))

        hub_connection.start()

        return self


if __name__ == "__main__":
    Websocket("CON.F.US.EP.M25", Connector()).run()
    loop = asyncio.new_event_loop()
    loop.run_forever()

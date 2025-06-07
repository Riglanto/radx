from asyncio import sleep
import asyncio

from signalrcore.hub_connection_builder import HubConnectionBuilder
from config import MARKET_HUB_URL

from connector import Connector


class Websocket:
    symbol: str
    last_price: float = None
    _connector: Connector = None

    def __init__(self, symbol: str, connector: Connector):
        self.symbol = symbol
        self._connector = connector

    def _login_function(self):
        return self._connector._token

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
            symbol, trades = data
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
        hub_connection.on_close(lambda e: print(
            f"rad connection closed -> {e}"))
        hub_connection.on_error(lambda e: print(f"rad err -> {e}"))

        hub_connection.start()

        return self


if __name__ == "__main__":
    Websocket("CON.F.US.EP.M25", Connector()).run()
    loop = asyncio.new_event_loop()
    loop.run_forever()

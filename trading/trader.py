from connector import Connector
from strategies import Action, ActionType

import logging
import chime
from logger import create_logger


chime.theme("zelda")
logging.getLogger("werkzeug").setLevel(logging.ERROR)
log = create_logger(__name__)


class Trader:
    in_position: bool = False
    contract_id: str = None

    _connector: Connector = None

    def __init__(self, contract_id: str, connector: Connector):
        self.contract_id = contract_id
        self._connector = connector

    def execute(self, action: Action):

        action_type, stop_price = action.action_type, action.stop

        if self.in_position:

            if action_type == ActionType.CLOSE:
                print("Closing position")
            pass
        else:
            # OPEN
            if action_type == ActionType.BUY:
                print("Opening position")
                self._connector.place_order(self.contract_id, ActionType.BUY, size=1, stop_price=stop_price, is_trail=True)
                chime.success()

            elif action_type == ActionType.SELL:
                print("Opening short position")
                self._connector.place_order(self.contract_id, ActionType.SELL, size=1, stop_price=stop_price, is_trail=True)
                chime.success()

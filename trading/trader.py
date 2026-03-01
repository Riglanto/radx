from strategies import Action, ActionType

import logging
import chime
from logger import create_logger


chime.theme("zelda")
logging.getLogger("werkzeug").setLevel(logging.ERROR)
log = create_logger(__name__)


class Trader:
    in_position: bool = False

    def __init__(self):
        pass

    def execute(self, action: Action):

        if self.in_position:

            if action.action_type == ActionType.CLOSE:
                # CLOSE
                print("Closing position")
            # CLOSE
            pass
        else:
            # OPEN
            if action.action_type == ActionType.BUY:
                print("Opening position")
                chime.success()

            elif action.action_type == ActionType.SELL:
                print("Opening short position")
                chime.success()

from typing import Any, List, Tuple
from enum import Enum

import pandas as pd
import os
import importlib


class ActionType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"


IMPL_ERROR = NotImplementedError("Strategy must implement the method.")


class Action:
    def __init__(self, action_type: ActionType, stop: int):
        self.action_type = action_type
        self.stop = stop


class DrawableIndicator:
    def __init__(self, key: str, mode: str, color: str, width: int):
        self.key = key
        self.mode = mode
        self.color = color
        self.width = width


class StrategyConfig:
    trading_hours: Tuple[int, int]

    def __init__(self, trading_hours: Tuple[int, int] = [0, 24]):
        self.trading_hours = trading_hours


class BaseStrategy:
    df: pd.DataFrame
    drawable_indicators: List[DrawableIndicator] = []
    config: StrategyConfig
    _params: dict[str, Any]

    def __init__(self, df: pd.DataFrame, config: StrategyConfig):
        self.df = df.copy()
        self.config = config

    def run(self, **params) -> pd.DataFrame:
        raise IMPL_ERROR

    def update(self) -> pd.DataFrame:
        raise IMPL_ERROR


class StrategyFactory:
    _strategies = {}

    @classmethod
    def register_strategy(cls, strategy_class: str):
        cls._strategies[strategy_class.__name__.lower()] = strategy_class

    @classmethod
    def create(cls, strategy_name: str, df: pd.DataFrame, config: StrategyConfig) -> BaseStrategy:
        strategy_name = strategy_name.lower()
        if strategy_name in cls._strategies:
            return cls._strategies[strategy_name](df, config)
        else:
            raise ValueError(f"Unknown strategy: {strategy_name}")


# Dynamically register all strategies in the strategies directory
strategies_dir = os.path.dirname(__file__)
for file in os.listdir(strategies_dir):
    if file.endswith(".py") and file != "__init__.py":
        module_name = f"strategies.{file[:-3]}"
        module = importlib.import_module(module_name)
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                StrategyFactory.register_strategy(obj)

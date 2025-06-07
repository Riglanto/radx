
from typing import List

import pandas as pd
import vectorbt as vbt


class DrawableIndicator:
    def __init__(self, key: str, mode: str, color: str, width: int):
        self.key = key
        self.mode = mode
        self.color = color
        self.width = width


class BaseStrategy:
    df: pd.DataFrame
    drawable_indicators: List[DrawableIndicator] = []

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()


class DefaultStrategy(BaseStrategy):
    def run(self):
        fast_ma = vbt.MA.run(self.df.close, 8, short_name="fast MA")
        slow_ma = vbt.MA.run(self.df.close, 34, short_name="slow MA")

        self.df["short_entries"] = fast_ma.ma_crossed_above(slow_ma)
        self.df["long_entries"] = fast_ma.ma_crossed_below(slow_ma)

        self.df["fast_ma"] = fast_ma.ma
        self.df["slow_ma"] = slow_ma.ma

        self.drawable_indicators = [
            DrawableIndicator("fast_ma", "lines", "purple", 1),
            DrawableIndicator("slow_ma", "lines", "blue", 1)
        ]

        return self.df


class StrategyFactory:
    _strategies = {}

    @classmethod
    def register_strategy(cls, strategy_class):
        cls._strategies[strategy_class.__name__.lower()] = strategy_class

    @classmethod
    def create(cls, strategy_name, df):
        strategy_name = strategy_name.lower()
        if strategy_name in cls._strategies:
            return cls._strategies[strategy_name](df)
        else:
            raise ValueError(f"Unknown strategy: {strategy_name}")


# Automatically register strategies
StrategyFactory.register_strategy(DefaultStrategy)

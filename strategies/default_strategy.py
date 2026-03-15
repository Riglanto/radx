from typing import Optional

import pandas as pd
import vectorbt as vbt
import numpy as np

from strategies import BaseStrategy, DrawableIndicator, ActionType, Action


class DefaultStrategy(BaseStrategy):
    def run(self, **params) -> pd.DataFrame:
        self._params = params

        p_stop = params.get("stop", 22)
        p_fast_ma = params.get("fast_ma", 8)
        p_slow_ma = params.get("slow_ma", 34)

        fast_ma = vbt.MA.run(self.df.close, p_fast_ma, short_name="fast MA")
        slow_ma = vbt.MA.run(self.df.close, p_slow_ma, short_name="slow MA")

        self.df["long_entries"] = fast_ma.ma_crossed_above(slow_ma)
        self.df["long_exits"] = fast_ma.ma_crossed_below(slow_ma)

        # Trading hours allowed
        th = self.config.trading_hours
        self.df["trading_allowed"] = self.df["time"].dt.hour.between(th[0], th[1], inclusive="left")

        self.df["long_entries"] &= self.df["trading_allowed"]
        self.df["long_exits"] &= self.df["trading_allowed"]

        # Ensure 'date' column exists by extracting date from 'time'
        self.df["date"] = self.df["time"].dt.date
        signals = self.df[self.df["long_entries"] | self.df["long_exits"]]

        # First signal of the day cannot be the exit
        signals_by_date = signals.groupby("date").first()
        is_first_exit = signals_by_date[signals_by_date["long_exits"]]["time"]
        self.df.loc[self.df["time"].isin(is_first_exit), "long_exits"] = False

        # Last trading hour: force exit if in position
        entries_cs = np.cumsum(self.df["long_entries"].astype(int).values)
        exits_cs = np.cumsum(self.df["long_exits"].astype(int).values)
        valid_exits_cs = np.minimum(exits_cs, entries_cs)
        in_position_prior = entries_cs - valid_exits_cs

        self.df["fast_ma"] = fast_ma.ma
        self.df["slow_ma"] = slow_ma.ma

        last_bars = self.df[self.df["trading_allowed"]].groupby("date").last()
        self.df.loc[self.df["time"].isin(last_bars["time"]) & (in_position_prior > 0), "long_exits"] = True

        # Recompute in position and trade id after forced last-hour exits
        entries_cs = np.cumsum(self.df["long_entries"].astype(int).values)
        exits_cs = np.cumsum(self.df["long_exits"].astype(int).values)
        valid_exits_cs = np.minimum(exits_cs, entries_cs)

        # Keep position true on the exit bar; close on next bar
        self.df["in_position"] = entries_cs - pd.Series(valid_exits_cs).shift(1, fill_value=0).values
        self.df["trade_id"] = (self.df["long_entries"].cumsum() * (self.df["in_position"] > 0)).astype(int)

        # Trailing stop
        self.df["stops"] = None
        self.df["stops"] = self.df["high"] - (p_stop * 0.25)
        self.df.loc[self.df["in_position"] <= 0, "stops"] = None
        self.df["stops"] = self.df.groupby("trade_id")["stops"].cummax()
        self.df["stop_signals"] = self.df["low"] <= self.df["stops"]

        # Drawables
        self.drawable_indicators = [
            DrawableIndicator("fast_ma", "lines", "purple", 1),
            DrawableIndicator("slow_ma", "lines", "blue", 1),
        ]

        return self.df

    def update(self) -> Optional[Action]:
        # Clean previous output
        self.df = self.df[["time", "open", "high", "low", "close", "volume", "t_original"]]

        # For this simple strategy, we can just re-run the entire logic on the updated dataframe
        self.run(**self._params)

        last = self.df.iloc[-1]

        stop = int(last["stops"]) if pd.notna(last["stops"]) else 0
        if last["long_entries"]:
            return Action(ActionType.BUY, stop)
        if last["long_exits"]:
            return Action(ActionType.CLOSE)

        return None

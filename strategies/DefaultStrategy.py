import pandas as pd
import vectorbt as vbt

from strategies import BaseStrategy, DrawableIndicator


class DefaultStrategy(BaseStrategy):
    def run(self):
        fast_ma = vbt.MA.run(self.df.close, 8, short_name="fast MA")
        slow_ma = vbt.MA.run(self.df.close, 34, short_name="slow MA")

        self.df["long_entries"] = fast_ma.ma_crossed_above(slow_ma)
        self.df["long_exits"] = fast_ma.ma_crossed_below(slow_ma)

        # Trading hours allowed
        th = self.config.trading_hours
        self.df["trading_allowed"] = self.df["time"].dt.hour.between(th[0], th[1], inclusive="left")
        self.df["trading_allowed"]

        self.df["long_entries"] &= self.df["trading_allowed"]
        self.df["long_exits"] &= self.df["trading_allowed"]

        # Ensure 'date' column exists by extracting date from 'time'
        self.df["date"] = self.df["time"].dt.date
        signals = self.df[self.df["long_entries"] | self.df["long_exits"]]

        # First signal of the day cannot be the exit
        first_signals = signals.groupby("date").first()
        is_first_exit = first_signals[first_signals["long_exits"]]["time"]
        self.df.loc[self.df["time"].isin(is_first_exit), "long_exits"] = False

        last_signals = signals.groupby("date").last()
        is_last_entry = last_signals[last_signals["long_entries"]]
        last_bars = self.df[self.df["trading_allowed"]].groupby("date").last()
        self.df.loc[self.df["date"].isin(is_last_entry["time"].dt.date) & self.df["time"].isin(last_bars["time"]), "long_exits"] = True

        self.df["fast_ma"] = fast_ma.ma
        self.df["slow_ma"] = slow_ma.ma

        self.drawable_indicators = [DrawableIndicator("fast_ma", "lines", "purple", 1), DrawableIndicator("slow_ma", "lines", "blue", 1)]

        return self.df

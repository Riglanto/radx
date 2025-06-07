
import pandas as pd
import vectorbt as vbt

from strategies import BaseStrategy, DrawableIndicator


class DefaultStrategy(BaseStrategy):
    def run(self):
        fast_ma = vbt.MA.run(self.df.close, 8, short_name="fast MA")
        slow_ma = vbt.MA.run(self.df.close, 34, short_name="slow MA")

        self.df["long_entries"] = fast_ma.ma_crossed_below(slow_ma)
        self.df["long_exits"] = fast_ma.ma_crossed_above(slow_ma)

        print(self.df.shape)
        th = self.config.trading_hours
        if th:
            self.df["trading_allowed"] = self.df["time"].dt.hour.between(
                th[0], th[1], inclusive="left")
            self.df["trading_allowed"]

            self.df["long_entries"] &= self.df["trading_allowed"]
            self.df["long_exits"] &= self.df["trading_allowed"]

            # Close before end of trading allowed
            if self.df["long_entries"].sum() > self.df["long_exits"].sum():
                last_index = self.df[self.df["trading_allowed"] == 1].index[-1]
                self.df.loc[last_index, "long_exits"] = True

        self.df["fast_ma"] = fast_ma.ma
        self.df["slow_ma"] = slow_ma.ma

        self.drawable_indicators = [
            DrawableIndicator("fast_ma", "lines", "purple", 1),
            DrawableIndicator("slow_ma", "lines", "blue", 1)
        ]

        return self.df

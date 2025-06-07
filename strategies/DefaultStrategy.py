
import vectorbt as vbt

from strategies import BaseStrategy, DrawableIndicator


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

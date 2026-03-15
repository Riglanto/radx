from typing import Optional

import pandas as pd

from config import PARAMS
from strategies import ActionType, StrategyConfig, StrategyFactory
from strategies.default_strategy import DefaultStrategy


def _read_test_data(dataset: Optional[int] = None) -> pd.DataFrame:
    suffix = f"_{dataset}" if dataset else ""
    df = pd.read_csv(f"tests/data/test_data{suffix}.csv", parse_dates=["time"], index_col=False)
    return df


def test_simple():
    data = _read_test_data()

    params = {"stop": 100, "fast_ma": 8, "slow_ma": 34, "trading_hours": [21, 24]}
    stra = StrategyFactory.create("DefaultStrategy", data, StrategyConfig(trading_hours=params["trading_hours"]))

    df = stra.run(**params)

    entries = df[df["long_entries"]]
    assert entries.shape[0] == 1
    assert str(entries["time"].iloc[0]) == "2026-02-27 21:12:00+01:00"

    exits = df[df["long_exits"]]
    assert exits.shape[0] == 1
    assert str(exits["time"].iloc[0]) == "2026-02-27 22:42:00+01:00"

    assert df["in_position"].value_counts()[1] == 31
    assert df["trade_id"].value_counts()[1] == 31


def test_update():
    raw_data = _read_test_data()
    data = raw_data.head(94)

    params = {"stop": 100, "fast_ma": 8, "slow_ma": 34, "trading_hours": [21, 24]}
    stra = StrategyFactory.create("DefaultStrategy", data, StrategyConfig(trading_hours=params["trading_hours"]))

    df = stra.run(**params)

    entries = df[df["long_entries"]]
    assert entries.shape[0] == 1
    assert str(entries["time"].iloc[0]) == "2026-02-27 21:12:00+01:00"

    exits = df[df["long_exits"]]
    assert exits.shape[0] == 1
    assert str(exits["time"].iloc[0]) == "2026-02-27 22:39:00+01:00"

    assert df["in_position"].value_counts()[1] == 30
    assert df["trade_id"].value_counts()[1] == 30
    import pdb

    # Adds row
    stra.df = pd.concat([stra.df, raw_data.iloc[94:95]])

    action = stra.update()
    assert action.action_type == ActionType.CLOSE

    # Keep updating exit
    df = stra.df
    assert df["in_position"].value_counts()[1] == 31

    # Adds remaining rows
    stra.df = pd.concat([stra.df, raw_data.iloc[95:]])

    action = stra.update()
    assert not action

    # Unchanged
    df = stra.df
    assert df["in_position"].value_counts()[1] == 31


def test_two_trades():
    data = _read_test_data()
    params = {"stop": 100, "fast_ma": 8, "slow_ma": 34, "trading_hours": [0, 22]}
    stra = StrategyFactory.create("DefaultStrategy", data, StrategyConfig(trading_hours=params["trading_hours"]))

    df = stra.run(**params)

    entries = df[df["long_entries"]]
    assert entries.shape[0] == 2

    exits = df[df["long_exits"]]
    assert exits.shape[0] == 2
    assert df["in_position"].value_counts()[1] == 24

    assert df["trade_id"].value_counts()[1] == 8
    assert df["trade_id"].value_counts()[2] == 16


def test_trailing_stops():
    data = _read_test_data()
    params = {"stop": 62, "fast_ma": 8, "slow_ma": 34, "trading_hours": [0, 22]}
    stra = StrategyFactory.create("DefaultStrategy", data, StrategyConfig(trading_hours=params["trading_hours"]))

    df = stra.run(**params)

    assert df["stop_signals"].value_counts()[True] == 3

    stops = df[df["stop_signals"]]["time"]

    assert str(stops.iloc[0]) == "2026-02-27 20:24:00+01:00"
    assert str(stops.iloc[1]) == "2026-02-27 21:36:00+01:00"
    assert str(stops.iloc[2]) == "2026-02-27 21:39:00+01:00"


def test_narrow_trading_arrows():
    data = _read_test_data()
    params = {"stop": 100, "fast_ma": 8, "slow_ma": 34, "trading_hours": [21, 22]}
    stra = StrategyFactory.create("DefaultStrategy", data, StrategyConfig(trading_hours=params["trading_hours"]))

    df = stra.run(**params)

    entries = df[df["long_entries"]]
    assert entries.shape[0] == 1
    assert str(entries["time"].iloc[0]) == "2026-02-27 21:12:00+01:00"

    exits = df[df["long_exits"]]
    assert exits.shape[0] == 1
    assert str(exits["time"].iloc[0]) == "2026-02-27 21:57:00+01:00"

    assert df["in_position"].value_counts()[1] == 16
    assert df["trade_id"].value_counts()[1] == 16


def test_double_close_signal():
    data = _read_test_data(2)
    params = {"stop": 28, "fast_ma": 8, "slow_ma": 34, "trading_hours": [0, 22]}
    stra = StrategyFactory.create("DefaultStrategy", data, StrategyConfig(trading_hours=params["trading_hours"]))

    df = stra.run(**params)

    entries = df[df["long_entries"]]
    assert entries.shape[0] == 10
    exits = df[df["long_exits"]]
    assert exits.shape[0] == 10

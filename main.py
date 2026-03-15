from datetime import datetime, timezone, time, timedelta

from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv
import json
import math
import itertools

import vectorbt as vbt
import plotly.graph_objects as go
from dash import Dash, Input, Output, callback, dcc, html, dash_table
import click
from tqdm import tqdm

from config import LOCAL_TIMEZONE, APP_NAME, PARAMS, BACKTESTING_PARAMS
from connector import TIME_UNITS, Connector
from trading.trader import Trader
from ws import Websocket

from strategies import ActionType, BaseStrategy, StrategyFactory, StrategyConfig

from logger import create_logger
import logging

logging.getLogger("werkzeug").setLevel(logging.ERROR)
log = create_logger(__name__)
load_dotenv()


@click.command()
@click.option("--strategy", default="DefaultStrategy", help="Strategy name.")
@click.option("--ui", is_flag=True, help="Show dash dashboard.")
@click.option("--stream", default=False, is_flag=True, help="With live webosocket.")
@click.option("--backtest", default=False, is_flag=True, help="Backtesting.")
@click.option("--trade", default=False, is_flag=True, help="Trade.")
def main(strategy: str, ui: bool, stream: bool, backtest: bool, trade: bool):
    log.info(f"Starting with strategy={strategy}, ui={ui}, stream={stream}, backtest={backtest}, trade={trade}")

    con = Connector()
    # print(con.get_open_positions())
    # con.close_positions("CON.F.US.EP.H26")
    # print(con.place_order("CON.F.US.EP.H26", ActionType.SELL, size=1, stop_price=6843.5, is_trail=True))
    # print(con.get_open_positions())
    # return

    symbol, tf = "ES", [3, TIME_UNITS.Minute]
    contract_id = con.find_contract(symbol)
    config = (contract_id, symbol, tf, strategy, stream)
    # times = ["2026-02-19T00:00:00", "2026-02-20T00:00:00"]
    times = ["2026-02-27T00:00:00", "2026-02-28T00:00:00"]
    # times = ["2025-01-01T00:00:00", "2026-03-10T00:00:00"]

    ws = Websocket(contract_id, con).run() if stream or trade else None

    if trade:
        now_utc = datetime.now(ZoneInfo(LOCAL_TIMEZONE)).astimezone(timezone.utc)
        start = (datetime.combine(now_utc, time.min) - timedelta(days=1)).isoformat()  # .replace("10T", "08T")  # ytd midnight
        end = now_utc.isoformat()  # .replace("11T", "09T")  # now

        times = [start, end]
    df = con.get_bars(symbol, contract_id, tf=tf, times=times, includePartialBar=stream or trade)

    if ui or trade:
        return run_ui(df, con, ws, config, trade)

    if backtest:
        return run_backtest(df, config)


def run_backtest(df: pd.DataFrame, config: tuple):
    (contract_id, symbol, tf, strategy, stream) = config

    params = BACKTESTING_PARAMS

    stra = StrategyFactory.create(strategy, df, StrategyConfig(trading_hours=params.get("trading_hours")))

    del params["trading_hours"]

    keys = params.keys()

    combinations = math.prod([params[key]["max"] - params[key]["min"] + 1 for key in keys])
    print(f"Running backtest for...")
    print(f"{combinations} combination, {df['time'].dt.date.nunique()} days, {df.shape[0]} candles")

    def yielder(key):
        start = params[key]["min"]
        end = params[key]["max"] + 1
        for val in range(start, end, 1):
            yield val

    def generate_params():
        for xs in itertools.product(*[yielder(key) for key in keys]):
            yield dict(zip(keys, xs))

    results = []
    for p in tqdm(generate_params()):
        df = stra.run(**p)

        pf = vbt.Portfolio.from_signals(
            df.close,
            entries=df.long_entries,
            exits=df.long_exits,
            freq=f"{tf[0]}{tf[1].name.lower()[0]}",
            size=1,
            size_type="amount",
        )

        positions = build_positions(pf.positions)

        sum_row = positions[["Ticks", "Gain"]].sum()

        wins = positions[positions["Ticks"] >= 0]
        losses = positions[positions["Ticks"] < 0]

        biggest_win = wins["Ticks"].max()
        average_win = wins["Ticks"].mean()
        biggest_loss = losses["Ticks"].min()
        average_loss = losses["Ticks"].mean()
        # cum_win
        res = {
            "params": p,
            "total_ticks": sum_row["Ticks"],
            "trades": positions.shape[0],
            "wins": wins.shape[0],
            "losses": losses.shape[0],
            "win_rate": (wins.shape[0] / positions.shape[0]) if positions.shape[0] > 0 else 0,
            "biggest_win": int(biggest_win) if not pd.isna(biggest_win) else "/",
            "average_win": round(float(average_win), 2) if not pd.isna(average_win) else "/",
            "biggest_loss": int(biggest_loss) if not pd.isna(biggest_loss) else "/",
            "average_loss": round(float(average_loss), 2) if not pd.isna(average_loss) else "/",
        }

        results.append(res)

    df = pd.DataFrame(results)
    df.sort_values(by="win_rate", ascending=False, inplace=True)
    df.to_csv(f"_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", index=False)


def build_positions(positions) -> pd.DataFrame:
    df = positions.records_readable
    df["Ticks"] = ((df["Avg Exit Price"] - df["Avg Entry Price"]) / 0.25).astype(int)
    df["Gain"] = df["Ticks"] * 12.5

    return df


def run_ui(df: pd.DataFrame, con: Connector, ws: Websocket, config: tuple, trade: bool):
    (contract_id, symbol, tf, strategy, stream) = config
    title = f"{APP_NAME} - {strategy} - {symbol} - {tf[0]} {tf[1].name} ({LOCAL_TIMEZONE})"

    stra = StrategyFactory.create(strategy, df, StrategyConfig(trading_hours=PARAMS.get("trading_hours", [7, 22])))
    df = stra.run(**PARAMS)

    pf = vbt.Portfolio.from_signals(
        df.close,
        entries=df.long_entries,
        exits=df.long_exits,
        freq=f"{tf[0]}{tf[1].name.lower()[0]}",
        size=1,
        size_type="amount",
    )

    # Get last trading day for initial load
    last_day = df["time"].max()

    positions = build_positions(pf.positions)

    summary_fig = pf.plot(subplots=["orders", "trade_pnl", "cum_returns"])

    app = Dash(APP_NAME, prevent_initial_callbacks=True)
    app.title = APP_NAME

    all_dates = pd.date_range(df["time"].min(), df["time"].max(), freq="D", tz=LOCAL_TIMEZONE)
    present_dates = df["time"].dt.date.unique().tolist()
    disabled_dates = sorted(set(all_dates.date) - set(pd.to_datetime(present_dates).date))

    trading_hours = stra.config.trading_hours
    time_delta = pd.Timedelta(minutes=tf[0])

    if trade:

        trader = Trader("CON.F.US.EP.H26", con)

        def _build_candle(bucket):
            open_ = bucket[0]
            high = max(bucket)
            low = min(bucket)
            close = bucket[-1]
            return open_, high, low, close

        @callback(
            Output("chart", "figure"),
            Input("interval", "n_intervals"),
        )
        def update_output(n_intervals):
            bucket, candles_poped = ws.pop_bucket()
            if bucket:
                open_, high, low, close = _build_candle(bucket)

                log.info(candles_poped)
                last_ts = stra.df.iloc[-1]["time"]
                if candles_poped == 1:  # Updates first partial candle
                    partial_candle = stra.df.iloc[-1].copy()
                    last_idx = stra.df.index[-1]
                    stra.df.at[last_idx, "high"] = max(partial_candle["high"], high)
                    stra.df.at[last_idx, "low"] = min(partial_candle["low"], low)
                    stra.df.at[last_idx, "close"] = close
                else:
                    # /home/rad/Projects/rad/radx/main.py:211: FutureWarning:
                    # The behavior of DataFrame concatenation with empty or all-pd.NA entries is deprecated. In a future version, this will no longer exclude empty or all-NA columns when determining the result dtypes. To retain the old behavior, exclude the relevant entries before the concat operation.
                    stra.df.loc[len(stra.df)] = {
                        "time": last_ts + time_delta,
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "trading_allowed": True,
                    }

                    # Update strategy
                    action = stra.update()
                    if action:
                        log.info(f"Action: {action.action_type}, Stop: {action.stop}")
                        trader.execute(action)

            active = ws.get_current_bucket()

            return build_chart(
                stra, positions, last_day, trading_hours, last_price=ws and ws.last_price, active=active and _build_candle(active)  # None,
            )

    else:

        @callback(
            Output("chart", "figure"),
            Input("date-picker", "date"),
            Input("trading-hours-slider", "value"),
        )
        def update_output(date_value, slider_value):
            if date_value:
                return build_chart(
                    stra,
                    positions,
                    pd.to_datetime(date_value),
                    slider_value,
                    last_price=ws and ws.last_price,
                )

        @callback(
            Output("table-records", "data"),
            Input("date-picker", "date"),
        )
        def update_table(date_value):
            if date_value:
                return build_table_records(positions, pd.to_datetime(date_value))

    graph = dcc.Graph(
        id="chart",
        figure=build_chart(stra, positions if not trade else None, last_day, trading_hours=trading_hours),
        style={"height": "85vh"},
    )
    app.layout = html.Div(
        (
            [dcc.Interval(id="interval", interval=1000), graph]
            if trade
            else [
                dcc.Interval(id="interval", interval=1 * 1000) if stream else None,  # updates every 1 secs
                html.Div(
                    children=[
                        html.H4(
                            id="header",
                            children=title,
                            style={"textAlign": "center", "margin-right": 20},
                        ),
                        dcc.DatePickerSingle(
                            id="date-picker",
                            date=df["time"].max(),
                            min_date_allowed=df["time"].min(),
                            max_date_allowed=df["time"].max(),
                            display_format="MMM Do, YY",
                            disabled_days=disabled_dates,
                            first_day_of_week=1,
                            clearable=True,
                            with_portal=True,
                        ),
                    ],
                    style={"display": "flex", "justifyContent": "center"},
                ),
                dcc.RangeSlider(0, 24, 1, value=trading_hours, id="trading-hours-slider"),
                html.Div(
                    children=[
                        dcc.Graph(id="summary_chart", figure=summary_fig),
                        html.Div(
                            children=[
                                graph,
                                html.H6(children=f"Buys {pf.orders.buy.count()}, Sells {pf.orders.sell.count()}"),
                            ],
                            style={"flex": 1},
                        ),
                    ],
                    style={"display": "flex"},
                ),
                dash_table.DataTable(
                    data=build_table_records(positions, last_day),
                    columns=[
                        {"name": i, "id": i}
                        for i in [
                            "Direction",
                            "Size",
                            "PnL",
                            "Entry Timestamp",
                            "Avg Entry Price",
                            "Exit Timestamp",
                            "Avg Exit Price",
                            "Ticks",
                            "Gain",
                            "Status",
                        ]
                    ],
                    id="table-records",
                ),
            ]
        ),
    )

    app.run()


def build_table_records(df, date):
    records = df[df["Entry Timestamp"].dt.date == date.date()]
    sum_row = records[["Ticks", "Gain"]].sum().to_frame().T
    sum_row["Direction"] = "TOTAL"
    records = pd.concat([records, sum_row], ignore_index=True)

    return records.to_dict("records")


def build_chart(
    stra: BaseStrategy,
    positions: Optional[pd.DataFrame],
    date=datetime.today(),
    trading_hours: tuple[int, int] = [],
    last_price: float = None,
    active: Optional[tuple[float, float, float, float]] = None,
) -> go.Figure:
    df = stra.df
    df = df[df["time"].dt.date == date.date()]

    time_delta = pd.Timedelta(minutes=3)

    positions_scatters = []
    if positions is not None:
        df = pd.merge(df, positions, left_on="t_original", right_on="Exit Timestamp", how="left")
        long_entries = df[df["Entry Timestamp"].notna()]
        long_exits = df[df["Exit Timestamp"].notna()]
        positions_scatters = [
            go.Scatter(
                x=long_entries["Entry Timestamp"],
                y=long_entries["Avg Entry Price"],
                mode="markers",
                name="Buys",
                text="Buy",
                marker=dict(
                    color="green",
                    size=20,
                    symbol="triangle-up",
                ),
                textposition="bottom center",
            ),
            go.Scatter(
                x=df["time"],
                y=df["stops"],
                mode="lines",
                name="Stop",
                line=dict(color="black", width=1),
            ),
            go.Scatter(
                x=long_exits["Exit Timestamp"],
                y=long_exits["Avg Exit Price"],
                mode="markers",
                name="Sell",
                text=long_exits["Ticks"].apply(lambda x: f"Sell {x:+0.0f}"),
                marker=dict(
                    color="red",
                    size=20,
                    symbol="triangle-down",
                ),
                textposition="top center",
            ),
        ]

    if trading_hours:
        df = df[(df["time"].dt.hour >= max((trading_hours[0] - 1), 0) % 25) & (df["time"].dt.hour <= trading_hours[1])]

    indicators = map(
        lambda ind: go.Scatter(
            x=df["time"],
            y=df[ind.key],
            mode=ind.mode,
            name=ind.key.replace("_", " ").title(),
            line=dict(color=ind.color, width=ind.width),
        ),
        stra.drawable_indicators,
    )

    def active_candle():
        if not active:
            return []

        open_, high, low, close = active
        return [
            go.Candlestick(
                x=df.tail(1)["time"] + time_delta,
                high=[high],
                low=[low],
                open=[open_],
                close=[close],
                name="Active",
                increasing_line_color="gray",
                decreasing_line_color="gray",
            ),
        ]

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df["time"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name="Price",
            ),
            *active_candle(),
            *indicators,
            *positions_scatters,
        ],
    )

    trading_allowed = df[df["trading_allowed"]]

    fig.add_vline(
        x=trading_allowed.iloc[0]["time"],
        line_width=2,
        line_dash="dash",
        line_color="green",
    )

    if not active:
        fig.add_vline(
            x=trading_allowed.iloc[-1]["time"] + time_delta,
            line_width=1,
            line_dash="dash",
            line_color="red",
        )

    if last_price:
        fig.add_hline(
            y=last_price,
            line_width=1,
            line_color="black",
            line_dash="dot",
            annotation_text=f"Last Price {last_price}",
            annotation_position="top left",
        )
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        yaxis=dict(side="right"),
    )

    if not df.empty:
        pad = time_delta * 3
        fig.update_xaxes(range=[df["time"].min(), df["time"].max() + pad])

    return fig


if __name__ == "__main__":
    main()

from datetime import datetime

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
from ws import Websocket

from strategies import BaseStrategy, StrategyFactory, StrategyConfig

load_dotenv()


@click.command()
@click.option("--strategy", default="DefaultStrategy", help="Strategy name.")
@click.option("--ui", is_flag=True, help="Show dash dashboard.")
@click.option("--stream", default=False, is_flag=True, help="With live webosocket.")
@click.option("--backtest", default=False, is_flag=True, help="Backtesting.")
@click.option("--trade", default=False, is_flag=True, help="Trade.")
def main(strategy: str, ui: bool, stream: bool, backtest: bool, trade: bool):
    con = Connector()

    symbol, tf = "ES", [3, TIME_UNITS.Minute]
    contract_id = con.find_contract(symbol)
    config = (contract_id, symbol, tf, strategy, stream)

    df = con.get_bars(symbol, contract_id, tf=tf, times=["2025-01-01T00:00:00", "2026-01-11T00:00:00"])
    # df = con.get_bars(contract_id, tf=tf, times=["2025-12-23T00:00:00", "2025-12-25T00:00:00"])

    df.sort_values(by="time", inplace=True)

    # Time index req for vbt plots
    df.set_index(df["time"], inplace=True)
    # data fetched, can we get more?

    if ui:
        return run_ui(df, con, config)

    if backtest:
        return run_backtest(df, config)

    if trade:
        print("Trading not implemented yet.")


def run_backtest(df: pd.DataFrame, config: tuple):
    (contract_id, symbol, tf, strategy, stream) = config

    params = BACKTESTING_PARAMS

    stra = StrategyFactory.create(strategy, df, StrategyConfig(trading_hours=params.get("trading_hours", [7, 22])))

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
    df.to_csv("_backtest_results.csv", index=False)


def build_positions(positions) -> pd.DataFrame:
    df = positions.records_readable
    df["Ticks"] = ((df["Avg Exit Price"] - df["Avg Entry Price"]) / 0.25).astype(int)
    df["Gain"] = df["Ticks"] * 12.5

    return df


def run_ui(df: pd.DataFrame, con: Connector, config: tuple):
    (contract_id, symbol, tf, strategy, stream) = config
    title = f"{APP_NAME} - {strategy} - {symbol} - {tf[0]} {tf[1].name} ({LOCAL_TIMEZONE})"
    ws = Websocket(contract_id, con).run() if stream else None

    stra = StrategyFactory.create(strategy, df, StrategyConfig(trading_hours=[7, 22]))
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

    app.layout = html.Div(
        [
            dcc.Interval(id="interval", interval=3 * 1000) if stream else None,  # updates every 3 secs
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
                            dcc.Graph(
                                id="chart",
                                figure=build_chart(stra, positions, last_day, trading_hours=trading_hours),
                                style={"height": "85vh"},
                            ),
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
        ],
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
    positions: pd.DataFrame,
    date=datetime.today(),
    trading_hours: tuple[int, int] = [],
    last_price: float = None,
) -> go.Figure:
    df = stra.df
    df = df[df["time"].dt.date == date.date()]

    df = pd.merge(df, positions, left_on="t_original", right_on="Exit Timestamp", how="left")

    if trading_hours:
        df = df[(df["time"].dt.hour >= (trading_hours[0] - 1) % 25) & (df["time"].dt.hour <= trading_hours[1])]

    long_entries = df[df["Entry Timestamp"].notna()]
    long_exits = df[df["Exit Timestamp"].notna()]

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
            *indicators,
            go.Scatter(
                x=df["time"],
                y=df["stops"],
                mode="lines",
                name="Stop",
                line=dict(color="black", width=1),
            ),
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
    )

    trading_allowed = df[df["trading_allowed"]]

    fig.add_vline(
        x=trading_allowed.iloc[0]["time"],
        line_width=1,
        line_dash="dash",
        line_color="green",
    )

    fig.add_vline(
        x=trading_allowed.iloc[-1]["time"],
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
    fig.update_layout(xaxis_rangeslider_visible=False)
    return fig


if __name__ == "__main__":
    main()

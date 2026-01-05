from datetime import datetime

import pandas as pd
import numpy as np
from dotenv import load_dotenv

import vectorbt as vbt
import plotly.graph_objects as go
from dash import Dash, Input, Output, callback, dcc, html, dash_table
import click

from config import LOCAL_TIMEZONE, APP_NAME
from connector import TIME_UNITS, Connector
from ws import Websocket

from strategies import BaseStrategy, StrategyFactory, StrategyConfig
from numba import njit

load_dotenv()


@click.command()
@click.option("--strategy", default="DefaultStrategy", help="Strategy name.")
@click.option("--ui", is_flag=True, help="Show dash dashboard.")
@click.option("--stream", default=False, is_flag=True, help="With live webosocket.")
def main(strategy: str, ui: bool, stream: bool):
    con = Connector()

    symbol, tf = "ES", [3, TIME_UNITS.Minute]
    title = f"{APP_NAME} - {strategy} - {symbol} - {tf[0]} {tf[1].name} ({LOCAL_TIMEZONE})"
    contract_id = con.find_contract(symbol)

    ws = Websocket(contract_id, con).run() if stream else None

    # df = con.get_bars(contract_id, tf=tf, times=["2025-12-23T00:00:00", "2025-12-24T00:00:00"])
    df = con.get_bars(contract_id, tf=tf, times=["2025-12-23T00:00:00", "2025-12-25T00:00:00"])

    df.sort_values(by="time", inplace=True)

    # Time index req for vbt plots
    df.set_index(df["time"], inplace=True)

    # Get last trading day for initial load
    last_day = df["time"].max()

    stra = StrategyFactory.create(strategy, df, StrategyConfig(trading_hours=[7, 22]))
    df = stra.run()

    pf = vbt.Portfolio.from_signals(
        df.close,
        entries=df.long_entries,
        exits=df.long_exits,
        freq=f"{tf[0]}{tf[1].name.lower()[0]}",
        size=1,
        size_type="amount",
    )

    def build_positions(positions):
        df = positions.records_readable
        df["Ticks"] = (df["Avg Exit Price"] - df["Avg Entry Price"]) / 0.25
        df["Gain"] = df["Ticks"] * 12.5

        return df

    positions = build_positions(pf.positions)

    summary_fig = pf.plot(subplots=["orders", "trade_pnl", "cum_returns"])

    if ui:
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

import requests
import os
from enum import Enum
from datetime import datetime
import json

import pandas as pd
from dotenv import load_dotenv

import vectorbt as vbt
import plotly.graph_objects as go
from dash import Dash, Input, Output, callback, dcc, html, dependencies
import click

from config import LOCAL_TIMEZONE, APP_NAME
from connector import TIME_UNITS, Connector
from ws import Websocket

from strategies import BaseStrategy, StrategyFactory

load_dotenv()


@click.command()
@click.option("--strategy", default="DefaultStrategy", help="Strategy name.")
@click.option("--ui", is_flag=True, help="Show dash dashboard.")
def main(strategy, ui):
    con = Connector()

    symbol, tf = "ES", [3, TIME_UNITS.Minute]
    title = f"{APP_NAME} - {strategy} - {symbol} - {tf[0]} {tf[1].name} ({LOCAL_TIMEZONE})"
    contract_id = con.find_contract(symbol)

    ws = Websocket(contract_id, con).run()

    df = con.get_bars(contract_id, tf=tf)

    # Time index req for vbt plots
    df.set_index(df["time"], inplace=True)

    stra = StrategyFactory.create(strategy, df)
    df = stra.run()

    pf = vbt.Portfolio.from_signals(
        df.close,
        entries=df.long_entries,
        exits=df.short_entries,
        freq=f"{tf[0]}{tf[1].name.lower()[0]}",
    )
    summary_fig = pf.plot(subplots=["orders", "trade_pnl", "cum_returns"])

    # print(pf.stats())

    if ui:
        app = Dash(APP_NAME, prevent_initial_callbacks=True)
        app.title = APP_NAME

        all_dates = pd.date_range(
            df["time"].min(), df["time"].max(), freq="D", tz=LOCAL_TIMEZONE
        )
        present_dates = df["time"].dt.date.unique().tolist()
        disabled_dates = sorted(
            set(all_dates.date) - set(pd.to_datetime(present_dates).date)
        )

        trading_hours = [7, 22]

        @callback(
            Output("chart", "figure"),
            Input("date-picker", "date"),
            Input("trading-hours-slider", "value"),
            Input("interval", "n_intervals"),
        )
        def update_output(date_value, slider_value, n_intervals):
            if date_value:
                return build_chart(
                    stra,
                    pd.to_datetime(date_value),
                    slider_value,
                    last_price=ws.last_price,
                )

        app.layout = html.Div(
            [
                dcc.Interval(id="interval", interval=3 *
                             1000),  # updates every 3 secs
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
                dcc.RangeSlider(
                    0, 24, 1, value=trading_hours, id="trading-hours-slider"
                ),
                html.Div(
                    children=[
                        dcc.Graph(
                            id="summary_chart",
                            figure=summary_fig,
                        ),
                        dcc.Graph(
                            id="chart",
                            figure=build_chart(
                                stra, trading_hours=trading_hours),
                            style={"flex": 1, "height": "85vh"},
                        ),
                    ],
                    style={"display": "flex"},
                ),
            ],
        )

        app.run()


def build_chart(
    stra: BaseStrategy,
    date=datetime.today(),
    trading_hours: tuple[int, int] = [],
    last_price: float = None,
) -> go.Figure:
    df = stra.df
    df = df[df["time"].dt.date == date.date()]
    if trading_hours:
        df = df[
            (df["time"].dt.hour >= trading_hours[0])
            & (df["time"].dt.hour <= trading_hours[1])
        ]

    long_entries = df[df["long_entries"] == True]
    short_entries = df[df["short_entries"] == True]

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
                x=long_entries["time"],
                y=long_entries["close"],
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
                x=short_entries["time"],
                y=short_entries["close"],
                mode="markers",
                name="Sells",
                text="Sell",
                marker=dict(
                    color="red",
                    size=20,
                    symbol="triangle-down",
                ),
                textposition="top center",
            ),
        ]
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

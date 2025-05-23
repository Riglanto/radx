import requests
import os
from enum import Enum
from datetime import datetime
import json

import pandas as pd
from dotenv import load_dotenv

import vectorbt as vbt
import plotly.graph_objects as go
from dash import Dash, dcc, html
import click

from connector import Connector


load_dotenv()


@click.command()
@click.option("--ui", is_flag=True, help="Show dash dashboard.")
def main(ui):
    print("Hello from radx!", os.getenv("SECRET_USERNAME"))
    con = Connector()

    df = con.get_bars(
        "CON.F.US.EP.M25",
        ["2025-05-16T00:00:00Z", "2025-05-20T00:00:00Z"],
    )

    print(df.head())
    print(df.tail())

    fast_ma = vbt.MA.run(df.close, 10, short_name="fast MA")
    slow_ma = vbt.MA.run(df.close, 50, short_name="slow MA")

    long_entries = fast_ma.ma_crossed_above(slow_ma)
    short_entries = fast_ma.ma_crossed_below(slow_ma)

    pf = vbt.Portfolio.from_signals(
        df.close, entries=long_entries, short_entries=short_entries, freq="5m"
    )

    print(pf.stats())

    fig = pf.plot(subplots=["orders", "trade_pnl", "cum_returns"])
    fast_ma.ma.vbt.plot(fig=fig)
    slow_ma.ma.vbt.plot(fig=fig)

    if ui:
        app = Dash()

        app.layout = html.Div(
            [
                html.H1(children="Radx", style={"textAlign": "center"}),
                dcc.Graph(figure=fig),
            ],
            style={"height": "100vh", "width": "100%"},
        )

        app.run(debug=False)


if __name__ == "__main__":
    main()

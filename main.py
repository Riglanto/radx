from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

import vectorbt as vbt
import plotly.graph_objects as go
from dash import Dash, Input, Output, callback, dcc, html, dash_table
import click

from config import LOCAL_TIMEZONE, APP_NAME
from connector import TIME_UNITS, Connector
from ws import Websocket

from strategies import BaseStrategy, StrategyFactory, StrategyConfig

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

    df = con.get_bars(contract_id, tf=tf)

    df.sort_values(by="time", inplace=True)

    # Time index req for vbt plots
    df.set_index(df["time"], inplace=True)

    # Filter data for the last day
    last_day = df["time"].max()
    # df = df[df["time"].dt.date == last_day]

    stra = StrategyFactory.create(
        strategy, df, StrategyConfig(trading_hours=[7, 22]))
    df = stra.run()

    pf = vbt.Portfolio.from_signals(
        df.close,
        entries=df.long_entries,
        exits=df.long_exits,
        freq=f"{tf[0]}{tf[1].name.lower()[0]}",
        size=1
    )
    summary_fig = pf.plot(subplots=["orders", "trade_pnl", "cum_returns"])

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

        trading_hours = stra.config.trading_hours

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
                    last_price=ws and ws.last_price,
                )

        @callback(
            Output("table-records", "data"),
            Input("date-picker", "date"),
        )
        def update_table(date_value):
            if date_value:
                return build_table_records(
                    pf.positions, pd.to_datetime(date_value)
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
                            figure=summary_fig
                        ),
                        html.Div(
                            children=[
                                dcc.Graph(
                                    id="chart",
                                    figure=build_chart(
                                        stra, last_day, trading_hours=trading_hours),
                                    style={"height": "85vh"}
                                ),
                                html.H6(
                                    children=f"Buys {pf.orders.buy.count()}, Sells {pf.orders.sell.count()}")
                            ],
                            style={"flex": 1},
                        )
                    ],
                    style={"display": "flex"},
                ),
                dash_table.DataTable(
                    data=build_table_records(pf.positions, last_day),
                    columns=[{"name": i, "id": i} for i in
                             ["Direction", "Size", "PnL", "Entry Timestamp",
                              "Avg Entry Price", "Exit Timestamp", "Avg Exit Price", "Status"]],
                    id="table-records"),
            ],
        )

        app.run()


def build_table_records(positions, date):
    df = positions.records_readable
    return df[df["Entry Timestamp"].dt.date == date.date()].to_dict(
        'records')


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
            (df["time"].dt.hour >= (trading_hours[0] - 1) % 25)
            & (df["time"].dt.hour <= trading_hours[1])
        ]

    long_entries = df[df["long_entries"] == True]
    long_exits = df[df["long_exits"] == True]

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
                x=long_exits["time"],
                y=long_exits["close"],
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

    trading_allowed = df[df["trading_allowed"]]

    fig.add_vline(x=trading_allowed.iloc[0]["time"],
                  line_width=1, line_dash="dash", line_color="green")

    fig.add_vline(x=trading_allowed.iloc[-1]["time"],
                  line_width=1, line_dash="dash", line_color="red")

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

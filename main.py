import requests
import os
from enum import Enum
from datetime import datetime
import json

import pandas as pd
from dotenv import load_dotenv


load_dotenv()

# API Endpoint: https://api.topstepx.com
# User Hub: https://rtc.topstepx.com/hubs/user
# Market Hub: https://rtc.topstepx.com/hubs/market
API_URL = "https://api.topstepx.com"
LIVE_DATA = False
LOCAL_TIMEZONE = "Europe/Berlin"


class TIME_UNITS(Enum):
    Second = 1
    Minute = 2
    Hour = 3
    Day = 4
    Week = 5
    Month = 6


class Connector:
    _session: requests.Session = None

    def __init__(self):
        self._login()

    def _store_token(self, token: str):
        with open(".token.json", "w") as outfile:
            json.dump(
                {
                    "ts": int(datetime.now().timestamp()),
                    "token": token,
                },
                outfile,
            )

            print("Token saved l=", len(token))

    def _read_token(self):
        try:
            with open(".token.json", "r") as outfile:
                data = json.load(
                    outfile,
                )

                diff = datetime.now() - datetime.fromtimestamp(data["ts"])

                # Reload if older than 23h
                if (diff.seconds // 3600) > 23:
                    print("Token older than 23h")
                    return None

                print("Token loaded")
                return data["token"]
        except:
            return None

    def _login(self):
        token = self._read_token()

        if not token:
            res = requests.post(
                f"{API_URL}/api/Auth/loginKey",
                json={
                    "userName": os.getenv("SECRET_USERNAME"),
                    "apiKey": os.getenv("SECRET_API_KEY"),
                },
            )

            data = res.json()
            if not data["success"]:
                print("Error", data)
                return

            token = data["token"]
            self._store_token(token)

        self._session = requests.Session()
        self._session.headers = {"Authorization": f"Bearer { token}"}

    def revalidate(self):
        res = self._post("Auth/validate")

        data = res.json()
        if not data["success"]:
            print("Error", data)
            return

        token = data["newToken"]
        self._session.headers = {"Authorization": f"Bearer { token}"}

        print("Token saved l=", len(token))

    def _post(self, url: str, json: dict = {}):
        return self._session.post(f"{API_URL}/api/{url}", json=json)

    def get_accounts(self):
        res = self._post("account/search", {"onlyActiveAccounts": True})
        print(res.json()["accounts"])

    def get_contracts(self, text="ES"):
        res = self._post("contract/search", {"live": LIVE_DATA, "searchText": text})
        print(res.json()["contracts"])

    def get_bars(
        self,
        contractId: str,
        times: tuple[str, str] = [
            datetime.now().isoformat(),
            datetime.now().isoformat(),
        ],
        tf: tuple[int, TIME_UNITS] = (3, TIME_UNITS.Minute),
        limit=1000000000,  # fetches all the data for contract
        includePartialBar=False,
    ):
        res = self._post(
            "History/retrieveBars",
            {
                "contractId": contractId,
                "live": LIVE_DATA,
                "startTime": times[0],
                "endTime": times[1],
                "unitNumber": tf[0],
                "unit": tf[1].value,
                "limit": limit,
                "includePartialBar": includePartialBar,
            },
        )

        return res.json()["bars"]


def main():
    print("Hello from radx!", os.getenv("SECRET_USERNAME"))
    con = Connector()

    bars = con.get_bars(
        "CON.F.US.EP.M25",
        ["2025-05-16T00:00:00Z", "2025-05-20T00:00:00Z"],
    )
    df = pd.DataFrame(bars)
    df["t"] = pd.to_datetime(df["t"])
    if LOCAL_TIMEZONE:
        df["t_original"] = df["t"]
        df["t"] = df["t"].dt.tz_convert(LOCAL_TIMEZONE)

    print(df.head())
    print(df.tail())


if __name__ == "__main__":
    main()

# January	F
# February	G
# March	H
# April	J
# May	K
# June	M
# July	N
# August	Q
# September	U
# October	V
# November	X
# December	Z

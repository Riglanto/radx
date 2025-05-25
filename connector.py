import requests
import os
from enum import Enum
from datetime import datetime, timedelta
import json
import logging

import pandas as pd
from dotenv import load_dotenv

import vectorbt as vbt

from config import API_URL, LIVE_DATA, LOCAL_TIMEZONE


class TIME_UNITS(Enum):
    Second = 1
    Minute = 2
    Hour = 3
    Day = 4
    Week = 5
    Month = 6


## Months
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


class Connector:
    _session: requests.Session = None
    _token: str = None
    _recent_data: str = None

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

                if diff > timedelta(hours=23):
                    print("Token older than 23h")
                    return None

                print(f"Token loaded from {datetime.fromtimestamp(data["ts"])}")
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
        self._session.headers = {"Authorization": f"Bearer {token}"}
        self._token = token

    def revalidate(self):
        res = self._post("Auth/validate")

        data = res.json()
        if not data["success"]:
            print("Error", data)
            return

        token = data["newToken"]
        self._session.headers = {"Authorization": f"Bearer {token}"}
        self._token = token

        print("Token saved l=", len(token))

    def _post(self, url: str, json: dict = {}):
        return self._session.post(f"{API_URL}/api/{url}", json=json)

    def get_accounts(self):
        res = self._post("account/search", {"onlyActiveAccounts": True})
        return res.json()["accounts"]

    def get_contracts(self, text="ES"):
        res = self._post("contract/search", {"live": LIVE_DATA, "searchText": text})
        return res.json()["contracts"]

    def find_contract(self, text="ES"):
        contracts = self.get_contracts(text)
        result = next((c for c in contracts if c["name"].startswith(text)), None)
        if result:
            return result["id"]

        raise ValueError(f"Contract {text} not found")

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
    ) -> pd.DataFrame:
        key = f"{contractId}_{times[0]}_{times[1]}_{tf[0]}_{tf[1].value}"
        csv_name = f"_data/{key}.csv"
        if self._recent_data == key or os.path.exists(csv_name):
            print("Loading from cache", csv_name)
            return pd.read_csv(csv_name)

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

        bars = res.json()["bars"]

        df = pd.DataFrame(bars)
        df["t"] = pd.to_datetime(df["t"])
        if LOCAL_TIMEZONE:
            df["t_original"] = df["t"]
            df["t"] = df["t"].dt.tz_convert(LOCAL_TIMEZONE)

        df.columns = ["time", "open", "high", "low", "close", "volume", "t_original"]

        if not os.path.exists("_data"):
            os.mkdir("_data")
        df.to_csv(csv_name, index=False)
        self._recent_data = key

        return df

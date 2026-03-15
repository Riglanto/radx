import requests
import os
from enum import Enum
from datetime import datetime, timedelta
import json

import pandas as pd
from dotenv import load_dotenv

from logger import create_logger

from config import API_URL, LIVE_DATA, LOCAL_TIMEZONE
from logger import create_logger
from strategies import ActionType

log = create_logger(__name__)


class TIME_UNITS(Enum):
    Second = 1
    Minute = 2
    Hour = 3
    Day = 4
    Week = 5
    Month = 6


# Months
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
    _account_id: str = None

    def __init__(self):
        self._account_id = os.getenv("TOPSTEP_ACCOUNT_ID")
        self._login()
        accounts = self.get_accounts()
        account = next((a for a in accounts if a["id"] == int(self._account_id)), None)
        if account:
            log.info(f"Using account >> {account['name']} << with id {account['id']}")

    def _store_token(self, token: str):
        with open(".token.json", "w") as outfile:
            json.dump(
                {
                    "ts": int(datetime.now().timestamp()),
                    "token": token,
                },
                outfile,
            )

            log.debug("Token saved l=", len(token))

    def _read_token(self):
        try:
            with open(".token.json", "r") as outfile:
                data = json.load(
                    outfile,
                )

                diff = datetime.now() - datetime.fromtimestamp(data["ts"])

                if diff > timedelta(hours=23):
                    log.debug("Token older than 23h, reloading...")
                    return None

                log.debug(f"Token loaded from {datetime.fromtimestamp(data["ts"])}")
                return data["token"]
        except:
            return None

    def _login(self):
        token = self._read_token()

        if not token:
            username = os.getenv("SECRET_USERNAME")
            if not username:
                raise Exception("Missing .env setup")
            res = requests.post(
                f"{API_URL}/api/Auth/loginKey",
                json={
                    "userName": username,
                    "apiKey": os.getenv("SECRET_API_KEY"),
                },
            )

            data = res.json()
            if not data["success"]:
                log.error("Error", data)
                return

            token = data["token"]
            self._store_token(token)

        self._session = requests.Session()
        self._session.headers = {"Authorization": f"Bearer {token}"}
        self._token = token

    def revalidate(self):
        data = self._post("Auth/validate")

        token = data["newToken"]
        self._session.headers = {"Authorization": f"Bearer {token}"}
        self._token = token

        log.debug("Token saved l=", len(token))

    def _post(self, url: str, json: dict = {}):
        api_url = f"{API_URL}/api/{url}"
        log.info(f"POST {API_URL} with {json}")
        res = self._session.post(api_url, json=json)
        if not res.ok:
            raise Exception(f"Error posting to {url}: {res.status_code}, {res.text}")

        json_res = res.json()
        if not json_res.get("success", False):
            log.error(json_res)
            raise Exception(
                f"Error in response from {url}: {json_res.get('errorCode', 'Unknown')} -> {json_res.get('errorMessage', 'No error message')}"
            )
        return json_res

    def get_accounts(self):
        data = self._post("account/search", {"onlyActiveAccounts": True})
        return data["accounts"]

    def get_contracts(self, text="ES"):
        data = self._post("contract/search", {"live": LIVE_DATA, "searchText": text})
        return data["contracts"]

    def find_contract(self, text="ES"):
        contracts = self.get_contracts(text)
        result = next((c for c in contracts if c["name"].startswith(text)), None)
        if result:
            return result["id"]

        raise ValueError(f"Contract {text} not found")

    def get_bars(
        self,
        symbol: str,
        contractId: str,
        times: tuple[str, str] = [
            datetime.now().isoformat(),
            datetime.now().isoformat(),
        ],
        tf: tuple[int, TIME_UNITS] = (3, TIME_UNITS.Minute),
        limit=1000000000,  # fetches all the data for contract
        includePartialBar=False,
    ) -> pd.DataFrame:
        main_key = f"{symbol}_{times[0]}_{times[1]}_{tf[0]}_{tf[1].value}"
        main_csv_name = f"_data/{main_key}.csv"

        def _load():
            if self._recent_data == main_key or os.path.exists(main_csv_name):
                log.debug("Loading from cache", main_csv_name)
                return pd.read_csv(main_csv_name)

            current = contractId.split(".")[-1]  # CON.F.US.EP.H26
            m, y = current[-3], int(current[-2:])
            months = ["H", "M", "U", "Z"]
            month_index = months.index(m)

            dfs = {}

            for i in range(0, 6):
                month = months[(month_index - i) % len(months)]
                contract = contractId[:-3] + month + str(y)

                if month == "H":
                    y -= 1

                key = f"{contract}_{times[0]}_{times[1]}_{tf[0]}_{tf[1].value}"
                csv_name = f"_data/{key}.csv"

                if self._recent_data == key or os.path.exists(csv_name):
                    log.debug("Loading from cache", csv_name)
                    dfs[contract] = pd.read_csv(csv_name)

                    continue

                data = self._post(
                    "History/retrieveBars",
                    {
                        "contractId": contract,
                        "live": LIVE_DATA,
                        "startTime": times[0],
                        "endTime": times[1],
                        "unitNumber": tf[0],
                        "unit": tf[1].value,
                        "limit": limit,
                        "includePartialBar": includePartialBar,
                    },
                )

                bars = data["bars"]

                if len(bars) == 0:
                    log.info(f"No bars returned from API for {contract}")
                    continue

                df = pd.DataFrame(bars)
                df.columns = ["time", "open", "high", "low", "close", "volume"]

                if not os.path.exists("_data"):
                    os.mkdir("_data")

                log.debug(f"Fetched {df.shape} for {contract}")

                df.to_csv(csv_name, index=False)

                dfs[contract] = df

            volumes = []

            for contract, df in dfs.items():
                v = df.groupby(pd.DatetimeIndex(df["time"]).normalize())["volume"].sum()
                volumes.append(v)
            volume = pd.concat(volumes, axis=1)
            volume.columns = dfs.keys()
            mxs = volume.eq(volume.max(axis=1), axis=0)
            volume["Most Liquid"] = mxs.dot(mxs.columns + ", ").str.rstrip(", ")

            for contract, df in dfs.items():
                dates = volume[volume["Most Liquid"] == contract].index
                dfs[contract] = df[pd.DatetimeIndex(df["time"]).normalize().isin(dates)]

            df = pd.concat(dfs)

            if len(df) == 0:
                raise ValueError("No data fetched for the given parameters.")

            return df

        df = _load()

        df["time"] = pd.to_datetime(df["time"])
        if LOCAL_TIMEZONE:
            df["t_original"] = df["time"]
            df["time"] = df["time"].dt.tz_convert(LOCAL_TIMEZONE)

        if not os.path.exists("_data"):
            os.mkdir("_data")

        df.sort_values(by="time", inplace=True)

        df.to_csv(main_csv_name, index=False)
        self._recent_data = main_key

        # Time index req for vbt plots
        df.set_index(df["time"], inplace=True)
        # data fetched, can we get more?

        return df

    def get_open_orders(self):
        data = self._post("Order/searchOpen", {"accountId": self._account_id})
        return data["orders"]

    def get_orders(self):
        data = self._post(
            "Order/search",
            {
                "accountId": self._account_id,
                "startTimestamp": (datetime.now() - timedelta(days=1)).isoformat(),
            },
        )
        return data["orders"]

    def get_open_positions(self):
        data = self._post("Position/searchOpen", {"accountId": self._account_id})
        return data["positions"]

    # Execution

    def close_positions(self, contract_id: str) -> bool:
        data = self._post("Position/closeContract", {"accountId": self._account_id, "contractId": contract_id})
        print(data)
        return data["success"]

    def place_order(self, contract_id: str, side: ActionType, size: int, stop_price: float, is_trail: bool) -> bool:
        # The order type:
        # 1 = Limit
        # 2 = Market
        # 4 = Stop
        # 5 = TrailingStop
        # 6 = JoinBid
        # 7 = JoinAsk
        data = self._post(
            "Order/place",
            {
                "accountId": self._account_id,
                "contractId": contract_id,
                "type": 2,  # Market order
                "side": 0 if side == ActionType.BUY else 1,
                "size": size,
                "stopLossBracket": {"ticks": 28, "type": 5 if is_trail else 2},  # or 5 for trail
            },
        )
        return data["success"]

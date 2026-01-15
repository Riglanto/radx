APP_NAME = "Radx"

API_URL = "https://api.topstepx.com"
MARKET_HUB_URL = "wss://rtc.topstepx.com/hubs/market"
USER_HUB_URL = "wss://rtc.topstepx.com/hubs/user"

LIVE_DATA = False
LOCAL_TIMEZONE = "Europe/Berlin"


# Params
PARAMS = {
    "stop": 33,
    "fast_ma": 20,
    "slow_ma": 55,
    "trading_hours": [0, 22],
}

BACKTESTING_PARAMS = {
    "stop": {
        "min": 20,
        "max": 40,
    },
    "fast_ma": {
        "min": 5,
        "max": 20,
    },
    "slow_ma": {
        "min": 30,
        "max": 60,
    },
    "trading_hours": [0, 22],
}

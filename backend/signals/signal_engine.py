
def generate_signal(df):
    if len(df) < 200:
        return {
            "signal": "WAIT",
            "reason": "Not enough market data."
        }

    latest = df.iloc[-1]

    values = [
        latest["ema_9"],
        latest["ema_21"],
        latest["ema_50"],
        latest["rsi"],
        latest["macd"],
        latest["macd_signal"]
    ]

    if any(value != value for value in values):
        return {
            "signal": "WAIT",
            "reason": "Indicator data is incomplete."
        }

    if (
        latest["ema_9"] > latest["ema_21"]
        and latest["ema_21"] > latest["ema_50"]
        and latest["rsi"] > 50
        and latest["macd"] > latest["macd_signal"]
    ):
        return {
            "signal": "BUY",
            "reason": "Bullish technical conditions."
        }

    if (
        latest["ema_9"] < latest["ema_21"]
        and latest["ema_21"] < latest["ema_50"]
        and latest["rsi"] < 50
        and latest["macd"] < latest["macd_signal"]
    ):
        return {
            "signal": "SELL",
            "reason": "Bearish technical conditions."
        }

    return {
        "signal": "WAIT",
        "reason": "Market conditions are not aligned."
    }

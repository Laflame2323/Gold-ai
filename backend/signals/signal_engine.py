
def generate_signal(df):
    if len(df) < 200:
        return {
            "signal": "WAIT",
            "reason": "Not enough market data."
        }

    latest = df.iloc[-1]

    buy_conditions = (
        latest["ema_9"] > latest["ema_21"]
        and latest["ema_21"] > latest["ema_50"]
        and latest["rsi"] > 50
        and latest["macd"] > latest["macd_signal"]
    )

    sell_conditions = (
        latest["ema_9"] < latest["ema_21"]
        and latest["ema_21"] < latest["ema_50"]
        and latest["rsi"] < 50
        and latest["macd"] < latest["macd_signal"]
    )

    if buy_conditions:
        return {
            "signal": "BUY",
            "reason": "Bullish technical conditions."
        }

    if sell_conditions:
        return {
            "signal": "SELL",
            "reason": "Bearish technical conditions."
        }

    return {
        "signal": "WAIT",
        "reason": "Trading conditions are not aligned."
    }

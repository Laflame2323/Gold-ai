
import pandas as pd


def calculate_indicators(df):
    df = df.copy()

    required = ["open", "high", "low", "close"]

    for column in required:
        if column not in df.columns:
            raise ValueError(f"Missing column: {column}")

    close = df["close"]

    # Moving averages
    df["ema_9"] = close.ewm(span=9, adjust=False).mean()
    df["ema_21"] = close.ewm(span=21, adjust=False).mean()
    df["ema_50"] = close.ewm(span=50, adjust=False).mean()
    df["ema_200"] = close.ewm(span=200, adjust=False).mean()

    # RSI
    change = close.diff()
    gain = change.clip(lower=0)
    loss = -change.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14, adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1/14, adjust=False
    ).mean()

    rs = avg_gain / avg_loss.where(avg_loss != 0)
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(
        span=9, adjust=False
    ).mean()

    # ATR
    previous_close = close.shift(1)

    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs()
    ], axis=1).max(axis=1)

    df["atr"] = true_range.ewm(
        alpha=1/14, adjust=False
    ).mean()

    return df

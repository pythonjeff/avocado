import pandas as pd
from sklearn.linear_model import LinearRegression


def strip_market_beta(
    stock_returns: pd.Series,
    market_returns: pd.Series,
    window: int = 252,
) -> pd.Series:
    """
    Remove market beta via rolling regression.
    Returns beta-adjusted (residual) returns.
    """
    df = pd.concat([stock_returns, market_returns], axis=1).dropna()
    df.columns = ["stock", "market"]

    residuals = pd.Series(index=df.index, dtype=float)

    for i in range(window, len(df)):
        y = df["stock"].iloc[i - window:i].values
        x = df["market"].iloc[i - window:i].values.reshape(-1, 1)

        reg = LinearRegression().fit(x, y)
        beta = reg.coef_[0]
        alpha = reg.intercept_

        predicted = alpha + beta * df["market"].iloc[i]
        residuals.iloc[i] = df["stock"].iloc[i] - predicted

    return residuals.dropna()


def macro_sensitivity_on_residuals(
    residuals: pd.Series,
    macro_changes: pd.DataFrame,
    window: int = 252,
) -> pd.DataFrame:
    """
    Rolling regression of beta-adjusted returns on macro changes.
    """
    df = pd.concat([residuals, macro_changes], axis=1).dropna()
    y_name = residuals.name

    rows = []

    for i in range(window, len(df)):
        y = df[y_name].iloc[i - window:i].values
        X = df.iloc[i - window:i, 1:].values

        reg = LinearRegression().fit(X, y)

        rows.append(
            {
                "date": df.index[i],
                "beta_real_yield": reg.coef_[0],
                "beta_nominal_10y": reg.coef_[1],
                "beta_breakeven_5y": reg.coef_[2],
            }
        )

    return pd.DataFrame(rows).set_index("date")

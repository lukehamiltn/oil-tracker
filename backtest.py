"""
Backtester: how would each strategy have done, with trading costs?

Results are split into two periods:
  - "Build"  2007-2016: the period ideas were developed on
  - "Test"   2017-now:  the honest check - a rule that only works in the
                        first period was probably luck

Run it with:   python backtest.py
"""

import numpy as np
import pandas as pd

import strategies as strat

START = "2007-01-01"           # features need ~1 year of history to warm up
SPLIT = "2017-01-01"
COST_PCT = 0.10                # % of the position lost each time we buy or sell
                               # (bid/ask spread + slippage on an oil ETF)
TRADING_DAYS = 252


def run(positions: pd.Series, prices: pd.Series, cost_pct: float = COST_PCT) -> pd.DataFrame:
    """Daily results of holding `positions` (decided at each close)."""
    next_day_return = prices.pct_change(fill_method=None).shift(-1)
    pos = positions.fillna(0)
    trades = pos.diff().abs().fillna(pos.abs())
    daily = pos * next_day_return - trades * cost_pct / 100
    out = pd.DataFrame({"position": pos, "return": daily.fillna(0)})
    # Shift so each return is dated on the day it was EARNED
    out["return"] = out["return"].shift(1).fillna(0)
    return out


def metrics(result: pd.DataFrame) -> dict:
    r = result["return"]
    equity = (1 + r).cumprod()
    years = len(r) / TRADING_DAYS
    total = equity.iloc[-1] - 1
    vol = r.std() * np.sqrt(TRADING_DAYS)
    entries = ((result["position"] > 0) & (result["position"].shift(1, fill_value=0) == 0)).sum()
    return {
        "total_return_pct": total * 100,
        "annual_return_pct": ((1 + total) ** (1 / years) - 1) * 100,
        "annual_volatility_pct": vol * 100,
        "sharpe": r.mean() / r.std() * np.sqrt(TRADING_DAYS) if r.std() > 0 else 0.0,
        "max_drawdown_pct": (equity / equity.cummax() - 1).min() * 100,
        "time_in_market_pct": (result["position"] > 0).mean() * 100,
        "trades": int(entries),
    }


def run_all(features: pd.DataFrame | None = None):
    """Backtest every strategy. Returns (results by strategy, metrics table)."""
    f = strat.build_features() if features is None else features
    f = f[f.index >= START]
    results, rows = {}, []
    for key, (label, rule) in strat.STRATEGIES.items():
        res = run(rule(f), f["price"])
        results[key] = res
        for period, part in [("Build 2007-2016", res[res.index < SPLIT]),
                             ("Test 2017-now", res[res.index >= SPLIT])]:
            rows.append({"strategy": key, "label": label, "period": period,
                         **metrics(part)})
    return results, pd.DataFrame(rows)


def main() -> None:
    _, table = run_all()
    show = table.set_index(["label", "period"])[
        ["annual_return_pct", "annual_volatility_pct", "sharpe",
         "max_drawdown_pct", "time_in_market_pct", "trades"]]
    show.columns = ["return/yr %", "volatility %", "Sharpe", "worst drop %",
                    "in market %", "trades"]
    pd.set_option("display.width", 140)
    print(f"Brent, costs {COST_PCT}% per trade\n")
    print(show.round(2).to_string())
    print("\nSharpe = return per unit of risk. Above ~0.5 is decent; compare each "
          "strategy to buy-and-hold in the SAME period.")


if __name__ == "__main__":
    main()

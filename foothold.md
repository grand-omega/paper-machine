# Foothold — Systematic trading strategies vs QQQM buy-and-hold

## Research question

Do simple systematic trading strategies — moving-average crossovers,
time-series momentum, volatility targeting, or mean-reversion signals —
produce **risk-adjusted returns (Sharpe ratio) distinguishably different**
from buy-and-hold of **QQQM** (Invesco NASDAQ-100 ETF) on real daily data
since QQQM's inception (2020-10-13)?

QQQM tracks the NASDAQ-100 with a low expense ratio (0.15%). It's a close
proxy for large-cap US tech — a regime known for strong momentum and secular
trend since inception. Both properties make it a meaningful — and arguably
hard — baseline to beat.

## Baseline

**QQQM buy-and-hold** from the first common date to the last available date
in the cached dataset. Compute:

- Total return
- Annualized return (CAGR)
- Annualized volatility (stdev of daily log returns × √252)
- Sharpe ratio (daily mean / daily stdev × √252) — assume 0% risk-free rate
- Max drawdown

Any candidate strategy is measured against these exact numbers.

## Data source

- **Primary:** `yfinance` (already installed as a project dep). Download
  QQQM daily OHLCV from first trading day to yesterday's close.
- **Cache:** first experiment that downloads must save to `data/qqqm.csv`.
  Subsequent experiments read the cache. This makes results reproducible
  across a single run.
- **No API keys required.** yfinance hits Yahoo Finance public endpoints.

**The user runs `just fetch-qqqm` once** (or the planner runs it from
the foothold's "First-time setup" section). That writes `data/qqqm.csv`
with these columns: `Date, Open, High, Low, Close, Volume, Dividends,
Stock Splits, Capital Gains`. Timezone is stripped from Date for clean
pandas parsing.

Read in experiments like:
```python
import pandas as pd
df = pd.read_csv("data/qqqm.csv", parse_dates=["Date"]).set_index("Date")
# df.Close is split/dividend-adjusted (auto_adjust=True was used on fetch)
# use df.Close.pct_change() for daily returns, etc.
```

`auto_adjust=True` at fetch time means `Close` is the total-return
adjusted series — use it directly; do not apply additional
dividend/split adjustments.

## Expected direction

Prior literature and efficient-market reasoning both suggest that after
adjusting for noise, most simple technical strategies on a broad-market ETF
fail to consistently beat buy-and-hold on a risk-adjusted basis — especially
in a regime (2020-present) with strong secular uptrend where being "flat"
is costly. Exceptions are plausible during drawdown windows (2022 bear
market) but in-sample edges should be heavily discounted.

A well-behaved result is most likely one of:

1. **No edge** — strategy Sharpe ≈ B&H Sharpe within Monte Carlo / bootstrap CIs
2. **Negative edge** — strategy drags due to missed upside + transaction-cost
   proxy (even 0.1% round-trip is non-trivial across many signals)
3. **Positive but weak** — small excess Sharpe (< 0.3) with wide bootstrap CIs
   overlapping zero

A result like "+1.5 Sharpe improvement in-sample" should raise immediate
suspicion of look-ahead bias, parameter overfitting, or survivorship
confounds — the reviewer must cross-check.

## Success criteria

- Experimenter runs at most **3 experiments** (planner decides which strategies)
- Each experiment has numeric outputs in `results.json`:
  `strategy_sharpe`, `baseline_sharpe`, `sharpe_diff`, `total_return_diff`,
  `max_drawdown`, `win_rate`, `number_of_trades`
- Paper's quantitative claims cross-check against SQLite to 2+ decimal places
- `paper/main.pdf` compiles cleanly (2-3 pages, 1 results table,
  optionally 1 figure)
- **Null or weak-negative results reported faithfully** — refusing to
  confabulate an edge is a feature

## Scope constraints

- Total budget: ~60 agent messages across all phases
- Per-experiment runtime: `< 60 seconds` (loading ~5y of daily bars +
  rolling-window backtest is fast)
- Data: QQQM only. **No other tickers, no multi-asset portfolios.**
- In-sample testing only — sample is limited (~5 years). Note this as a
  limitation in the paper.
- Paper: 2-3 pages, one results table, figure optional
- **Pre-installed deps:** `yfinance`, `pandas`, `numpy`, `matplotlib`, stdlib
- **Adding more is fine** — `uv add <pkg>` for widely-used scientific
  libraries (`scipy`, `statsmodels`, `seaborn`, `scikit-learn`, etc.) per
  `.claude/rules/python/conventions.md`. Don't hobble the analysis or
  figure quality to avoid adding a standard dep.

## Out of scope

- Multi-asset portfolios / pairs trading
- Options, leverage, shorting
- Intraday / high-frequency strategies
- Out-of-sample / walk-forward validation (sample too short)
- Transaction costs / slippage modeling (simplification; note as limitation)
- Taxes
- Comparison vs other broad-market ETFs (SPY, VOO, IVV) — stay on QQQM

## Planning notes (for the planner)

Reasonable candidate strategies, roughly in order of "widely reported to
possibly beat B&H on NASDAQ tech":

- **MA(50) / MA(200) golden-cross** — classic. Long when MA50 > MA200,
  flat otherwise.
- **12-1 month time-series momentum** — long when 12-month return
  (ex last month) is positive, flat otherwise. Standard Moskowitz/Ooi/
  Pedersen signal.
- **Volatility targeting** — scale exposure inversely to rolling 20d
  volatility, targeting 15% annualized. Always long, just with
  time-varying leverage / cash allocation.
- **Channel breakout (Donchian N=20)** — long on close > 20d high,
  flat on close < 20d low. Classic trend-following.
- **RSI(14) mean reversion** — long when RSI < 30 (oversold), flat
  otherwise. Expected to lose on a trending asset like QQQM.

Pick **3** that together probe different hypotheses (trend-following vs
mean-reversion vs vol-targeting). Cite specific references from the lit
review where possible.

Every proposal must specify:
- The signal definition (parameters included)
- The trading rule (long only, long/flat, long/short, etc.)
- The metric (Sharpe diff is primary; include max-drawdown and trade-count
  for context)
- Expected direction and magnitude

## Literature review hints (for the literature-reviewer)

`related_works/` may be empty — web-fetch these topics:

- "Brock Lakonishok LeBaron 1992 simple technical rules" (classic paper)
- "Jegadeesh Titman 1993 momentum returns stocks" (seminal momentum)
- "Moskowitz Ooi Pedersen 2012 time series momentum"
- "QQQ ETF backtest moving average"
- "volatility targeting improves Sharpe ratio"
- "technical analysis profitable efficient market"

Use:
- `WebFetch: https://scholar.google.com/scholar?q=<url-encoded-query>`
- `WebFetch: https://arxiv.org/search/?query=<url-encoded-query>`

Extract 5-8 key references. Note that most pre-2000 technical-analysis
findings have not replicated out-of-sample — cite this skeptically.

## Notes for the pipeline

- This is a **real research question with a real answer**. Unlike the null-
  hypothesis smoke test, the empirical result could legitimately land
  anywhere on the spectrum from "no edge" to "modest edge" — the goal is
  to measure honestly, not to confirm a preordained outcome.
- The sample (2020-present) is short and includes the 2022 bear market,
  2023 recovery, and strong 2024-2025 tech run. Each regime may favor
  different strategies. Note this.
- **In-sample overfitting is the #1 failure mode.** If the planner
  proposes sweeping across many parameter settings and picking the best,
  that's p-hacking. Prefer fixed canonical parameters (MA50/200 not a
  grid search).

## First-time setup (human does this before `just run`)

Make sure yfinance is installed and working:

```bash
cd ~/Desktop/new-paper-machine
uv sync                          # installs yfinance + pandas + numpy
mkdir -p data
uv run python -c "import yfinance as yf; print(yf.Ticker('QQQM').history(period='5d').tail())"
# should print last 5 daily bars
```

If that works, the pipeline can fetch data on its own during a run.

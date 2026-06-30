from __future__ import annotations

import argparse
import json

import pandas as pd

from .execution import ExecutionModel
from .hypotheses import HYPOTHESES
from .mt_loader import load_mt_export
from .pipeline import run_research


def main() -> None:
    parser = argparse.ArgumentParser(description="Run causal intraday hypothesis research.")
    parser.add_argument("--csv", required=True, help="Path to an intraday OHLCV CSV.")
    parser.add_argument("--format", choices=["standard", "mt"], default="standard")
    parser.add_argument("--hypothesis", default="liquidity_sweep_reversal", choices=sorted(HYPOTHESES))
    parser.add_argument("--horizon-bars", type=int, default=5)
    parser.add_argument("--commission-bps", type=float, default=0.25)
    parser.add_argument("--slippage-bps", type=float, default=0.50)
    parser.add_argument("--synthetic-spread-bps", type=float, default=2.0)
    parser.add_argument("--point-size", type=float, default=0.01)
    parser.add_argument("--keep-zero-spread", action="store_true")
    parser.add_argument("--trades-out", default=None, help="Optional CSV path for simulated trades.")
    args = parser.parse_args()

    meta = None
    if args.format == "mt":
        raw, meta = load_mt_export(
            args.csv,
            point_size=args.point_size,
            drop_zero_spread=not args.keep_zero_spread,
        )
    else:
        raw = pd.read_csv(args.csv)
    hypothesis = HYPOTHESES[args.hypothesis]()
    model = ExecutionModel(
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        horizon_bars=args.horizon_bars,
    )
    result = run_research(raw, hypothesis, model, synthetic_spread_bps=args.synthetic_spread_bps)

    payload = {
        "source": meta.__dict__ if meta else {"source_path": args.csv, "format": "standard"},
        "hypothesis": hypothesis.record.__dict__,
        "causality": result.causality.__dict__,
        "summary": result.summary.to_dict(),
        "expectancy_ci_95": result.expectancy_ci_95,
        "regime_breakdown": result.regime_breakdown.to_dict(orient="records"),
        "acceptance": result.acceptance.to_dict(),
    }
    print(json.dumps(payload, indent=2, default=str))

    if args.trades_out:
        result.trades.to_csv(args.trades_out, index=False)


if __name__ == "__main__":
    main()

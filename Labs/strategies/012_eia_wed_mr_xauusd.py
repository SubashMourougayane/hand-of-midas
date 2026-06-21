"""012 — EIA Wednesday MR on XAU_USD. Sprint 3 — same as #005 on Gold.

Note: EIA reports US OIL inventory, not Gold. Gold-on-EIA is a stretch
but Gold often reacts to USD via dollar-strength inverse, and EIA can
move USD. Including it for symmetry; expect weak / null result.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import importlib.util
_p = Path(__file__).resolve().parent / "005_eia_wednesday_meanrev_brent.py"
_spec = importlib.util.spec_from_file_location("eia_brent", _p)
_m = importlib.util.module_from_spec(_spec)
sys.modules["eia_brent"] = _m
_spec.loader.exec_module(_m)
generate_signals = _m.generate_signals
EIAConfig = _m.EIAConfig


def main() -> None:
    from Labs.shared.data import get_xauusd
    from Labs.shared.runner import run_strategy, print_report
    from Labs.shared.safeguards import lookahead_audit, random_baseline, print_safeguard_report

    print("Loading XAU_USD dev data...")
    data = get_xauusd()
    cfg = EIAConfig()
    fn = lambda d1_, h1_, m3_: generate_signals(d1_, h1_, m3_, cfg)
    r = run_strategy(fn, data)
    print_report("012 — EIA Wed MR on XAU_USD", r)
    la = lookahead_audit(fn, data)
    rb = random_baseline(data, n_trades=max(r.total_trades, 200))
    trusted = print_safeguard_report("012 — EIA Wed Gold", la, rb)
    print(f"  ==> {'TRUSTED' if trusted else 'UNTRUSTED'}")


if __name__ == "__main__":
    main()

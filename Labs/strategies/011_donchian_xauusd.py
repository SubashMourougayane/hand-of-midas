"""011 — Donchian Breakout on XAU_USD. Sprint 3 — same as #004 on Gold."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import importlib.util
_p = Path(__file__).resolve().parent / "004_donchian_breakout_brent.py"
_spec = importlib.util.spec_from_file_location("don_brent", _p)
_m = importlib.util.module_from_spec(_spec)
sys.modules["don_brent"] = _m
_spec.loader.exec_module(_m)
generate_signals = _m.generate_signals
DonchianConfig = _m.DonchianConfig


def main() -> None:
    from Labs.shared.data import get_xauusd
    from Labs.shared.runner import run_strategy, print_report
    from Labs.shared.safeguards import lookahead_audit, random_baseline, print_safeguard_report

    print("Loading XAU_USD dev data...")
    data = get_xauusd()
    cfg = DonchianConfig()
    fn = lambda d1_, h1_, m3_: generate_signals(d1_, h1_, m3_, cfg)
    r = run_strategy(fn, data)
    print_report("011 — Donchian Breakout on XAU_USD (20/10, RR=2)", r)
    la = lookahead_audit(fn, data)
    rb = random_baseline(data, n_trades=max(r.total_trades, 200))
    trusted = print_safeguard_report("011 — Donchian Gold", la, rb)
    print(f"  ==> {'TRUSTED' if trusted else 'UNTRUSTED'}")


if __name__ == "__main__":
    main()

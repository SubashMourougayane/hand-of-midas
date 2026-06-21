"""008 — ORB on XAU_USD (Gold). Sprint 3 — same concept as #001 on Gold.

Sources / why on gold: Gold has cleaner session boundaries than Brent.
London PM fix at 15:00 UTC, NY equity open at 13:30 UTC create real
institutional anchor points where breakout strategies *might* have edge.

We use the SAME ORB code as #001 — only the data source changes.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Reuse the core signal generator from #001
import importlib.util
_orb_path = Path(__file__).resolve().parent / "001_orb_brent.py"
_spec = importlib.util.spec_from_file_location("orb_brent", _orb_path)
_orb = importlib.util.module_from_spec(_spec)
sys.modules["orb_brent"] = _orb  # required so dataclass() inside the module can resolve
_spec.loader.exec_module(_orb)
generate_signals = _orb.generate_signals
ORBConfig = _orb.ORBConfig


def main() -> None:
    from Labs.shared.data import get_xauusd
    from Labs.shared.runner import run_strategy, print_report
    from Labs.shared.safeguards import (
        lookahead_audit, random_baseline, print_safeguard_report,
    )

    print("Loading XAU_USD dev data via sealed gateway...")
    d1, h1, m3 = get_xauusd()
    print(f"  D1={len(d1):,}  H1={len(h1):,}  M3={len(m3):,}")

    cfg = ORBConfig()  # same defaults as Brent
    fn = lambda d1_, h1_, m3_: generate_signals(d1_, h1_, m3_, cfg)

    print("\nRunning strategy on Gold...")
    result = run_strategy(fn, (d1, h1, m3))
    print_report("008 — ORB on XAU_USD (session=13:00 UTC, 60 min, RR=2.0)", result)

    print("Safeguards...")
    la = lookahead_audit(fn, (d1, h1, m3))
    rb = random_baseline((d1, h1, m3), n_trades=max(result.total_trades, 200))
    trusted = print_safeguard_report("008 — ORB Gold", la, rb)
    print()
    print(f"  ==> {'TRUSTED' if trusted else 'UNTRUSTED'}")


if __name__ == "__main__":
    main()

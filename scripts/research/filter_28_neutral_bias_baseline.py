"""V2: monkey-patch dict.get on the daily_bias dict by overriding the
str-default arg. Cleaner approach: subclass dict to override .get to always
return "neutral".

Even simpler: use unittest.mock.patch on the strategy module's `generate_signals`
function — but use the FULLY-QUALIFIED dotted path so the engine's local
reference is also captured.

Actually the simplest reliable approach: replace `daily_bias` arg's CLASS at
runtime to a special dict whose .get() always returns "neutral". We do this
by intercepting `dict()` constructor calls in the engine — but that's wild.

CORRECT approach: patch the strategy module's `generate_signals` function via
sys.modules — engines import via `from strategies.alpha_sweep import generate_signals`,
which resolves at import time. So patching sys.modules AFTER engine import is
too late.

THE CORRECT FIX: patch sys.modules BEFORE engine imports. Done by:
1. Wipe sys.modules
2. Pre-import strategies.alpha_sweep
3. Replace its generate_signals
4. THEN import engine — its `from strategies.alpha_sweep import generate_signals`
   will pull the patched version.

Easier: monkey-patch BUILT-IN dict.get on daily_bias instances. Use a
subclass that always returns "neutral" for `.get(date, ...)`.
"""
import sys
from collections import defaultdict
from contextlib import contextmanager


class NeutralBiasDict(dict):
    """A dict that always returns 'neutral' regardless of stored value."""
    def get(self, key, default=None):
        return "neutral"
    def __getitem__(self, key):
        return "neutral"


def fresh_import_clean(backend_path):
    sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")
    sys.path.insert(0, backend_path)
    for mod in list(sys.modules.keys()):
        if mod.startswith("backtest") or "strategies" in mod or mod == "config":
            del sys.modules[mod]
    from backtest import engine as eng
    return eng


def fresh_import_with_neutral_patch(backend_path, target_module_path):
    """Pre-load the strategy module, patch its generate_signals to inject
    NeutralBiasDict, THEN load engine so its import gets the patched ref."""
    sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")
    sys.path.insert(0, backend_path)
    # Wipe everything
    for mod in list(sys.modules.keys()):
        if mod.startswith("backtest") or "strategies" in mod or mod == "config":
            del sys.modules[mod]

    # Pre-import the strategy module
    import importlib
    target = importlib.import_module(target_module_path)
    original = target.generate_signals

    def wrapped(*args, **kwargs):
        # daily_bias is the LAST positional arg or "daily_bias" kwarg
        if "daily_bias" in kwargs:
            kwargs["daily_bias"] = NeutralBiasDict()
        elif args:
            args = list(args)
            args[-1] = NeutralBiasDict()
            args = tuple(args)
        return original(*args, **kwargs)

    target.generate_signals = wrapped

    # NOW load engine — its `from strategies.alpha_sweep import generate_signals`
    # will pull `wrapped` (since target.generate_signals is now `wrapped`)
    from backtest import engine as eng
    return eng, target, original


def fresh_import_with_inline_patch(backend_path):
    """Oil Micro: generate_signals is INLINE in engine.py. Patch on engine module."""
    sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")
    sys.path.insert(0, backend_path)
    for mod in list(sys.modules.keys()):
        if mod.startswith("backtest") or "strategies" in mod or mod == "config":
            del sys.modules[mod]
    from backtest import engine as eng
    original = eng.generate_signals

    def wrapped(*args, **kwargs):
        if "daily_bias" in kwargs:
            kwargs["daily_bias"] = NeutralBiasDict()
        elif args:
            args = list(args)
            args[-1] = NeutralBiasDict()
            args = tuple(args)
        return original(*args, **kwargs)

    eng.generate_signals = wrapped
    return eng, original


def status_buckets(trades):
    sl = sum(1 for t in trades if t.status.lower() in ("sl", "stop_loss"))
    tp = sum(1 for t in trades if t.status.lower() in ("tp", "take_profit"))
    be = sum(1 for t in trades if "be" in t.status.lower() or "break" in t.status.lower())
    other = len(trades) - sl - tp - be
    return sl, tp, be, other


def run_one(name, backend_path, kind, target_path=None):
    print(f"\n{'='*72}")
    print(f"  {name}")
    print(f"{'='*72}")

    # WITH BIAS (control)
    eng = fresh_import_clean(backend_path)
    res_w = eng.run_backtest()
    pnl_w = sum(t.pnl_sized for t in res_w.trades)
    n_w = len(res_w.trades)
    sl_w, tp_w, be_w, other_w = status_buckets(res_w.trades)
    wins_w = sum(1 for t in res_w.trades if t.pnl_sized > 0)
    wr_w = wins_w / max(1, n_w) * 100
    print(f"  WITH BIAS:    N={n_w:>5}  pnl>0: {wins_w:>4} (WR {wr_w:.1f}%)  SL={sl_w} TP={tp_w} BE={be_w} other={other_w}  P&L=${pnl_w:+.0f}")

    # NEUTRAL BIAS
    if kind == "import":
        eng, _, _ = fresh_import_with_neutral_patch(backend_path, target_path)
    elif kind == "inline":
        eng, _ = fresh_import_with_inline_patch(backend_path)
    res_n = eng.run_backtest()
    pnl_n = sum(t.pnl_sized for t in res_n.trades)
    n_n = len(res_n.trades)
    sl_n, tp_n, be_n, other_n = status_buckets(res_n.trades)
    wins_n = sum(1 for t in res_n.trades if t.pnl_sized > 0)
    wr_n = wins_n / max(1, n_n) * 100
    print(f"  NEUTRAL BIAS: N={n_n:>5}  pnl>0: {wins_n:>4} (WR {wr_n:.1f}%)  SL={sl_n} TP={tp_n} BE={be_n} other={other_n}  P&L=${pnl_n:+.0f}")
    print(f"  Δ:            N {n_n-n_w:+d}, P&L ${pnl_n-pnl_w:+.0f}")
    return {"sys": name, "n_w": n_w, "pnl_w": pnl_w, "wr_w": wr_w,
            "n_n": n_n, "pnl_n": pnl_n, "wr_n": wr_n}


if __name__ == "__main__":
    results = []
    # Gold Macro: backend.strategies.alpha_sweep imported via `from backend.strategies import alpha_sweep`
    results.append(run_one("Gold Macro", "/Users/subash/SUBASH/GoldDigger/backend",
                           "import", "backend.strategies.alpha_sweep"))
    # Gold Micro: backend.strategies.micro_alpha_sweep
    results.append(run_one("Gold Micro", "/Users/subash/SUBASH/GoldDigger/backend-micro",
                           "import", "backend.strategies.micro_alpha_sweep"))
    # Oil Macro: strategies.alpha_sweep (NO backend prefix)
    results.append(run_one("Oil Macro",  "/Users/subash/SUBASH/GoldDigger/backend-oil",
                           "import", "strategies.alpha_sweep"))
    # Oil Micro: inline
    results.append(run_one("Oil Micro",  "/Users/subash/SUBASH/GoldDigger/backend-oil-micro",
                           "inline"))

    print(f"\n{'='*86}")
    print("  SUMMARY: 21yr BT, $5k base/yr, all 4 systems, with vs without bias filter")
    print(f"{'='*86}")
    print(f"{'System':<14} {'WITH BIAS':<32} {'NEUTRAL':<32} {'Δ P&L':>14}")
    print("-" * 86)
    tot_w = 0; tot_n = 0
    for r in results:
        with_str = f"N={r['n_w']:>5} WR={r['wr_w']:>5.1f}% ${r['pnl_w']:>+10.0f}"
        neut_str = f"N={r['n_n']:>5} WR={r['wr_n']:>5.1f}% ${r['pnl_n']:>+10.0f}"
        delta = r['pnl_n'] - r['pnl_w']
        print(f"{r['sys']:<14} {with_str:<32} {neut_str:<32} ${delta:>+13.0f}")
        tot_w += r['pnl_w']; tot_n += r['pnl_n']
    print("-" * 86)
    print(f"{'TOTAL':<14} {' '*32} {' '*32} ${tot_n - tot_w:>+13.0f}")
    print(f"\n  21yr P&L with bias:    ${tot_w:>+12.0f}")
    print(f"  21yr P&L neutral:      ${tot_n:>+12.0f}")
    print(f"  Bias-filter contribution: ${tot_w - tot_n:>+12.0f} (positive = bias HELPS)")
    print(f"  Per year:              ${(tot_w - tot_n)/21:>+12.0f}")

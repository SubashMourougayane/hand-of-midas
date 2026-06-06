"""TEST 08: Mutation Guards — Tests specifically designed to catch common mutations.

Each test targets a specific mutation type that the static checks (test_01, test_06) miss.
These require RUNNING the code with real data to detect logic/value/type errors.
"""
import sys
import os
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-micro"))


class TestTradedSweepsStructure:
    """Catches M1: _traded_sweeps must have 'keys' as a set."""

    def test_traded_sweeps_has_keys_set(self):
        """_traded_sweeps['keys'] must be a set (for .add() to work)."""
        from scanner.scheduler import _traded_sweeps
        assert "keys" in _traded_sweeps, "_traded_sweeps missing 'keys'"
        assert isinstance(_traded_sweeps["keys"], set), \
            f"_traded_sweeps['keys'] is {type(_traded_sweeps['keys'])}, expected set"

    def test_traded_sweeps_has_date(self):
        from scanner.scheduler import _traded_sweeps
        assert "date" in _traded_sweeps, "_traded_sweeps missing 'date'"


class TestStartupCooldownLogic:
    """Catches M3: startup cooldown must actually block signals."""

    def test_cooldown_check_is_active(self):
        """The cooldown check must use the actual variable (not 'if False')."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        # Must contain real check, not bypassed
        assert "_startup_cooldown_until and now < _startup_cooldown_until" in source, \
            "Startup cooldown check is disabled or bypassed"


class TestPriceExtremesType:
    """Catches M4: _price_extremes must be a dict."""

    def test_price_extremes_is_dict(self):
        from scanner.live_engine import _price_extremes
        assert isinstance(_price_extremes, dict), \
            f"_price_extremes is {type(_price_extremes)}, expected dict"


class TestSLBufferValue:
    """Catches M5: sl_buffer must be reasonable ($1-$10 for Gold)."""

    def test_sl_buffer_range(self):
        from backend.config import ALPHA_SWEEP
        from config import MICRO_ALPHA_SWEEP
        for name, cfg in [("ALPHA_SWEEP", ALPHA_SWEEP), ("MICRO_ALPHA_SWEEP", MICRO_ALPHA_SWEEP)]:
            val = cfg["sl_buffer"]
            assert 0.5 <= val <= 10.0, \
                f"{name}['sl_buffer'] = {val} — out of valid range [0.5, 10.0]"


class TestTPFormulaDirection:
    """Catches M8: TP formula must put TP on the PROFITABLE side."""

    def test_short_tp_below_entry(self, gold_7d_h1, gold_7d_m3, daily_bias, seed_random):
        """All SHORT signals must have TP < entry."""
        np.random.seed(42)
        from backend.strategies import micro_alpha_sweep
        signals = micro_alpha_sweep.generate_signals(gold_7d_h1, gold_7d_m3, daily_bias)

        for s in [sig for sig in signals if sig.direction == "short"][:10]:
            assert s.tp < s.entry, \
                f"SHORT at {s.date}: TP ({s.tp}) >= entry ({s.entry}) — formula sign error!"

    def test_long_tp_above_entry(self, gold_7d_h1, gold_7d_m3, daily_bias, seed_random):
        """All LONG signals must have TP > entry."""
        np.random.seed(42)
        from backend.strategies import micro_alpha_sweep
        signals = micro_alpha_sweep.generate_signals(gold_7d_h1, gold_7d_m3, daily_bias)

        for s in [sig for sig in signals if sig.direction == "long"][:10]:
            assert s.tp > s.entry, \
                f"LONG at {s.date}: TP ({s.tp}) <= entry ({s.entry}) — formula sign error!"


class TestPriceExtremesKeys:
    """Catches M9: _price_extremes entries must use 'high' and 'low' keys."""

    def test_extremes_code_uses_correct_keys(self):
        """Code must reference 'high' and 'low' in BOTH creation AND reading."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/live_engine.py")
        with open(path) as f:
            source = f.read()

        # Creation: {"high": ..., "low": ...}
        assert '"high":' in source or "'high':" in source, \
            "_price_extremes creation doesn't use 'high' key"
        assert '"low":' in source or "'low':" in source, \
            "_price_extremes creation doesn't use 'low' key"

        # Reading: extremes["high"] or extremes['high']
        assert 'extremes["high"]' in source or "extremes['high']" in source, \
            "Exit estimation doesn't read extremes['high']"
        assert 'extremes["low"]' in source or "extremes['low']" in source, \
            "Exit estimation doesn't read extremes['low']"

        # CRITICAL: creation keys must match reading keys
        import re
        # Extract keys from dict literal: {"high": ..., "low": ...}
        creation_match = re.search(r'_price_extremes\[oid\]\s*=\s*\{(.+?)\}', source)
        creation_keys = set(re.findall(r'"(\w+)":', creation_match.group(1))) if creation_match else set()
        # Extract keys read via extremes["key"]
        reading_keys = set(re.findall(r'extremes\["(\w+)"\]', source))
        assert creation_keys and reading_keys, "Could not parse extremes keys"
        assert creation_keys == reading_keys, \
            f"Key mismatch! Created with {creation_keys}, read with {reading_keys}"


class TestFillModelTPFires:
    """Catches M10: TP must actually fire when price reaches it."""

    def test_tp_fills_on_exact_touch(self):
        """If bar low equals TP (SHORT), trade must exit at TP."""
        from backend.execution.fill_model import execute_trade

        # SHORT: entry=4520, tp=4510. Bar low = 4510 exactly.
        idx = pd.date_range("2026-01-01", periods=2, freq="3min", tz="UTC")
        data = pd.DataFrame({
            "bid_open": [4520, 4515], "bid_high": [4520, 4516],
            "bid_low": [4520, 4509], "bid_close": [4520, 4512],
            "ask_open": [4520.1, 4515.1], "ask_high": [4520.1, 4516.1],
            "ask_low": [4520.1, 4510.0], "ask_close": [4520.1, 4512.1],
            "volume": [100, 100],
        }, index=idx)

        result = execute_trade(
            df=data, bar_start=0, entry=4520, sl=4535, tp=4510,
            direction="short", max_bars=80, strategy="micro_alpha_sweep",
            use_break_even=False
        )
        assert result is not None, "No fill — TP should have triggered"
        assert result.exit_reason == "tp", f"Expected tp, got {result.exit_reason}"
        assert result.exit_price == 4510

    def test_tp_fills_when_exceeded(self):
        """If bar low goes PAST TP (SHORT), still fills at TP price."""
        from backend.execution.fill_model import execute_trade

        idx = pd.date_range("2026-01-01", periods=2, freq="3min", tz="UTC")
        data = pd.DataFrame({
            "bid_open": [4520, 4512], "bid_high": [4520, 4513],
            "bid_low": [4520, 4500], "bid_close": [4520, 4502],
            "ask_open": [4520.1, 4512.1], "ask_high": [4520.1, 4513.1],
            "ask_low": [4520.1, 4500.1], "ask_close": [4520.1, 4502.1],
            "volume": [100, 100],
        }, index=idx)

        result = execute_trade(
            df=data, bar_start=0, entry=4520, sl=4535, tp=4510,
            direction="short", max_bars=80, strategy="micro_alpha_sweep",
            use_break_even=False
        )
        assert result is not None
        assert result.exit_reason == "tp"
        assert result.exit_price == 4510  # NOT 4500 — fills at TP, not bar low


class TestConfigValueSanity:
    """Catches unreasonable config values that would produce broken trades."""

    def test_sweep_threshold_positive(self):
        from backend.config import ALPHA_SWEEP
        assert ALPHA_SWEEP["sweep_threshold"] > 0

    def test_min_sl_reasonable(self):
        from backend.config import ALPHA_SWEEP
        assert 1.0 <= ALPHA_SWEEP["min_sl"] <= 20.0

    def test_max_bars_reasonable(self):
        from backend.config import ALPHA_SWEEP
        assert 20 <= ALPHA_SWEEP["max_bars"] <= 200

    def test_be_trigger_between_0_and_1(self):
        from backend.config import ALPHA_SWEEP
        assert 0 < ALPHA_SWEEP["be_trigger_pct"] < 1.0

    def test_tp_structure_buffer_positive(self):
        from backend.config import ALPHA_SWEEP
        buf = ALPHA_SWEEP.get("tp_structure_buffer")
        assert buf is not None and buf > 0, f"tp_structure_buffer={buf} — must be positive"


class TestV2BiasDeployed:
    """Verify V2 bias (close position 80/20) is in live code, not V1 (body%)."""

    def test_scheduler_uses_combined_bias(self):
        """Micro scheduler must use Combined V1+V2 bias (Option A)."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        # Must have BOTH V1 and V2 components
        assert "body_pct" in source, "Combined bias missing V1 body_pct"
        assert "close_position" in source, "Combined bias missing V2 close_position"
        assert "v1_bias" in source, "Combined bias missing v1_bias variable"
        assert "v2_bias" in source, "Combined bias missing v2_bias variable"
        # Combined logic: either one triggers
        assert 'v1_bias == "bearish" or v2_bias == "bearish"' in source, \
            "Combined logic missing: either bearish → bearish"

    def test_macro_scheduler_uses_combined_bias(self):
        """Macro scheduler must also use Combined V1+V2."""
        path = os.path.join(PROJECT_ROOT, "backend/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        assert "v1_bias" in source, "Macro missing combined bias"
        assert "v2_bias" in source, "Macro missing combined bias"

    def test_combined_thresholds_correct(self):
        """V1: 0.4 body%, V2: 0.8/0.2 close position."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        assert "body_pct >= 0.4" in source, "V1 threshold 0.4 missing"
        assert "close_position >= 0.8" in source, "V2 bullish threshold 0.8 missing"
        assert "close_position <= 0.2" in source, "V2 bearish threshold 0.2 missing"

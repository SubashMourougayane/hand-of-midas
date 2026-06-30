"""Unit tests for SDR001Strategy."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.strategies import registry
from bt_engine.strategies.sdr001.generator import (
    SDR002_CLEAN_RULE,
    Zone,
    add_event_rule_features,
    add_orb_context,
)
from bt_engine.strategies.sdr001.strategy import SDR001Strategy, SDR002CleanStrategy


REPO_ROOT = Path(__file__).resolve().parents[5]
SLEEVE = REPO_ROOT / "research-baseline" / "results" / "base" / "base_sleeve1_trades.csv"


def _bar(ts: str, *, o=100, h=101, l=99, c=100.5, v=1000) -> Bar:
    return Bar("X", "M1", pd.Timestamp(ts), o, h, l, c, float(v))


def test_strategy_initial_state_empty() -> None:
    s = SDR001Strategy(symbol="X")
    st = s.initial_state()
    assert st.emitted_zone_ids == set()
    assert st.emitted_trade_keys == set()
    assert st.bar_rows == []
    assert s.sleeve1_filter is False


def test_strategy_warmup_no_emit_under_50_bars() -> None:
    s = SDR001Strategy(symbol="X")
    st = s.initial_state()
    history = pd.DataFrame()
    for i in range(5):
        ts = pd.Timestamp("2026-06-29T00:00:00Z") + pd.Timedelta(minutes=i)
        result = s.on_bar(st, _bar(ts.isoformat()), history)
        st = result.state
        assert result.new_orders == ()


@pytest.mark.skipif(not SLEEVE.is_file(), reason="sleeve1 ledger missing")
def test_strategy_loads_sleeve1_zone_ids() -> None:
    s = SDR001Strategy(symbol="X", sleeve1_filter=True)
    assert len(s._sleeve1_zone_ids) == 1032
    assert 39 in s._sleeve1_zone_ids  # first sleeve1 zone


def test_strategy_disables_sleeve1_filter_when_flag_off() -> None:
    s = SDR001Strategy(symbol="X", sleeve1_filter=False)
    assert s.sleeve1_filter is False
    assert s._sleeve1_zone_ids == set()


def test_strategy_rejects_replay_filter_in_live() -> None:
    s = SDR001Strategy(symbol="X", sleeve1_filter=True)
    with pytest.raises(ValueError, match="replay-only"):
        s.validate_for_live(timeframe="M1")


def test_strategy_rejects_non_m1_live_timeframe() -> None:
    s = SDR001Strategy(symbol="X", sleeve1_filter=False)
    with pytest.raises(ValueError, match="requires timeframe='M1'"):
        s.validate_for_live(timeframe="H1")


def test_strategy_rejects_orb_forward_flags_in_live() -> None:
    s = SDR001Strategy(symbol="X", sleeve1_filter=False, forward_rule=("orb_reversal",))
    with pytest.raises(ValueError, match="ORB forward flags are blocked"):
        s.validate_for_live(timeframe="M1")


def test_forward_rule_missing_flag_raises() -> None:
    s = SDR001Strategy(symbol="X", sleeve1_filter=False, forward_rule=("does_not_exist",))
    events = pd.DataFrame(
        {
            "entry_timestamp": [pd.Timestamp("2026-06-29T00:00:00Z")],
            "zone_id": [1],
        }
    )
    with pytest.raises(ValueError, match="missing SDR-001 feature flags"):
        s._apply_forward_rule(events)


def test_streaming_strategy_discovers_event_after_later_history(monkeypatch) -> None:
    def fake_generate(history):
        if len(history) < 2:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "zone_id": [99],
                "direction": ["demand"],
                "entry_timestamp": [pd.Timestamp("2026-06-29T00:01:00Z")],
                "entry_price": [101.0],
                "stop_price": [99.0],
                "risk_units": [2.0],
                "spec_name": ["fake"],
                "cost_r": [0.01],
                "trade_key": ["2026-06-29T00:01:00Z|demand|101.0"],
            }
        )

    monkeypatch.setattr("bt_engine.strategies.sdr001.strategy.generate_events_from_raw", fake_generate)
    s = SDR001Strategy(symbol="X", sleeve1_filter=False)
    st = s.initial_state()
    h1 = pd.DataFrame(
        [{"timestamp": pd.Timestamp("2026-06-29T00:00:00Z"), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}]
    )
    r1 = s.on_bar(st, _bar("2026-06-29T00:00:00Z"), h1)
    assert r1.new_orders == ()

    h2 = pd.concat(
        [
            h1,
            pd.DataFrame(
                [{"timestamp": pd.Timestamp("2026-06-29T00:01:00Z"), "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1}]
            ),
        ],
        ignore_index=True,
    )
    r2 = s.on_bar(r1.state, _bar("2026-06-29T00:01:00Z"), h2)
    assert len(r2.new_orders) == 1
    assert r2.new_orders[0].extra["zone_id"] == 99


def test_streaming_strategy_ignores_events_before_live_start(monkeypatch) -> None:
    def fake_generate(history):
        return pd.DataFrame(
            {
                "zone_id": [99],
                "direction": ["demand"],
                "entry_timestamp": [pd.Timestamp("2026-06-29T00:01:00Z")],
                "entry_price": [101.0],
                "stop_price": [99.0],
                "risk_units": [2.0],
                "spec_name": ["fake"],
                "cost_r": [0.01],
                "trade_key": ["2026-06-29T00:01:00Z|demand|101.0"],
            }
        )

    monkeypatch.setattr("bt_engine.strategies.sdr001.strategy.generate_events_from_raw", fake_generate)
    s = SDR001Strategy(
        symbol="X",
        sleeve1_filter=False,
        ignore_events_before=pd.Timestamp("2026-06-29T00:02:00Z"),
    )
    st = s.initial_state()
    history = pd.DataFrame(
        [{"timestamp": pd.Timestamp("2026-06-29T00:02:00Z"), "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1}]
    )
    result = s.on_bar(st, _bar("2026-06-29T00:02:00Z"), history)
    assert result.new_orders == ()


def test_event_rule_features_include_live_forward_flags() -> None:
    events = pd.DataFrame(
        {
            "entry_timestamp": [pd.Timestamp("2026-06-29T14:00:00Z")],
            "direction": ["demand"],
            "entry_price": [101.0],
            "cost_r": [0.04],
            "risk_units": [10.0],
            "bars_to_confirm": [1],
            "confirm_body_ratio": [0.5],
            "zone_width_atr": [0.8],
            "impulse_atr": [1.6],
            "base_body_ratio": [0.2],
        }
    )
    m5 = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-06-29T13:55:00Z"),
                pd.Timestamp("2026-06-29T14:00:00Z"),
            ],
            "atr": [2.0, 2.0],
            "ema8": [100.0, 200.0],
            "close": [101.0, 50.0],
            "close_location": [0.9, 0.1],
            "orb30_state": ["below", "above"],
            "orb15_state": ["below", "above"],
            "orb30_width": [1.0, 1.0],
        }
    )
    out = add_event_rule_features(events, m5)
    for flag in [
        "cost_le_0p05",
        "ema8_aligned",
        "base_body_low",
        "ny_main_or_overlap",
        "orb_reversal",
        "fast_confirm_1",
        "body_ge_45",
    ]:
        assert flag in out.columns
        assert bool(out[flag].iloc[0]) is True
    assert pd.Timestamp(out["entry_context_timestamp"].iloc[0]) == pd.Timestamp("2026-06-29T13:55:00Z")
    assert float(out["entry_ema8"].iloc[0]) == 100.0


def test_closed_m15_ema_uses_strictly_previous_closed_bar() -> None:
    events = pd.DataFrame(
        {
            "entry_timestamp": [pd.Timestamp("2026-06-29T14:15:00Z")],
            "direction": ["demand"],
            "entry_price": [101.0],
            "cost_r": [0.04],
            "risk_units": [10.0],
            "bars_to_confirm": [1],
            "confirm_body_ratio": [0.5],
            "zone_width_atr": [0.8],
            "impulse_atr": [1.6],
            "base_body_ratio": [0.2],
        }
    )
    m5 = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-06-29T14:10:00Z"),
                pd.Timestamp("2026-06-29T14:15:00Z"),
            ],
            "atr": [2.0, 2.0],
            "ema8": [90.0, 90.0],
            "close": [101.0, 101.0],
            "close_location": [0.9, 0.9],
            "orb30_state": ["missing", "missing"],
            "orb15_state": ["missing", "missing"],
            "orb30_width": [1.0, 1.0],
        }
    )
    m15 = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-06-29T14:00:00Z"),
                pd.Timestamp("2026-06-29T14:15:00Z"),
            ],
            "atr": [2.0, 2.0],
            "ema8": [100.0, 100.0],
            "close": [101.0, 99.0],
        }
    )

    out = add_event_rule_features(events, m5, m15=m15)

    assert pd.Timestamp(out["closed_m15_timestamp"].iloc[0]) == pd.Timestamp("2026-06-29T14:00:00Z")
    assert bool(out["closed_m15_ema8_aligned"].iloc[0]) is True
    assert bool(out["m15_boundary_entry"].iloc[0]) is True


def test_intraday_stack_24h_counts_only_known_prior_overlapping_zones() -> None:
    entry_ts = pd.Timestamp("2026-06-29T14:15:00Z")
    events = pd.DataFrame(
        {
            "zone_id": [1],
            "spec_name": ["m15_2c_1atr"],
            "entry_timestamp": [entry_ts],
            "direction": ["demand"],
            "upper": [101.0],
            "lower": [99.0],
            "entry_price": [101.0],
            "cost_r": [0.04],
            "risk_units": [10.0],
            "bars_to_confirm": [1],
            "confirm_body_ratio": [0.5],
            "zone_width_atr": [0.8],
            "impulse_atr": [1.6],
            "base_body_ratio": [0.2],
        }
    )
    m5 = pd.DataFrame(
        {
            "timestamp": [entry_ts - pd.Timedelta(minutes=5), entry_ts],
            "atr": [2.0, 2.0],
            "ema8": [100.0, 100.0],
            "close": [101.0, 101.0],
            "close_location": [0.9, 0.9],
            "orb30_state": ["missing", "missing"],
            "orb15_state": ["missing", "missing"],
            "orb30_width": [1.0, 1.0],
        }
    )
    prior_overlap = Zone(99, "30min", "m30_2c_1atr", "demand", 100.5, 98.5, entry_ts - pd.Timedelta(hours=2), entry_ts, entry_ts, entry_ts, 2, 1.5, 0.8, 0.2)
    future_overlap = Zone(100, "30min", "m30_2c_1atr", "demand", 100.5, 98.5, entry_ts + pd.Timedelta(minutes=30), entry_ts, entry_ts, entry_ts, 2, 1.5, 0.8, 0.2)
    own_zone = Zone(1, "15min", "m15_2c_1atr", "demand", 101.0, 99.0, entry_ts - pd.Timedelta(hours=1), entry_ts, entry_ts, entry_ts, 2, 1.5, 0.8, 0.2)

    out = add_event_rule_features(events, m5, stack_zones=[prior_overlap, future_overlap, own_zone])

    assert int(out["same_dir_intraday_overlap_24h"].iloc[0]) == 1
    assert bool(out["intraday_stack_24h"].iloc[0]) is True


def test_orb_context_is_missing_until_orb_window_is_closed() -> None:
    ts = pd.date_range("2026-06-29T13:00:00Z", periods=10, freq="5min")
    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "open": [100.0] * len(ts),
            "high": [101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 110.0, 111.0, 112.0, 113.0],
            "low": [99.0] * len(ts),
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 107.0, 108.0, 109.0, 110.0],
            "volume": [1.0] * len(ts),
        }
    )

    out = add_orb_context(frame)

    assert out.loc[out["timestamp"] < pd.Timestamp("2026-06-29T13:15:00Z"), "orb15_state"].eq("missing").all()
    assert out.loc[out["timestamp"] < pd.Timestamp("2026-06-29T13:30:00Z"), "orb30_state"].eq("missing").all()
    assert out.loc[out["timestamp"] == pd.Timestamp("2026-06-29T13:15:00Z"), "orb15_state"].iloc[0] != "missing"
    assert out.loc[out["timestamp"] == pd.Timestamp("2026-06-29T13:30:00Z"), "orb30_state"].iloc[0] != "missing"


def test_sdr002_clean_factory_uses_fixed_clean_rule() -> None:
    s = registry.get("sdr002_clean", symbol="X")
    assert isinstance(s, SDR002CleanStrategy)
    assert s.forward_rule == SDR002_CLEAN_RULE
    s.validate_for_live(timeframe="M1")

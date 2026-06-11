"""SignalDiff — pairwise comparison of BT and Live signal records.

Pairing strategy
----------------
We bucket each record by (timestamp_floored_to_minute, direction) and join
the two sides on that key. Same-minute, same-direction signals are treated
as the "same" event for parity purposes. Off-by-one-minute timestamp
mismatches show up in `timestamp_delta_secs` rather than as separate diffs
— but only if the same-minute bucketing finds a match.

If BT and Live disagree on the minute, both rows survive as
"signals_only_in_X" diffs and the diagnosis_hint flags the timing skew.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

from .extractor import SignalRecord


@dataclass
class SignalDiff:
    system: str
    timestamp: datetime
    in_backtest: bool
    in_live: bool
    direction: str | None
    direction_match: bool
    entry_price_delta: float | None
    sl_delta: float | None
    tp_delta: float | None
    timestamp_delta_secs: int | None
    bias_match: bool
    skip_reason_match: bool
    backtest_record: SignalRecord | None
    live_record: SignalRecord | None
    diagnosis_hint: str = ""

    def to_dict(self) -> dict:
        d = {
            "system": self.system,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "in_backtest": self.in_backtest,
            "in_live": self.in_live,
            "direction": self.direction,
            "direction_match": self.direction_match,
            "entry_price_delta": self.entry_price_delta,
            "sl_delta": self.sl_delta,
            "tp_delta": self.tp_delta,
            "timestamp_delta_secs": self.timestamp_delta_secs,
            "bias_match": self.bias_match,
            "skip_reason_match": self.skip_reason_match,
            "diagnosis_hint": self.diagnosis_hint,
            "backtest_record": self.backtest_record.to_dict() if self.backtest_record else None,
            "live_record": self.live_record.to_dict() if self.live_record else None,
        }
        return d


def _safe_sub(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def diff_signals(
    bt_records: list[SignalRecord],
    live_records: list[SignalRecord],
) -> list[SignalDiff]:
    """Produce a per-event diff list.

    Each unique (minute_floored_timestamp, direction) bucket yields one
    diff. A record that exists only on one side gets a diff with the other
    record set to None.
    """
    bt_by_key: dict[tuple, SignalRecord] = {}
    for r in bt_records:
        bt_by_key[r.comparison_key()] = r
    live_by_key: dict[tuple, SignalRecord] = {}
    for r in live_records:
        live_by_key[r.comparison_key()] = r

    all_keys = sorted(set(bt_by_key) | set(live_by_key), key=lambda k: (str(k[0]), k[1]))

    diffs: list[SignalDiff] = []
    for key in all_keys:
        bt = bt_by_key.get(key)
        live = live_by_key.get(key)
        in_bt = bt is not None
        in_live = live is not None

        # Pick a canonical timestamp + direction for the diff record. Prefer
        # whichever side actually has data; if both, both should agree on
        # direction (that's the bucket key) but timestamps may differ
        # within the minute.
        canonical_ts = (bt.timestamp if bt else None) or (live.timestamp if live else None)
        canonical_dir = (bt.direction if bt else None) or (live.direction if live else None)

        direction_match = (
            in_bt and in_live and bt.direction == live.direction
        )
        bias_match = (in_bt and in_live and bt.bias == live.bias) or (not in_bt and not in_live)
        skip_reason_match = (
            in_bt and in_live and (bt.skip_reason or "") == (live.skip_reason or "")
        )

        # Deltas (live - backtest, so positive means live higher)
        entry_delta = _safe_sub(live.entry_price if live else None,
                                bt.entry_price if bt else None)
        sl_delta = _safe_sub(live.sl_price if live else None,
                             bt.sl_price if bt else None)
        tp_delta = _safe_sub(live.tp_price if live else None,
                             bt.tp_price if bt else None)
        ts_delta_secs: int | None = None
        if in_bt and in_live and bt.timestamp and live.timestamp:
            ts_delta_secs = int((live.timestamp - bt.timestamp).total_seconds())

        diffs.append(SignalDiff(
            system=(bt.system if bt else live.system),
            timestamp=canonical_ts,
            in_backtest=in_bt,
            in_live=in_live,
            direction=canonical_dir,
            direction_match=direction_match,
            entry_price_delta=entry_delta,
            sl_delta=sl_delta,
            tp_delta=tp_delta,
            timestamp_delta_secs=ts_delta_secs,
            bias_match=bias_match,
            skip_reason_match=skip_reason_match,
            backtest_record=bt,
            live_record=live,
            diagnosis_hint=_initial_diagnosis_hint(bt, live, entry_delta, ts_delta_secs),
        ))
    return diffs


# Phase 5 diagnosis hint constants. Tunable per-system; defaults are
# generic and can be overridden by passing thresholds to diff_signals
# in the future (Phase 6+). Today the parity score uses sweep_threshold
# from the SystemConfig for normalization, so $1 entry-drift threshold
# below is a coarse fallback that triggers only on clearly-bad mismatches.
ENTRY_DELTA_HINT_THRESHOLD = 1.0   # USD/oz price drift to call out
TIMESTAMP_DELTA_HINT_THRESHOLD = 180   # seconds; matches M3 bar size


def _initial_diagnosis_hint(
    bt: SignalRecord | None,
    live: SignalRecord | None,
    entry_delta: float | None,
    ts_delta_secs: int | None,
) -> str:
    """Phase 5 hint heuristics (in priority order — first match wins).

    The five canonical hint shapes (reflected in
    docs/PARITY_HARNESS_PLAN.md) are:

      1. live_skipped_with_reason_X_backtest_did_not
         → Live has a skip_reason but BT took the signal. Indicates a
           live-only filter or guard fired.

      2. entry_price_delta_exceeds_X_dollars
         → Both took the signal but entry prices diverge by >$X.
           Usually slippage/fill-model mismatch.

      3. timestamp_delta_more_than_3min
         → Both took the signal but on different M3 bars (>180s).
           Live's polling cadence vs BT's bar-walking creates this.

      4. direction_flipped
         → Same minute bucket but opposite directions. Strategy LOGIC
           drift — most serious type of mismatch. Catastrophic gate
           covers >5 of these in one window.

      5. live_signaled_outside_backtest_window
         → BT didn't emit anything for this minute bucket but Live did.
           Most common drift type — captured by the existing
           live_only_* hints below.

    `agreement` is reserved for the clean case where everything matches.
    """
    # ----- both sides present -----
    if bt is not None and live is not None:
        if bt.direction != live.direction:
            return f"direction_flipped:bt={bt.direction},live={live.direction}"
        if entry_delta is not None and abs(entry_delta) > ENTRY_DELTA_HINT_THRESHOLD:
            return f"entry_price_delta_exceeds_{ENTRY_DELTA_HINT_THRESHOLD:.0f}_dollars:{entry_delta:+.2f}"
        if ts_delta_secs is not None and abs(ts_delta_secs) > TIMESTAMP_DELTA_HINT_THRESHOLD:
            return f"timestamp_delta_more_than_{TIMESTAMP_DELTA_HINT_THRESHOLD}_secs:{ts_delta_secs:+d}"
        return "agreement"

    # ----- only one side -----
    if bt is None and live is not None:
        if live.skip_reason:
            return f"live_skipped_with_reason_backtest_did_not:{live.skip_reason[:60]}"
        return "live_signaled_outside_backtest_window"
    if bt is not None and live is None:
        if bt.skip_reason:
            return f"backtest_skipped_with_reason_live_did_not:{bt.skip_reason[:60]}"
        return "backtest_signaled_outside_live_window"

    return "no_records"

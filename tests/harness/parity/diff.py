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


def _initial_diagnosis_hint(
    bt: SignalRecord | None,
    live: SignalRecord | None,
    entry_delta: float | None,
    ts_delta_secs: int | None,
) -> str:
    """Phase-1 placeholder hint generator. Phase 5 will expand this."""
    if bt is None and live is not None:
        if live.skip_reason:
            return f"live_only_with_skip_reason:{live.skip_reason[:50]}"
        return "live_only_signal_not_in_backtest"
    if bt is not None and live is None:
        return "backtest_only_signal_not_in_live"
    if bt is not None and live is not None:
        if bt.direction != live.direction:
            return f"direction_flipped:bt={bt.direction},live={live.direction}"
        if entry_delta is not None and abs(entry_delta) > 1.0:
            return f"entry_price_delta:{entry_delta:+.2f}"
        if ts_delta_secs is not None and abs(ts_delta_secs) > 180:
            return f"timestamp_delta_secs:{ts_delta_secs:+d}"
        return "agreement"
    return "no_records"

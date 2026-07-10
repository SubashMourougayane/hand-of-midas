"""CobraxState — streaming state for the COBRAX leg.

The research engine (research/cobrax/cobrax.py) is a VECTORIZED re-scanner: for each
bar it re-derives the most-recent sweep→MSS→FVG→OTE and its retrace fill. To reproduce
the SAME trades causally in a streaming engine we keep:

  * a rolling WINDOW of recent closed bars (enough history to detect a setup: the sweep
    scan looks back `sweep_lb`, the FVG forms up to `fvg_wait` after the MSS, and the
    retrace fill waits up to `retrace_wait` after the FVG),
  * the HTF-bias tracker,
  * a list of ARMED setups — a fully-confirmed sweep→MSS→FVG∩OTE waiting for price to
    retrace into the limit level (`elvl`); each fills AT MOST once,
  * `consumed_fill_keys` — dedup mirroring research's `used=set((fi, side))`,
  * `pending_entries` — orders whose fill was detected on the just-closed bar, finalized
    on the NEXT on_bar (next-bar-open queue; see strategy.py).

Causal contract: every field an armed setup carries (sweep extreme, MSS level, FVG
edges, OTE ratio) is computed from CLOSED bars strictly before the fill bar. No peek.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ...core.state import StrategyState
from .config import CobraxConfig
from .htf_bias import HtfBiasTracker


@dataclass
class ArmedSetup:
    """A confirmed sweep→MSS→FVG∩OTE setup waiting for its retrace-into-limit fill."""

    side: int  # +1 long | -1 short
    entry_level: float  # elvl — the FVG proximal (or CE) limit price
    stop: float  # SL past the swept extreme (or FVG far edge)
    sweep_ext: float  # the swept extreme price (fib anchor / stop basis)
    fvg_abs_idx: int  # absolute bar index of the FVG bar (fill must be strictly after)
    expiry_abs_idx: int  # last absolute bar index the retrace fill is allowed on
    setup_ts: pd.Timestamp  # MSS bar timestamp (signal ts, for causal audit)
    sweep_ts: pd.Timestamp
    fvg_ts: pd.Timestamp

    def key(self) -> tuple:
        # Dedup an armed setup so the same geometry isn't re-armed every bar.
        return (self.side, round(self.entry_level, 5), round(self.stop, 5), self.fvg_abs_idx)


@dataclass
class CobraxState(StrategyState):
    cfg: CobraxConfig = None  # type: ignore[assignment]

    bars_seen: int = 0
    """Absolute count of closed bars fed so far (monotonic index space)."""

    bias: HtfBiasTracker = None  # type: ignore[assignment]

    # Rolling window of recent CLOSED bars (parallel deques, newest last).
    win_ts: deque = field(default_factory=lambda: deque())
    win_o: deque = field(default_factory=lambda: deque())
    win_h: deque = field(default_factory=lambda: deque())
    win_l: deque = field(default_factory=lambda: deque())
    win_c: deque = field(default_factory=lambda: deque())
    win_idx: deque = field(default_factory=lambda: deque())  # absolute idx per window bar
    win_bias: deque = field(default_factory=lambda: deque())  # HTF bias at each bar's close

    armed: list[ArmedSetup] = field(default_factory=list)
    armed_keys: set = field(default_factory=set)

    # Dedup fills: (fill_abs_idx, side) — mirrors research used=set((fi, iside)).
    consumed_fill_keys: set = field(default_factory=set)

    # Fills detected on the just-closed bar, finalized to an Order on the NEXT on_bar.
    pending_entries: list = field(default_factory=list)

    def clone(self) -> "CobraxState":
        # Mutated in place + returned via StepResult, like FibV2State (perf).
        return self

    def clear_pending_entries(self) -> None:
        """Live warmup: drop entries queued during replay so only post-launch
        signals fire (mirrors FibV2State.clear_pending_entries)."""
        self.pending_entries = []

    # ----- window maintenance -----

    def push_bar(self, bar, *, bias: int, maxlen: int) -> int:
        """Append a closed bar + its HTF bias; trim to maxlen. Returns absolute idx."""
        idx = self.bars_seen
        self.win_ts.append(pd.Timestamp(bar.timestamp))
        self.win_o.append(float(bar.open))
        self.win_h.append(float(bar.high))
        self.win_l.append(float(bar.low))
        self.win_c.append(float(bar.close))
        self.win_idx.append(idx)
        self.win_bias.append(int(bias))
        self.bars_seen += 1
        while len(self.win_idx) > maxlen:
            for d in (self.win_ts, self.win_o, self.win_h, self.win_l,
                      self.win_c, self.win_idx, self.win_bias):
                d.popleft()
        return idx

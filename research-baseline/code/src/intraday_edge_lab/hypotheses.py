from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .features import previous_session_extremes


@dataclass(frozen=True)
class HypothesisRecord:
    name: str
    economic_rationale: str
    mathematical_definition: str
    participants: str
    causal_mechanism: str
    validation_plan: str
    robustness_plan: str
    falsification_plan: str
    failure_conditions: str


class Hypothesis:
    record: HypothesisRecord

    def generate_signals(self, frame: pd.DataFrame, features: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def parameter_variations(self) -> tuple[dict[str, float | int | bool], ...] | None:
        return None


class LiquiditySweepReversal(Hypothesis):
    record = HypothesisRecord(
        name="liquidity_sweep_reversal",
        economic_rationale=(
            "Prior session extremes concentrate stop orders and breakout liquidity. "
            "A sweep that fails back inside the prior range can reveal absorption rather than continuation."
        ),
        mathematical_definition=(
            "Short when high_t > prev_session_high, close_t < prev_session_high, "
            "close_location_t <= upper_rejection_threshold, and volume_z_20_t >= min_volume_z. "
            "Long is symmetric at prev_session_low."
        ),
        participants="Stop-loss traders, breakout initiators, liquidity providers, and short-horizon mean reversion desks.",
        causal_mechanism=(
            "Aggressive orders trigger resting liquidity beyond a visible extreme. "
            "If price fails to accept beyond that level by bar close, inventory pressure can revert toward value."
        ),
        validation_plan="Next-bar execution, cost-adjusted expectancy, side symmetry, monthly/yearly positivity.",
        robustness_plan="Perturb wick, volume, and horizon thresholds; segment by time of day and volatility regime.",
        falsification_plan="Shuffle sessions, reverse signs, test adjacent non-extreme levels, and require out-of-sample survival.",
        failure_conditions="Trend days, news shocks, wide spreads, persistent acceptance beyond the swept level.",
    )

    def __init__(
        self,
        min_volume_z: float = 0.5,
        upper_rejection_threshold: float = 0.35,
        lower_rejection_threshold: float = 0.65,
    ) -> None:
        self.min_volume_z = min_volume_z
        self.upper_rejection_threshold = upper_rejection_threshold
        self.lower_rejection_threshold = lower_rejection_threshold

    def generate_signals(self, frame: pd.DataFrame, features: pd.DataFrame) -> pd.Series:
        levels = previous_session_extremes(frame)
        close_location = features["close_location"]
        volume_z = features["volume_z_20"].replace([np.inf, -np.inf], np.nan)

        swept_high = (
            (frame["high"] > levels["prev_session_high"])
            & (frame["close"] < levels["prev_session_high"])
            & (close_location <= self.upper_rejection_threshold)
            & (volume_z >= self.min_volume_z)
        )
        swept_low = (
            (frame["low"] < levels["prev_session_low"])
            & (frame["close"] > levels["prev_session_low"])
            & (close_location >= self.lower_rejection_threshold)
            & (volume_z >= self.min_volume_z)
        )

        signals = pd.Series(0, index=frame.index, dtype=int)
        signals.loc[swept_high] = -1
        signals.loc[swept_low] = 1
        return signals

    def parameter_variations(self) -> tuple[dict[str, float], ...]:
        return (
            {"min_volume_z": 0.25, "upper_rejection_threshold": 0.30, "lower_rejection_threshold": 0.70},
            {"min_volume_z": 0.50, "upper_rejection_threshold": 0.35, "lower_rejection_threshold": 0.65},
            {"min_volume_z": 0.75, "upper_rejection_threshold": 0.40, "lower_rejection_threshold": 0.60},
        )


class MarkitTickSupportResistanceBreakout(Hypothesis):
    record = HypothesisRecord(
        name="markittick_sr_breakout",
        economic_rationale=(
            "Confirmed swing highs and lows can represent visible inventory reference points. "
            "A close through a stored level tests whether accepted value migrates beyond that reference."
        ),
        mathematical_definition=(
            "Confirm pivot highs/lows only after rightBars future bars have printed. Store the most recent "
            "levels. Go long when close_t crosses above stored resistance from below; go short when close_t "
            "crosses below stored support from above. Optional volume confirmation requires volume_t above "
            "its trailing moving average."
        ),
        participants="Breakout traders, liquidity providers around visible swing levels, and stop-order participants.",
        causal_mechanism=(
            "If a confirmed swing level concentrates orders, a closing cross may indicate enough aggressive "
            "flow to migrate value beyond the prior auction reference."
        ),
        validation_plan="Use only confirmed pivots, execute next bar, include bid/ask costs, and test persistence.",
        robustness_plan="Perturb pivot widths, stored-level count, decay, volume confirmation, and exit horizon.",
        falsification_plan="Test both continuation and inverse direction, out-of-sample periods, and cost stress.",
        failure_conditions="Range-bound chop, false breakouts, news gaps, wide spreads, or stale/overfit levels.",
    )

    def __init__(
        self,
        left_bars: int = 5,
        right_bars: int = 5,
        max_levels: int = 5,
        use_decay: bool = False,
        decay_bars: int = 50,
        use_volume_confirmation: bool = False,
        volume_ma_length: int = 20,
        direction: int = 1,
        use_structure_filter: bool = False,
        momentum_confirmation_bars: int = 0,
        min_confirmation_atr: float = 0.0,
    ) -> None:
        self.left_bars = left_bars
        self.right_bars = right_bars
        self.max_levels = max_levels
        self.use_decay = use_decay
        self.decay_bars = decay_bars
        self.use_volume_confirmation = use_volume_confirmation
        self.volume_ma_length = volume_ma_length
        self.direction = direction
        self.use_structure_filter = use_structure_filter
        self.momentum_confirmation_bars = momentum_confirmation_bars
        self.min_confirmation_atr = min_confirmation_atr

    def generate_signals(self, frame: pd.DataFrame, features: pd.DataFrame) -> pd.Series:
        high = frame["high"].astype(float)
        low = frame["low"].astype(float)
        close = frame["close"].astype(float)
        volume = frame["volume"].astype(float)
        window = self.left_bars + self.right_bars + 1

        confirmed_ph = high.shift(self.right_bars).where(high.shift(self.right_bars) == high.rolling(window).max())
        confirmed_pl = low.shift(self.right_bars).where(low.shift(self.right_bars) == low.rolling(window).min())
        if self.use_volume_confirmation:
            volume_ok = volume > volume.rolling(self.volume_ma_length, min_periods=self.volume_ma_length).mean()
        else:
            volume_ok = pd.Series(True, index=frame.index)

        close_values = close.to_numpy()
        atr_values = features["atr_14"].fillna(0.0).to_numpy()
        confirmed_ph_values = confirmed_ph.to_numpy()
        confirmed_pl_values = confirmed_pl.to_numpy()
        volume_ok_values = volume_ok.to_numpy(dtype=bool)
        resistance_levels: list[tuple[float, int]] = []
        support_levels: list[tuple[float, int]] = []
        signal_values = np.zeros(len(frame), dtype=np.int8)
        previous_pivot_high = np.nan
        previous_pivot_low = np.nan
        latest_high_structure = 0
        latest_low_structure = 0
        pending_direction = 0
        pending_level = np.nan
        pending_start = -1

        for i in range(len(frame)):
            if not np.isnan(confirmed_ph_values[i]):
                latest_high_structure = (
                    0 if np.isnan(previous_pivot_high) else (1 if confirmed_ph_values[i] > previous_pivot_high else -1)
                )
                previous_pivot_high = confirmed_ph_values[i]
                resistance_levels.insert(0, (float(confirmed_ph_values[i]), i - self.right_bars))
                resistance_levels = resistance_levels[: self.max_levels]
            if not np.isnan(confirmed_pl_values[i]):
                latest_low_structure = (
                    0 if np.isnan(previous_pivot_low) else (-1 if confirmed_pl_values[i] < previous_pivot_low else 1)
                )
                previous_pivot_low = confirmed_pl_values[i]
                support_levels.insert(0, (float(confirmed_pl_values[i]), i - self.right_bars))
                support_levels = support_levels[: self.max_levels]

            if i == 0:
                continue

            if pending_direction:
                expired = i - pending_start > self.momentum_confirmation_bars
                atr = atr_values[i]
                long_confirmed = (
                    pending_direction > 0
                    and close_values[i] > pending_level
                    and close_values[i] > close_values[i - 1]
                    and (atr <= 0 or (close_values[i] - close_values[i - 1]) / atr >= self.min_confirmation_atr)
                )
                short_confirmed = (
                    pending_direction < 0
                    and close_values[i] < pending_level
                    and close_values[i] < close_values[i - 1]
                    and (atr <= 0 or (close_values[i - 1] - close_values[i]) / atr >= self.min_confirmation_atr)
                )
                if long_confirmed or short_confirmed:
                    signal_values[i] = pending_direction
                    pending_direction = 0
                elif expired:
                    pending_direction = 0

            if not volume_ok_values[i]:
                continue

            res_breaks = 0
            res_level = np.nan
            kept_res: list[tuple[float, int]] = []
            for price, start_idx in resistance_levels:
                expired = self.use_decay and (i - start_idx > self.decay_bars)
                broken = close_values[i] > price and close_values[i - 1] <= price
                if broken:
                    res_breaks += 1
                    res_level = price if np.isnan(res_level) else max(res_level, price)
                elif not expired:
                    kept_res.append((price, start_idx))
            resistance_levels = kept_res

            sup_breaks = 0
            sup_level = np.nan
            kept_sup: list[tuple[float, int]] = []
            for price, start_idx in support_levels:
                expired = self.use_decay and (i - start_idx > self.decay_bars)
                broken = close_values[i] < price and close_values[i - 1] >= price
                if broken:
                    sup_breaks += 1
                    sup_level = price if np.isnan(sup_level) else min(sup_level, price)
                elif not expired:
                    kept_sup.append((price, start_idx))
            support_levels = kept_sup

            bullish_structure = latest_high_structure == 1 or latest_low_structure == 1
            bearish_structure = latest_high_structure == -1 or latest_low_structure == -1
            long_allowed = not self.use_structure_filter or bullish_structure
            short_allowed = not self.use_structure_filter or bearish_structure

            if res_breaks > sup_breaks:
                raw_direction = self.direction
                if raw_direction > 0 and not long_allowed:
                    continue
                if raw_direction < 0 and not short_allowed:
                    continue
                if self.momentum_confirmation_bars > 0:
                    pending_direction = raw_direction
                    pending_level = res_level
                    pending_start = i
                else:
                    signal_values[i] = raw_direction
            elif sup_breaks > res_breaks:
                raw_direction = -self.direction
                if raw_direction > 0 and not long_allowed:
                    continue
                if raw_direction < 0 and not short_allowed:
                    continue
                if self.momentum_confirmation_bars > 0:
                    pending_direction = raw_direction
                    pending_level = sup_level
                    pending_start = i
                else:
                    signal_values[i] = raw_direction

        return pd.Series(signal_values, index=frame.index, dtype=int)

    def parameter_variations(self) -> tuple[dict[str, float | int | bool], ...]:
        return (
            {"left_bars": 3, "right_bars": 3, "max_levels": 5, "direction": 1},
            {"left_bars": 5, "right_bars": 5, "max_levels": 5, "direction": 1},
            {"left_bars": 8, "right_bars": 8, "max_levels": 5, "direction": 1},
            {"left_bars": 5, "right_bars": 5, "max_levels": 3, "direction": 1},
            {"left_bars": 5, "right_bars": 5, "max_levels": 8, "direction": 1},
        )


class MarkitTickConfirmedBreakout(MarkitTickSupportResistanceBreakout):
    record = HypothesisRecord(
        name="markittick_sr_confirmed_breakout",
        economic_rationale=(
            "Raw support/resistance breaks are prone to fakeouts. Requiring volume, market-structure alignment, "
            "and a follow-through bar tests whether execution flow confirms momentum after the visible level breaks."
        ),
        mathematical_definition=(
            "Start from confirmed MarkitTick-style pivot levels. A resistance/support break creates a pending "
            "long/short candidate only when volume exceeds its trailing average and recent pivot structure agrees. "
            "Enter only if the next bar continues beyond the broken level in the breakout direction."
        ),
        participants="Breakout traders, stop-order participants, liquidity providers, and momentum execution flow.",
        causal_mechanism=(
            "A second bar of directional acceptance after a visible level break may indicate continuation demand "
            "rather than a one-bar stop run."
        ),
        validation_plan="Compare against raw breakout, execute next bar after confirmation, include full costs.",
        robustness_plan="Perturb pivot widths, level counts, volume filter, confirmation bars, and ATR threshold.",
        falsification_plan="Test inverse direction, recent and full histories, high/low volatility regimes, and cost stress.",
        failure_conditions="Delayed entries after exhausted moves, low-liquidity spikes, HTF opposition, and news gaps.",
    )

    def __init__(
        self,
        left_bars: int = 5,
        right_bars: int = 5,
        max_levels: int = 5,
        use_volume_confirmation: bool = True,
        volume_ma_length: int = 20,
        direction: int = 1,
        use_structure_filter: bool = True,
        momentum_confirmation_bars: int = 1,
        min_confirmation_atr: float = 0.0,
    ) -> None:
        super().__init__(
            left_bars=left_bars,
            right_bars=right_bars,
            max_levels=max_levels,
            use_volume_confirmation=use_volume_confirmation,
            volume_ma_length=volume_ma_length,
            direction=direction,
            use_structure_filter=use_structure_filter,
            momentum_confirmation_bars=momentum_confirmation_bars,
            min_confirmation_atr=min_confirmation_atr,
        )

    def parameter_variations(self) -> tuple[dict[str, float | int | bool], ...]:
        return (
            {
                "left_bars": 3,
                "right_bars": 3,
                "max_levels": 5,
                "use_volume_confirmation": True,
                "use_structure_filter": True,
                "momentum_confirmation_bars": 1,
            },
            {
                "left_bars": 5,
                "right_bars": 5,
                "max_levels": 5,
                "use_volume_confirmation": True,
                "use_structure_filter": True,
                "momentum_confirmation_bars": 1,
            },
            {
                "left_bars": 8,
                "right_bars": 8,
                "max_levels": 5,
                "use_volume_confirmation": True,
                "use_structure_filter": True,
                "momentum_confirmation_bars": 1,
            },
        )


class ZigZagClusterSupportResistanceBreakout(Hypothesis):
    record = HypothesisRecord(
        name="zigzag_cluster_sr_breakout",
        economic_rationale=(
            "Repeated reversals around a narrow price zone can identify an auction reference area where inventory "
            "has previously changed hands. A later close through that clustered zone tests whether value migrates."
        ),
        mathematical_definition=(
            "Confirm zig-zag highs/lows only after price retraces by a fixed percentage. Cluster confirmed reversal "
            "prices when at least N points fall within a price tolerance and time window. Go long on a close crossing "
            "above a clustered resistance level; go short on a close crossing below a clustered support level."
        ),
        participants="Swing traders, stop-order participants, breakout traders, and liquidity providers around repeated reversal zones.",
        causal_mechanism=(
            "A clustered reversal zone may hold resting orders and anchored inventory. A closing cross can reveal "
            "that aggressive flow has absorbed the zone."
        ),
        validation_plan="Confirm zig-zag levels only after retracement, execute next bar, include bid/ask costs.",
        robustness_plan="Perturb retracement size, cluster tolerance, minimum touches, and holding horizon.",
        falsification_plan="Test inverse signals, isolated single-touch levels, cross-instrument survival, and cost stress.",
        failure_conditions="Stale levels, trend exhaustion after breakout, sparse touch clusters, or high-spread bars.",
    )

    def __init__(
        self,
        min_retrace_pct: float = 0.25,
        cluster_tolerance_pct: float = 0.10,
        min_touches: int = 3,
        lookback_bars: int = 500,
        max_levels: int = 8,
        direction: int = 1,
        momentum_confirmation_bars: int = 0,
    ) -> None:
        self.min_retrace_pct = min_retrace_pct
        self.cluster_tolerance_pct = cluster_tolerance_pct
        self.min_touches = min_touches
        self.lookback_bars = lookback_bars
        self.max_levels = max_levels
        self.direction = direction
        self.momentum_confirmation_bars = momentum_confirmation_bars

    def _cluster_levels(self, reversals: list[tuple[int, float, int]], current_index: int) -> tuple[list[float], list[float]]:
        recent = [(idx, price, kind) for idx, price, kind in reversals if current_index - idx <= self.lookback_bars]
        if not recent:
            return ([], [])

        highs: list[float] = []
        lows: list[float] = []
        for _, price, kind in recent:
            cluster = [
                other_price
                for _, other_price, other_kind in recent
                if other_kind == kind and abs((other_price / price - 1.0) * 100.0) <= self.cluster_tolerance_pct
            ]
            if len(cluster) >= self.min_touches:
                level = float(np.mean(cluster))
                target = highs if kind > 0 else lows
                if all(abs((level / existing - 1.0) * 100.0) > self.cluster_tolerance_pct for existing in target):
                    target.append(level)

        highs = sorted(highs)[-self.max_levels :]
        lows = sorted(lows)[: self.max_levels]
        return (highs, lows)

    def generate_signals(self, frame: pd.DataFrame, features: pd.DataFrame) -> pd.Series:
        close = frame["close"].astype(float).to_numpy()
        signal_values = np.zeros(len(frame), dtype=np.int8)
        if len(close) < 3:
            return pd.Series(signal_values, index=frame.index, dtype=int)

        direction = 1
        extreme_price = close[0]
        extreme_index = 0
        reversals: list[tuple[int, float, int]] = []
        pending_direction = 0
        pending_level = np.nan
        pending_start = -1

        for i in range(1, len(close)):
            if pending_direction:
                expired = i - pending_start > self.momentum_confirmation_bars
                long_confirmed = pending_direction > 0 and close[i] > pending_level and close[i] > close[i - 1]
                short_confirmed = pending_direction < 0 and close[i] < pending_level and close[i] < close[i - 1]
                if long_confirmed or short_confirmed:
                    signal_values[i] = pending_direction
                    pending_direction = 0
                elif expired:
                    pending_direction = 0

            if direction > 0:
                if close[i] >= extreme_price:
                    extreme_price = close[i]
                    extreme_index = i
                elif (extreme_price - close[i]) / extreme_price * 100.0 >= self.min_retrace_pct:
                    reversals.append((i, extreme_price, 1))
                    direction = -1
                    extreme_price = close[i]
                    extreme_index = i
            else:
                if close[i] <= extreme_price:
                    extreme_price = close[i]
                    extreme_index = i
                elif (close[i] - extreme_price) / extreme_price * 100.0 >= self.min_retrace_pct:
                    reversals.append((i, extreme_price, -1))
                    direction = 1
                    extreme_price = close[i]
                    extreme_index = i

            resistance_levels, support_levels = self._cluster_levels(reversals, i)
            if i == 0:
                continue

            crossed_resistance = [
                level for level in resistance_levels if close[i] > level and close[i - 1] <= level
            ]
            crossed_support = [
                level for level in support_levels if close[i] < level and close[i - 1] >= level
            ]
            if crossed_resistance and not crossed_support:
                raw_direction = self.direction
                if self.momentum_confirmation_bars > 0:
                    pending_direction = raw_direction
                    pending_level = max(crossed_resistance)
                    pending_start = i
                else:
                    signal_values[i] = raw_direction
            elif crossed_support and not crossed_resistance:
                raw_direction = -self.direction
                if self.momentum_confirmation_bars > 0:
                    pending_direction = raw_direction
                    pending_level = min(crossed_support)
                    pending_start = i
                else:
                    signal_values[i] = raw_direction

        return pd.Series(signal_values, index=frame.index, dtype=int)

    def parameter_variations(self) -> tuple[dict[str, float | int | bool], ...]:
        return (
            {"min_retrace_pct": 0.20, "cluster_tolerance_pct": 0.08, "min_touches": 3, "lookback_bars": 400},
            {"min_retrace_pct": 0.25, "cluster_tolerance_pct": 0.10, "min_touches": 3, "lookback_bars": 500},
            {"min_retrace_pct": 0.35, "cluster_tolerance_pct": 0.12, "min_touches": 3, "lookback_bars": 650},
        )


class StructureBreakoutPullbackTrend(Hypothesis):
    record = HypothesisRecord(
        name="structure_breakout_pullback_trend",
        economic_rationale=(
            "A structural breakout followed by a controlled pullback can indicate value migration with a lower "
            "entry price than chasing the initial break. EMA/VWAP alignment and RSI slope test whether participation "
            "still supports continuation."
        ),
        mathematical_definition=(
            "Use confirmed pivots to form structural highs/lows. A close through the latest confirmed structure "
            "level creates a pending breakout. Enter only after price pulls back within an ATR-normalized distance "
            "of the broken level, EMA, or session VWAP, then resumes in the breakout direction with trend and RSI "
            "confirmation."
        ),
        participants="Breakout traders waiting for retests, trend followers, liquidity providers, and trapped countertrend traders.",
        causal_mechanism=(
            "The initial break reprices the auction; the pullback tests whether prior resistance/support has converted "
            "into accepted value. Resumption after the test indicates continuing execution pressure."
        ),
        validation_plan="Sequential causal state machine, next-bar execution, full costs, monthly/yearly/regime validation.",
        robustness_plan="Perturb pivot width, pullback depth, EMA length, RSI filter, volume filter, and setup expiry.",
        falsification_plan="Compare against immediate breakout entry, inverse signals, no-pullback variants, and cost stress.",
        failure_conditions="V-shaped moves with no pullback, deep failed retests, range-bound chop, and low-volume breaks.",
    )

    def __init__(
        self,
        left_bars: int = 5,
        right_bars: int = 5,
        ema_length: int = 20,
        pullback_atr: float = 0.75,
        breakout_rvol_min: float = 1.0,
        min_rsi_slope: float = 0.0,
        setup_expiry_bars: int = 30,
        direction: int = 1,
    ) -> None:
        self.left_bars = left_bars
        self.right_bars = right_bars
        self.ema_length = ema_length
        self.pullback_atr = pullback_atr
        self.breakout_rvol_min = breakout_rvol_min
        self.min_rsi_slope = min_rsi_slope
        self.setup_expiry_bars = setup_expiry_bars
        self.direction = direction

    def generate_signals(self, frame: pd.DataFrame, features: pd.DataFrame) -> pd.Series:
        high = frame["high"].astype(float)
        low = frame["low"].astype(float)
        close = frame["close"].astype(float)
        window = self.left_bars + self.right_bars + 1
        confirmed_ph = high.shift(self.right_bars).where(high.shift(self.right_bars) == high.rolling(window).max())
        confirmed_pl = low.shift(self.right_bars).where(low.shift(self.right_bars) == low.rolling(window).min())

        close_values = close.to_numpy()
        high_values = high.to_numpy()
        low_values = low.to_numpy()
        ph_values = confirmed_ph.to_numpy()
        pl_values = confirmed_pl.to_numpy()
        atr_values = features["atr_14"].fillna(0.0).to_numpy()
        rvol_values = features["rvol_20"].fillna(0.0).to_numpy()
        rsi_slope_values = features["rsi_14_slope_5"].fillna(0.0).to_numpy()
        ema_values = features[f"ema_{self.ema_length}"].to_numpy()
        ema_slope_values = features[f"ema_{self.ema_length}_slope_5"].fillna(0.0).to_numpy()
        vwap_values = features["session_vwap"].to_numpy()
        signal_values = np.zeros(len(frame), dtype=np.int8)

        last_resistance = np.nan
        last_support = np.nan
        pending_direction = 0
        pending_level = np.nan
        pending_start = -1
        pullback_seen = False

        for i in range(1, len(frame)):
            if not np.isnan(ph_values[i]):
                last_resistance = float(ph_values[i])
            if not np.isnan(pl_values[i]):
                last_support = float(pl_values[i])

            if pending_direction:
                expired = i - pending_start > self.setup_expiry_bars
                atr = atr_values[i]
                if atr <= 0:
                    continue
                ema = ema_values[i]
                vwap = vwap_values[i]
                if pending_direction > 0:
                    near_reference = (
                        low_values[i] <= pending_level + atr * self.pullback_atr
                        or (not np.isnan(ema) and low_values[i] <= ema + atr * self.pullback_atr)
                        or (not np.isnan(vwap) and low_values[i] <= vwap + atr * self.pullback_atr)
                    )
                    pullback_seen = pullback_seen or near_reference
                    trend_ok = close_values[i] > ema and ema_slope_values[i] >= 0
                    momentum_ok = rsi_slope_values[i] >= self.min_rsi_slope and close_values[i] > close_values[i - 1]
                    if pullback_seen and trend_ok and momentum_ok and close_values[i] > pending_level:
                        signal_values[i] = self.direction
                        pending_direction = 0
                        pullback_seen = False
                else:
                    near_reference = (
                        high_values[i] >= pending_level - atr * self.pullback_atr
                        or (not np.isnan(ema) and high_values[i] >= ema - atr * self.pullback_atr)
                        or (not np.isnan(vwap) and high_values[i] >= vwap - atr * self.pullback_atr)
                    )
                    pullback_seen = pullback_seen or near_reference
                    trend_ok = close_values[i] < ema and ema_slope_values[i] <= 0
                    momentum_ok = rsi_slope_values[i] <= -self.min_rsi_slope and close_values[i] < close_values[i - 1]
                    if pullback_seen and trend_ok and momentum_ok and close_values[i] < pending_level:
                        signal_values[i] = -self.direction
                        pending_direction = 0
                        pullback_seen = False

                if expired:
                    pending_direction = 0
                    pullback_seen = False

            if rvol_values[i] < self.breakout_rvol_min:
                continue

            bullish_break = not np.isnan(last_resistance) and close_values[i] > last_resistance and close_values[i - 1] <= last_resistance
            bearish_break = not np.isnan(last_support) and close_values[i] < last_support and close_values[i - 1] >= last_support
            if bullish_break:
                pending_direction = 1
                pending_level = last_resistance
                pending_start = i
                pullback_seen = False
            elif bearish_break:
                pending_direction = -1
                pending_level = last_support
                pending_start = i
                pullback_seen = False

        return pd.Series(signal_values, index=frame.index, dtype=int)

    def parameter_variations(self) -> tuple[dict[str, float | int | bool], ...]:
        return (
            {"left_bars": 3, "right_bars": 3, "ema_length": 20, "pullback_atr": 0.50, "breakout_rvol_min": 1.0},
            {"left_bars": 5, "right_bars": 5, "ema_length": 20, "pullback_atr": 0.75, "breakout_rvol_min": 1.0},
            {"left_bars": 8, "right_bars": 8, "ema_length": 34, "pullback_atr": 1.00, "breakout_rvol_min": 1.1},
        )


HYPOTHESES: dict[str, type[Hypothesis]] = {
    LiquiditySweepReversal.record.name: LiquiditySweepReversal,
    MarkitTickSupportResistanceBreakout.record.name: MarkitTickSupportResistanceBreakout,
    MarkitTickConfirmedBreakout.record.name: MarkitTickConfirmedBreakout,
    ZigZagClusterSupportResistanceBreakout.record.name: ZigZagClusterSupportResistanceBreakout,
    StructureBreakoutPullbackTrend.record.name: StructureBreakoutPullbackTrend,
}

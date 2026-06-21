"""Phase 0 chart viewer + marker — DAY-AT-A-TIME, M3 timeframe.

Shows ONE FULL DAY of BCO_USD M3 candles at a time (~480 bars per day,
trading hours only — weekends auto-skipped).

Hard rules:
- Reads data ONLY through the sealed gateway. No raw CSV access.
- Marks save to `manual_marks.jsonl` (append-only) as you click LONG/SHORT.
- The viewer refuses to advance past the development window's end date.
- No overlay of legacy strategy signals.

Usage:
    python R&D/phase_0_observations/viewer.py

Workflow:
    1. Use ◀ Day / Day ▶ buttons to navigate one day at a time. The
       title shows the date + day-of-week. Weekends are skipped.
    2. CLICK any M3 candle on the chart to SELECT it. The selected
       candle highlights yellow. The Selected: panel shows its
       timestamp.
    3. Type a confidence (1-5) in the Confidence box.
    4. Type free-text notes in the Notes box (optional).
    5. Click LONG ▲ for a bullish-reversal setup OR SHORT ▼ for
       bearish-reversal. The mark saves and selection clears.
    6. Existing marks show as ▲/▼ markers below their candles.

Buttons:
    ◀◀ Week  back 7 trading days
    ◀ Day    back 1 trading day
    Day ▶    forward 1 trading day
    Week ▶▶  forward 7 trading days
    HOME     jump to dev start (2019-09-26)
    END      jump to last viewable date
    LONG     save selected candle as long-reversal sweep
    SHORT    save selected candle as short-reversal sweep
    SKIP     clear selection without saving
    QUIT     close window (marks already saved)

Window is RESIZABLE and has a built-in matplotlib toolbar (zoom/pan/save).
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle
from matplotlib.widgets import Button, TextBox

# Sealed gateway — the only way this script can read price data.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_split import Phase, get_data

MARKS_FILE = Path(__file__).parent / "manual_marks.jsonl"
TARGET_MARKS = 20

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class Mark:
    sweep_ts: str
    direction: str  # "long" or "short"
    confidence: int
    notes: str
    marked_at: str
    instrument: str = "BCO_USD"
    timeframe: str = "M3"


def load_existing_marks() -> list[Mark]:
    if not MARKS_FILE.exists():
        return []
    out = []
    for line in MARKS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        out.append(Mark(**d))
    return out


def save_mark(mark: Mark) -> None:
    with MARKS_FILE.open("a") as f:
        f.write(json.dumps(asdict(mark)) + "\n")


def _plot_candles_categorical(ax, df: pd.DataFrame, title: str) -> None:
    """Trading-time x-axis: each candle gets 1 unit of width.
    Time labels show actual UTC time on every Nth bar.
    """
    ax.clear()
    if df.empty:
        ax.text(0.5, 0.5, "no data on this day (weekend?)",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=14, color="#888")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(title, fontsize=11)
        return

    n = len(df)
    width = 0.7

    for x, (_, row) in enumerate(df.iterrows()):
        o, h, l, c = row["mid_open"], row["mid_high"], row["mid_low"], row["mid_close"]
        color = "#26a69a" if c >= o else "#ef5350"
        # Wick
        ax.plot([x, x], [l, h], color=color, linewidth=0.6, zorder=1)
        # Body
        body_low = min(o, c)
        body_high = max(o, c)
        ax.add_patch(Rectangle(
            (x - width / 2, body_low),
            width,
            max(body_high - body_low, (h - l) * 0.001),
            facecolor=color, edgecolor=color, linewidth=0.4, zorder=2,
        ))

    # X-axis ticks: every full hour (= every 20 M3 bars)
    # 1-hour spacing keeps ~10-15 labels max regardless of session length.
    tick_positions = []
    tick_labels = []
    for i, ts in enumerate(df.index):
        if ts.minute == 0 and ts.second == 0:
            tick_positions.append(i)
            tick_labels.append(ts.strftime("%H:%M"))

    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=0, fontsize=9)

    ax.set_xlim(-0.5, n - 0.5)
    ymin = df["mid_low"].min()
    ymax = df["mid_high"].max()
    ypad = (ymax - ymin) * 0.06
    ax.set_ylim(ymin - ypad, ymax + ypad)
    ax.tick_params(axis="y", labelsize=9)
    ax.grid(True, alpha=0.3, linestyle="--", linewidth=0.5)
    ax.set_title(title, fontsize=12, weight="bold")
    ax.set_xlabel("Time (UTC)", fontsize=9)
    ax.set_ylabel("BCO_USD price", fontsize=9)


class Viewer:
    def __init__(self) -> None:
        print("Loading development data via sealed gateway...")
        d1, h1, m3 = get_data(Phase.DEVELOPMENT, "BCO_USD")
        print(f"  D1 bars: {len(d1):,}")
        print(f"  H1 bars: {len(h1):,}")
        print(f"  M3 bars: {len(m3):,}  ({m3.index[0]} → {m3.index[-1]})")
        self.m3 = m3

        # Available trading dates (skip weekends)
        all_dates = sorted(set(m3.index.normalize().unique()))
        self.trading_dates = [d for d in all_dates if d.weekday() < 5]
        print(f"  Trading days: {len(self.trading_dates)}")

        self.marks = load_existing_marks()
        print(f"  Existing marks: {len(self.marks)} / target {TARGET_MARKS}")

        # State
        self.day_idx = 0  # index into self.trading_dates
        self.selected_ts: pd.Timestamp | None = None
        self.confidence_str = "3"
        self.notes_str = ""

        # ── Bigger window ────────────────────────────────────────────────
        self.fig = plt.figure(figsize=(18, 9.5))
        try:
            mgr = plt.get_current_fig_manager()
            # Try to maximize window (works on most matplotlib backends)
            mgr.window.geometry("1800x1000")
        except Exception:
            pass

        # Chart area — 75% of width
        self.ax = self.fig.add_axes([0.05, 0.22, 0.70, 0.70])

        # Status bar (top)
        self.status_text = self.fig.text(0.05, 0.96, "", fontsize=10, color="#333", weight="bold")

        # ── Bottom navigation bar ────────────────────────────────────────
        btn_h = 0.05
        btn_y = 0.08
        btn_w = 0.07
        x = 0.05
        gap = 0.005
        self.btn_back7 = Button(self.fig.add_axes([x, btn_y, btn_w, btn_h]), "◀◀ Week")
        x += btn_w + gap
        self.btn_back1 = Button(self.fig.add_axes([x, btn_y, btn_w, btn_h]), "◀ Day")
        x += btn_w + gap
        self.btn_fwd1 = Button(self.fig.add_axes([x, btn_y, btn_w, btn_h]), "Day ▶")
        x += btn_w + gap
        self.btn_fwd7 = Button(self.fig.add_axes([x, btn_y, btn_w, btn_h]), "Week ▶▶")
        x += btn_w + gap
        self.btn_home = Button(self.fig.add_axes([x, btn_y, btn_w, btn_h]), "HOME")
        x += btn_w + gap
        self.btn_end = Button(self.fig.add_axes([x, btn_y, btn_w, btn_h]), "END")

        self.btn_back7.on_clicked(lambda e: self._jump_days(-7))
        self.btn_back1.on_clicked(lambda e: self._jump_days(-1))
        self.btn_fwd1.on_clicked(lambda e: self._jump_days(1))
        self.btn_fwd7.on_clicked(lambda e: self._jump_days(7))
        self.btn_home.on_clicked(lambda e: self._jump_to(0))
        self.btn_end.on_clicked(lambda e: self._jump_to(len(self.trading_dates) - 1))

        # Date jump box
        self.fig.text(0.55, 0.10, "Jump to date (YYYY-MM-DD):", fontsize=9)
        ax_jump = self.fig.add_axes([0.69, 0.085, 0.07, 0.04])
        self.tb_jump = TextBox(ax_jump, "", initial="")
        self.tb_jump.on_submit(self._on_jump_submit)

        # ── Right-side panel ─────────────────────────────────────────────
        right_x = 0.78
        right_w = 0.18

        self.fig.text(right_x, 0.90, "Selected candle:", fontsize=10, weight="bold")
        self.selected_text = self.fig.text(right_x, 0.87, "(none — click a candle)",
                                            fontsize=9, color="#888")

        self.fig.text(right_x, 0.80, "Confidence (1-5):", fontsize=10)
        ax_conf = self.fig.add_axes([right_x, 0.76, right_w, 0.04])
        self.tb_confidence = TextBox(ax_conf, "", initial="3")
        self.tb_confidence.on_text_change(self._on_confidence_change)

        self.fig.text(right_x, 0.68, "Notes (what makes it look real):", fontsize=10)
        ax_notes = self.fig.add_axes([right_x, 0.61, right_w, 0.05])
        self.tb_notes = TextBox(ax_notes, "", initial="")
        self.tb_notes.on_text_change(self._on_notes_change)

        # Mark buttons
        ax_long = self.fig.add_axes([right_x, 0.50, right_w * 0.48, 0.07])
        self.btn_long = Button(ax_long, "LONG ▲", color="#a5d6a7", hovercolor="#81c784")
        self.btn_long.on_clicked(lambda e: self._save_mark("long"))
        ax_short = self.fig.add_axes([right_x + right_w * 0.52, 0.50, right_w * 0.48, 0.07])
        self.btn_short = Button(ax_short, "SHORT ▼", color="#ef9a9a", hovercolor="#e57373")
        self.btn_short.on_clicked(lambda e: self._save_mark("short"))

        ax_skip = self.fig.add_axes([right_x, 0.42, right_w, 0.05])
        self.btn_skip = Button(ax_skip, "Skip / Clear selection")
        self.btn_skip.on_clicked(lambda e: self._clear_selection())

        ax_quit = self.fig.add_axes([right_x, 0.08, right_w, 0.05])
        self.btn_quit = Button(ax_quit, "QUIT", color="#bdbdbd", hovercolor="#9e9e9e")
        self.btn_quit.on_clicked(lambda e: plt.close(self.fig))

        help_text = (
            "How to mark:\n"
            "  1. Navigate days with ◀/▶ buttons\n"
            "  2. CLICK any M3 candle\n"
            "  3. Type confidence (1=unsure, 5=textbook)\n"
            "  4. Type notes (optional)\n"
            "  5. Click LONG or SHORT\n\n"
            "Marks save to:\n"
            "  manual_marks.jsonl"
        )
        self.fig.text(right_x, 0.16, help_text, fontsize=8, color="#555",
                      verticalalignment="bottom")

        self.fig.canvas.mpl_connect("button_press_event", self._on_click)

        self._redraw()

    # ── Day data ──────────────────────────────────────────────────────────

    def _current_day_df(self) -> pd.DataFrame:
        """M3 bars for the currently selected trading day."""
        if not self.trading_dates:
            return self.m3.iloc[:0]
        day = self.trading_dates[self.day_idx]
        next_day = day + pd.Timedelta(days=1)
        return self.m3[(self.m3.index >= day) & (self.m3.index < next_day)]

    def _current_date_label(self) -> str:
        if not self.trading_dates:
            return "(no data)"
        day = self.trading_dates[self.day_idx]
        wd = DAY_LABELS[day.weekday()]
        return f"{day.strftime('%Y-%m-%d')} ({wd})"

    # ── Navigation ────────────────────────────────────────────────────────

    def _jump_days(self, n: int) -> None:
        new_idx = max(0, min(self.day_idx + n, len(self.trading_dates) - 1))
        if new_idx != self.day_idx:
            self.day_idx = new_idx
            self._clear_selection_silent()
            self._redraw()

    def _jump_to(self, idx: int) -> None:
        new_idx = max(0, min(idx, len(self.trading_dates) - 1))
        if new_idx != self.day_idx:
            self.day_idx = new_idx
            self._clear_selection_silent()
            self._redraw()

    def _on_jump_submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        try:
            target = pd.Timestamp(text, tz="UTC").normalize()
        except (ValueError, TypeError):
            self.status_text.set_text(f"⚠ Bad date '{text}'. Use YYYY-MM-DD.")
            self.status_text.set_color("#c62828")
            self.fig.canvas.draw_idle()
            return
        # Find nearest trading day at or after target
        for i, d in enumerate(self.trading_dates):
            if d >= target:
                self.day_idx = i
                self._clear_selection_silent()
                self._redraw()
                return
        self.status_text.set_text(f"⚠ Date {text} is past dev window end.")
        self.status_text.set_color("#c62828")
        self.fig.canvas.draw_idle()

    # ── Click ─────────────────────────────────────────────────────────────

    def _on_click(self, event) -> None:
        if event.inaxes != self.ax:
            return
        if event.xdata is None:
            return
        df = self._current_day_df()
        if df.empty:
            return
        bar_idx = int(round(event.xdata))
        if bar_idx < 0 or bar_idx >= len(df):
            return
        self.selected_ts = df.index[bar_idx]
        self.selected_text.set_text(self.selected_ts.strftime("%Y-%m-%d %H:%M:%S UTC"))
        self.selected_text.set_color("#1976d2")
        self._redraw()

    def _clear_selection(self) -> None:
        self._clear_selection_silent()
        self._redraw()

    def _clear_selection_silent(self) -> None:
        self.selected_ts = None
        self.selected_text.set_text("(none — click a candle)")
        self.selected_text.set_color("#888")
        self.tb_notes.set_val("")

    # ── Inputs ────────────────────────────────────────────────────────────

    def _on_confidence_change(self, text: str) -> None:
        self.confidence_str = text

    def _on_notes_change(self, text: str) -> None:
        self.notes_str = text

    # ── Save ──────────────────────────────────────────────────────────────

    def _save_mark(self, direction: str) -> None:
        if self.selected_ts is None:
            self.status_text.set_text(
                "⚠ Click a candle first, then click LONG or SHORT."
            )
            self.status_text.set_color("#c62828")
            self.fig.canvas.draw_idle()
            return
        try:
            confidence = int(self.confidence_str)
        except ValueError:
            self.status_text.set_text("⚠ Confidence must be an integer 1-5.")
            self.status_text.set_color("#c62828")
            self.fig.canvas.draw_idle()
            return
        if confidence not in (1, 2, 3, 4, 5):
            self.status_text.set_text("⚠ Confidence must be 1-5.")
            self.status_text.set_color("#c62828")
            self.fig.canvas.draw_idle()
            return

        mark = Mark(
            sweep_ts=self.selected_ts.isoformat(),
            direction=direction,
            confidence=confidence,
            notes=self.notes_str,
            marked_at=datetime.now(timezone.utc).isoformat(),
        )
        save_mark(mark)
        self.marks.append(mark)
        print(f"  ✓ Saved {direction.upper()} @ {self.selected_ts}  "
              f"(conf={confidence}, notes='{self.notes_str}')   "
              f"Total: {len(self.marks)}/{TARGET_MARKS}")

        self._clear_selection_silent()
        self._redraw()

    # ── Render ────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        df = self._current_day_df()
        date_label = self._current_date_label()
        title = f"BCO_USD M3   —   {date_label}"
        _plot_candles_categorical(self.ax, df, title)

        # Selection highlight
        if self.selected_ts is not None and not df.empty and self.selected_ts in df.index:
            bar_idx = df.index.get_loc(self.selected_ts)
            bar = df.loc[self.selected_ts]
            pad = (df["mid_high"].max() - df["mid_low"].min()) * 0.04
            self.ax.add_patch(Rectangle(
                (bar_idx - 0.45, bar["mid_low"] - pad),
                0.9,
                (bar["mid_high"] - bar["mid_low"]) + pad * 2,
                facecolor="none", edgecolor="#fbc02d", linewidth=2.5,
                linestyle="--", zorder=10,
            ))

        # Existing marks for THIS day
        for m in self.marks:
            ts = pd.Timestamp(m.sweep_ts)
            if not df.empty and ts in df.index:
                bar_idx = df.index.get_loc(ts)
                bar = df.loc[ts]
                span = df["mid_high"].max() - df["mid_low"].min()
                marker_y = bar["mid_low"] - span * 0.04
                color = "#1565c0" if m.direction == "long" else "#b71c1c"
                marker = "^" if m.direction == "long" else "v"
                self.ax.scatter([bar_idx], [marker_y], marker=marker, s=140,
                                color=color, zorder=8, edgecolors="black", linewidths=0.7)

        # Status line
        progress_pct = (self.day_idx + 1) / max(1, len(self.trading_dates)) * 100
        status = (
            f"Day: {date_label}   "
            f"|   {self.day_idx + 1} / {len(self.trading_dates)}  ({progress_pct:.1f}%)   "
            f"|   Marks: {len(self.marks)} / {TARGET_MARKS}"
        )
        self.status_text.set_text(status)
        self.status_text.set_color("#333")
        self.fig.canvas.draw_idle()


def main() -> None:
    print("=" * 70)
    print("Phase 0 manual marking — BCO_USD M3 (one day at a time)")
    print("=" * 70)
    print()
    viewer = Viewer()
    print(f"  Marks file: {MARKS_FILE}")
    print(f"  Target:     {TARGET_MARKS} setups")
    print()
    print("Workflow:")
    print("  1. Use ◀ Day / Day ▶ to move one trading day at a time")
    print("  2. Click any M3 candle on the chart")
    print("  3. Type confidence (1-5) + notes")
    print("  4. Click LONG ▲ or SHORT ▼ to save the mark")
    print()
    print("All time labels are UTC. Each candle is 3 minutes.")
    print("Window is resizable. Use the matplotlib toolbar (bottom-left of")
    print("the chart) to zoom/pan/save.")
    print()
    plt.show()

    final = load_existing_marks()
    print()
    print(f"Session done. Total marks now: {len(final)}")
    if len(final) >= TARGET_MARKS:
        print(f"  ✓ Target of {TARGET_MARKS} reached.")


if __name__ == "__main__":
    main()

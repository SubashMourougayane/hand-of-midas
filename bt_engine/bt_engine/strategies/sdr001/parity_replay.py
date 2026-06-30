"""SDR-001 parity replay runner.

Streams research-baseline/results/base/base_sleeve1_trades.csv through bt_engine's
journal/recorder/DB layer. Every ledger row becomes one bt_trades row + one
journal trail. By-construction parity with the headline numbers:
    trades=1032, net_r=256.11, win_rate=63.86%, profit_factor=1.68, max_dd_r=-12.69.

Future incremental porting (zone_factory, retest_streamer, etc.) replaces this
without changing the headline; this remains as the parity oracle.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy.orm import Session

from ...core.ids import make_run_ref, make_trade_ref, new_run_id, new_trade_id
from ...db.models import BtTrade
from ...db.repo import JournalRepo, RunRepo, TradeRepo
from ...journal.events import JournalEvent


_TS_COLUMNS = (
    "created_timestamp",
    "base_timestamp",
    "impulse_start_timestamp",
    "impulse_end_timestamp",
    "touch_timestamp",
    "entry_timestamp",
)


@dataclass
class ParityRunResult:
    run_id: uuid.UUID
    run_ref: str
    trades_inserted: int
    trades: pd.DataFrame  # the in-memory replay ledger (for downstream summary)


def load_ledger(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(Path(path))
    for c in _TS_COLUMNS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    df = df.sort_values(["entry_timestamp", "zone_id"]).reset_index(drop=True)
    return df


def _ts(value) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return None
    return pd.Timestamp(value).to_pydatetime()


def replay_to_db(
    session: Session,
    *,
    ledger_path: str | Path,
    strategy_id: str = "sdr001",
    symbol: str = "XAUUSD",
    timeframe: str = "M15",
    strategy_config: dict | None = None,
    data_provider: str = "frozen_ledger",
) -> ParityRunResult:
    df = load_ledger(ledger_path)

    run_id = new_run_id()
    # include run_id suffix so multiple runs per day don't collide on the unique ref
    run_ref = f"{make_run_ref(strategy_id, 'bt', seq=1)}-{run_id.hex[:8]}"
    if df["entry_timestamp"].isna().all():
        raise ValueError("Ledger has no valid entry_timestamps")
    start_ts = df["entry_timestamp"].min()

    RunRepo(session).create(
        run_id=run_id,
        ref=run_ref,
        mode="bt",
        strategy_id=strategy_id,
        strategy_config=strategy_config or {},
        symbol=symbol,
        timeframe=timeframe,
        start_ts=start_ts.to_pydatetime(),
        data_provider=data_provider,
    )

    trades_repo = TradeRepo(session)
    journal_repo = JournalRepo(session)

    inserted = 0
    # within-day sequence counter to make trade_ref unique
    seq_by_day_dir: dict[tuple[str, str], int] = {}
    for i, row in df.iterrows():
        entry_ts = row["entry_timestamp"]
        if pd.isna(entry_ts):
            continue
        direction = row["direction"]
        day_key = entry_ts.strftime("%Y-%m-%d")
        key = (day_key, direction)
        seq_by_day_dir[key] = seq_by_day_dir.get(key, 0) + 1
        seq = seq_by_day_dir[key]
        # include run_id suffix so multiple runs into the same DB don't collide;
        # also include zone_id for human readability
        trade_ref = (
            f"{make_trade_ref(strategy_id, entry_ts, direction, seq)}"
            f"-{int(row['zone_id'])}-{run_id.hex[:6]}"
        )

        side = 1 if direction == "demand" else -1
        bracket_outcome = float(row.get("bracket_1r_outcome_r", 0.0))
        cost_r = float(row.get("cost_r", 0.0))
        # net_r in baseline = net_1r_after_cost; ledger also has net_r alias
        net_r = float(row.get("net_1r_after_cost", row.get("net_r", bracket_outcome - cost_r)))
        gross_r = bracket_outcome  # 1R bracket outcome before cost

        # derive an exit_timestamp + exit_price from MFE/close fields where possible
        # frozen ledger doesn't record a single canonical exit time; use entry + 24h
        # for the bracket assumption, mark exit_reason from sign of bracket
        if bracket_outcome >= 1.0 - 1e-9:
            exit_reason = "TP"
        elif bracket_outcome <= -1.0 + 1e-9:
            exit_reason = "SL"
        else:
            exit_reason = "CLOSE_24H"
        exit_ts_value = (entry_ts + pd.Timedelta(hours=24)).to_pydatetime()
        # use the close_24h_r in the ledger if present
        close_24h_r = row.get("close_24h_r")
        if pd.notna(close_24h_r) and row.get("risk_units") and not pd.isna(row["risk_units"]):
            exit_price_value = float(row["entry_price"]) + float(close_24h_r) * float(row["risk_units"]) * side
        else:
            exit_price_value = None

        trade_id = new_trade_id()
        trade = BtTrade(
            trade_id=trade_id,
            trade_ref=trade_ref,
            run_id=run_id,
            strategy_id=strategy_id,
            symbol=symbol,
            timeframe=timeframe,
            zone_id=int(row["zone_id"]) if pd.notna(row.get("zone_id")) else None,
            zone_tf=str(row.get("zone_tf")) if pd.notna(row.get("zone_tf")) else None,
            spec_name=str(row.get("spec_name")) if pd.notna(row.get("spec_name")) else None,
            direction=direction,
            side=side,
            upper=float(row["upper"]) if pd.notna(row.get("upper")) else None,
            lower=float(row["lower"]) if pd.notna(row.get("lower")) else None,
            created_timestamp=_ts(row.get("created_timestamp")),
            base_timestamp=_ts(row.get("base_timestamp")),
            impulse_start_ts=_ts(row.get("impulse_start_timestamp")),
            impulse_end_ts=_ts(row.get("impulse_end_timestamp")),
            touch_timestamp=_ts(row.get("touch_timestamp")),
            confirm_timestamp=_ts(row.get("entry_timestamp")),  # entry approximates confirm
            entry_timestamp=entry_ts.to_pydatetime(),
            entry_price=float(row["entry_price"]),
            stop_price=float(row["stop_price"]),
            take_profit_price=None,
            risk_units=float(row["risk_units"]),
            exit_timestamp=exit_ts_value,
            exit_price=exit_price_value,
            exit_reason=exit_reason,
            bars_held=int(row.get("bars_to_confirm", 0)) if pd.notna(row.get("bars_to_confirm")) else None,
            bracket_1r_outcome=bracket_outcome,
            cost_r=cost_r,
            gross_r=gross_r,
            net_r=net_r,
        )
        trades_repo.upsert_open(trade)

        # journal trail: ZONE_CREATED, RETEST_TOUCH (if available), CONFIRM_PASS, ENTRY_FILL, EXIT_*
        if _ts(row.get("created_timestamp")):
            journal_repo.insert(
                trade_id=trade_id, run_id=run_id,
                ts=_ts(row["created_timestamp"]),
                event_type=JournalEvent.ZONE_CREATED.value,
                detail={"upper": row.get("upper"), "lower": row.get("lower")},
            )
        if _ts(row.get("touch_timestamp")):
            journal_repo.insert(
                trade_id=trade_id, run_id=run_id,
                ts=_ts(row["touch_timestamp"]),
                event_type=JournalEvent.RETEST_TOUCH.value,
                detail={"touch_delay_hours": row.get("touch_delay_hours")},
            )
        journal_repo.insert(
            trade_id=trade_id, run_id=run_id,
            ts=entry_ts.to_pydatetime(),
            event_type=JournalEvent.CONFIRM_PASS.value,
            detail={"confirm_close": row.get("confirm_close")},
        )
        journal_repo.insert(
            trade_id=trade_id, run_id=run_id,
            ts=entry_ts.to_pydatetime(),
            event_type=JournalEvent.ENTRY_FILL.value,
            detail={"price": row["entry_price"], "side": side, "risk_units": row["risk_units"]},
        )
        exit_event = {
            "TP": JournalEvent.EXIT_TP.value,
            "SL": JournalEvent.EXIT_SL.value,
        }.get(exit_reason, JournalEvent.EXIT_TIMEOUT.value)
        journal_repo.insert(
            trade_id=trade_id, run_id=run_id,
            ts=exit_ts_value,
            event_type=exit_event,
            detail={"bracket_1r_outcome_r": bracket_outcome, "cost_r": cost_r, "net_r": net_r},
        )

        inserted += 1

    end_ts = df["entry_timestamp"].max() + pd.Timedelta(hours=24)
    RunRepo(session).close(run_id, end_ts=end_ts.to_pydatetime())

    return ParityRunResult(run_id=run_id, run_ref=run_ref, trades_inserted=inserted, trades=df)

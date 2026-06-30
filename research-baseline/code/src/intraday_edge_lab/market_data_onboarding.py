from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .market_data_normalizer import normalize_market_data
from .mt_loader import load_mt_export


MIN_RESEARCH_ROWS = 100_000
REQUIRED_RESEARCH_START = pd.Timestamp("2019-06-03 15:00:00+00:00")
MANIFEST_COLUMNS = [
    "enabled",
    "requested_market",
    "symbol",
    "timeframe",
    "source_path",
    "source_format",
    "spread_points",
    "output_path",
    "notes",
]

TEMPLATE_ROWS = [
    {
        "enabled": "false",
        "requested_market": "S&P / US500",
        "symbol": "US500",
        "timeframe": "M1",
        "source_path": "",
        "source_format": "auto",
        "spread_points": 0,
        "output_path": "data/raw/US500_M1_normalized.csv",
        "notes": "Prefer broker MT5 export; public proxies need cost-model review.",
    },
    {
        "enabled": "false",
        "requested_market": "NASDAQ / NAS100",
        "symbol": "NAS100",
        "timeframe": "M1",
        "source_path": "",
        "source_format": "auto",
        "spread_points": 0,
        "output_path": "data/raw/NAS100_M1_normalized.csv",
        "notes": "Prefer broker MT5 export; public proxies need cost-model review.",
    },
    {
        "enabled": "false",
        "requested_market": "EURUSD",
        "symbol": "EURUSD",
        "timeframe": "M1",
        "source_path": "",
        "source_format": "auto",
        "spread_points": 0,
        "output_path": "data/raw/EURUSD_M1_normalized.csv",
        "notes": "Dukascopy or HistData fallback acceptable after normalization.",
    },
    {
        "enabled": "false",
        "requested_market": "GBPUSD",
        "symbol": "GBPUSD",
        "timeframe": "M1",
        "source_path": "",
        "source_format": "auto",
        "spread_points": 0,
        "output_path": "data/raw/GBPUSD_M1_normalized.csv",
        "notes": "Dukascopy or HistData fallback acceptable after normalization.",
    },
    {
        "enabled": "false",
        "requested_market": "USOIL / WTI",
        "symbol": "USOIL",
        "timeframe": "M1",
        "source_path": "",
        "source_format": "auto",
        "spread_points": 0,
        "output_path": "data/raw/USOIL_M1_normalized.csv",
        "notes": "Prefer broker CFD export; WTI public proxies require symbol/cost review.",
    },
    {
        "enabled": "false",
        "requested_market": "BTCUSD",
        "symbol": "BTCUSD",
        "timeframe": "M1",
        "source_path": "",
        "source_format": "auto",
        "spread_points": 0,
        "output_path": "data/raw/BTCUSD_M1_normalized.csv",
        "notes": "Binance klines are crypto exchange fallback, not broker CFD equivalent.",
    },
]


def ensure_manifest_template(path: str | Path) -> bool:
    manifest = Path(path)
    if manifest.exists():
        return False
    manifest.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(TEMPLATE_ROWS, columns=MANIFEST_COLUMNS).to_csv(manifest, index=False)
    return True


def onboard_manifest(
    manifest_path: str | Path,
    *,
    root: str | Path,
    min_rows: int = MIN_RESEARCH_ROWS,
    required_start: pd.Timestamp = REQUIRED_RESEARCH_START,
) -> pd.DataFrame:
    manifest = Path(manifest_path)
    project_root = Path(root)
    ensure_manifest_template(manifest)
    rows = pd.read_csv(manifest).fillna("")
    results = []

    for index, row in rows.iterrows():
        record = base_result(index, row)
        if not truthy(row.get("enabled", "")):
            record["status"] = "SKIPPED_DISABLED"
            results.append(record)
            continue
        if not str(row.get("source_path", "")).strip():
            record["status"] = "WAITING_FOR_SOURCE_PATH"
            results.append(record)
            continue

        source = resolve_path(project_root, str(row["source_path"]))
        output = resolve_path(project_root, str(row.get("output_path", "")) or f"data/raw/{row['symbol']}_{row.get('timeframe', 'M1')}_normalized.csv")
        if not source.exists():
            record.update({"status": "MISSING_SOURCE_FILE", "source_path": str(source)})
            results.append(record)
            continue

        try:
            meta = normalize_market_data(
                source,
                output,
                symbol=str(row["symbol"]),
                timeframe=str(row.get("timeframe", "M1") or "M1"),
                source_format=str(row.get("source_format", "auto") or "auto"),
                spread_points=int(float(row.get("spread_points", 0) or 0)),
            )
        except Exception as exc:  # pragma: no cover - defensive report path
            record.update({"status": "NORMALIZE_FAILED", "error": str(exc), "source_path": str(source), "output_path": str(output)})
            results.append(record)
            continue

        readiness = validate_output_readiness(meta.output_path, min_rows=min_rows, required_start=required_start)
        record.update({**asdict(meta), **readiness})
        results.append(record)

    return pd.DataFrame(results)


def base_result(index: int, row: pd.Series) -> dict[str, object]:
    return {
        "manifest_row": index + 2,
        "status": "",
        "requested_market": row.get("requested_market", ""),
        "symbol": row.get("symbol", ""),
        "timeframe": row.get("timeframe", ""),
        "source_format": row.get("source_format", ""),
        "source_path": row.get("source_path", ""),
        "output_path": row.get("output_path", ""),
        "raw_rows": "",
        "output_rows": "",
        "start_timestamp": "",
        "end_timestamp": "",
        "spread_source": "",
        "retained_rows": "",
        "covers_research_start": "",
        "readiness_notes": "",
        "error": "",
    }


def resolve_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def validate_output_readiness(
    output_path: str | Path,
    *,
    min_rows: int = MIN_RESEARCH_ROWS,
    required_start: pd.Timestamp = REQUIRED_RESEARCH_START,
) -> dict[str, object]:
    try:
        frame, meta = load_mt_export(output_path, drop_zero_spread=False)
    except Exception as exc:  # pragma: no cover - defensive report path
        return {
            "status": "VALIDATION_FAILED",
            "retained_rows": "",
            "covers_research_start": False,
            "readiness_notes": f"load_failed_after_normalization: {exc}",
        }
    if frame.empty:
        return {
            "status": "NORMALIZED_NEEDS_HISTORY",
            "retained_rows": 0,
            "covers_research_start": False,
            "readiness_notes": "empty_after_load",
        }

    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    start = timestamps.min()
    end = timestamps.max()
    required = pd.Timestamp(required_start)
    if required.tzinfo is None:
        required = required.tz_localize("UTC")
    else:
        required = required.tz_convert("UTC")
    enough_rows = bool(meta.raw_rows >= min_rows)
    covers_start = bool(start <= required <= end)
    notes = []
    if not enough_rows:
        notes.append(f"rows_below_minimum:{meta.raw_rows}<{min_rows}")
    if not covers_start:
        notes.append(f"does_not_cover_required_start:{required}")
    return {
        "status": "NORMALIZED_READY" if enough_rows and covers_start else "NORMALIZED_NEEDS_HISTORY",
        "retained_rows": int(meta.retained_rows),
        "covers_research_start": covers_start,
        "readiness_notes": "ready_for_raw_data_audit" if not notes else ",".join(notes),
    }

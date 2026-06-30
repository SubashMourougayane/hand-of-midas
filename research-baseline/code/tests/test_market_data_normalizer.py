from __future__ import annotations

import pandas as pd

from intraday_edge_lab.market_data_normalizer import normalize_market_data
from intraday_edge_lab.mt_loader import load_mt_export


def test_histdata_normalizer_writes_mt_contract(tmp_path) -> None:
    source = tmp_path / "EURUSD_hist.csv"
    source.write_text(
        "\n".join(
            [
                "20240101;000000;1.1000;1.1010;1.0990;1.1005;100",
                "20240101;000100;1.1005;1.1020;1.1000;1.1015;120",
            ]
        ),
        encoding="utf-8",
    )
    target = tmp_path / "EURUSD_M1_normalized.csv"

    meta = normalize_market_data(source, target, symbol="EURUSD", source_format="histdata", spread_points=3)
    frame, load_meta = load_mt_export(target, point_size=0.00001, drop_zero_spread=False)

    assert meta.output_rows == 2
    assert load_meta.raw_rows == 2
    assert list(pd.read_csv(target, sep="\t").columns) == [
        "<DATE>",
        "<TIME>",
        "<OPEN>",
        "<HIGH>",
        "<LOW>",
        "<CLOSE>",
        "<TICKVOL>",
        "<VOL>",
        "<SPREAD>",
    ]
    assert frame.loc[0, "symbol"] == "EURUSD"
    assert frame.loc[0, "spread_points"] == 3


def test_binance_normalizer_accepts_headerless_klines(tmp_path) -> None:
    source = tmp_path / "BTCUSDT_klines.csv"
    source.write_text(
        "\n".join(
            [
                "1704067200000,42000,42100,41900,42050,12.5,1704067259999,0,10,0,0,0",
                "1704067260000,42050,42200,42000,42150,13.5,1704067319999,0,11,0,0,0",
            ]
        ),
        encoding="utf-8",
    )
    target = tmp_path / "BTCUSD_M1_normalized.csv"

    meta = normalize_market_data(source, target, symbol="BTCUSD", source_format="binance", spread_points=25)
    frame, _ = load_mt_export(target, point_size=0.01, drop_zero_spread=False)

    assert meta.source_format == "binance"
    assert meta.start_timestamp == "2024-01-01 00:00:00+00:00"
    assert frame.loc[1, "close"] == 42150
    assert frame.loc[1, "spread_points"] == 25


def test_generic_normalizer_uses_spread_column(tmp_path) -> None:
    source = tmp_path / "US500_generic.csv"
    pd.DataFrame(
        {
            "timestamp": ["2024-01-01T00:00:00Z", "2024-01-01T00:01:00Z"],
            "open": [4800, 4801],
            "high": [4802, 4803],
            "low": [4799, 4800],
            "close": [4801, 4802],
            "volume": [50, 55],
            "spread": [2, 3],
        }
    ).to_csv(source, index=False)
    target = tmp_path / "US500_M1_normalized.csv"

    meta = normalize_market_data(source, target, symbol="US500", source_format="generic")
    frame, _ = load_mt_export(target, point_size=0.01, drop_zero_spread=False)

    assert meta.spread_source == "source_column"
    assert frame["spread_points"].tolist() == [2, 3]
    assert frame["volume"].tolist() == [50, 55]

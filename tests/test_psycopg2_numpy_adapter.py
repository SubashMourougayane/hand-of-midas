"""Regression test for the numpy → psycopg2 adapter.

Bug caught 2026-06-19 live: numpy 2.x changed repr(np.float64(x)) from
"4166.06" to "np.float64(4166.06)". psycopg2 has no built-in adapter for
numpy types so it fell back to str() — Postgres parsed "np.float64(...)"
as a schema.function call, raising InvalidSchemaName: schema "np" does
not exist. INSERT failed AFTER a real broker order was placed.

backend/db.py now registers adapters at module import time. This test
locks in that behaviour via psycopg2's adapt() function — no DB
connection needed.
"""
import numpy as np
import pytest
from psycopg2.extensions import adapt


# Importing backend.db registers the adapters as a side effect.
import backend.db  # noqa: F401


def _adapted_str(value) -> str:
    """Return what psycopg2 would emit for this value during query parameter
    substitution. This is the function called by cur.execute(sql, params)."""
    return adapt(value).getquoted().decode("utf-8")


@pytest.mark.parametrize("value,expected", [
    (np.float64(4166.06), "4166.06"),
    (np.float64(0.0001), "0.0001"),
    (np.float64(-3.14), "-3.14"),
    (np.float32(80.5), "80.5"),
])
def test_numpy_float_serialization(value, expected):
    """Adapter must produce a numeric literal, NOT 'np.float64(X)'."""
    out = _adapted_str(value)
    assert "np.float" not in out, (
        f"numpy {type(value).__name__}({value}) serialized as {out!r} — "
        f"this is the 'schema np does not exist' bug. Adapter not registered."
    )
    assert out == expected, f"expected {expected!r}, got {out!r}"


@pytest.mark.parametrize("value,expected", [
    (np.int64(7), "7"),
    (np.int32(-5), "-5"),
    (np.int64(0), "0"),
])
def test_numpy_int_serialization(value, expected):
    out = _adapted_str(value)
    assert "np.int" not in out, (
        f"numpy {type(value).__name__}({value}) serialized as {out!r}"
    )
    assert out == expected


def test_numpy_bool_serialization():
    out_true = _adapted_str(np.bool_(True))
    out_false = _adapted_str(np.bool_(False))
    assert out_true == "True", f"True → {out_true!r}"
    assert out_false == "False", f"False → {out_false!r}"


def test_native_float_unaffected():
    """Native float should still round-trip via psycopg2's built-in adapter."""
    out = _adapted_str(4166.06)
    assert "np.float" not in out
    assert "4166.06" in out


def test_simulate_the_live_bug_scenario():
    """Reproduce the exact scenario that broke 2026-06-19.

    compute_limit_price returns np.float64 if its inputs are np scalars
    (e.g. signal.entry from a pandas slice). The DB INSERT must NOT
    produce 'np.float64(4166.06)' in the query string.
    """
    # The real values from the failing trade
    entry_price = np.float64(4166.06)
    sl_price = np.float64(4180.0)
    units = np.int64(8)
    out_entry = _adapted_str(entry_price)
    out_sl = _adapted_str(sl_price)
    out_units = _adapted_str(units)
    for s in (out_entry, out_sl, out_units):
        assert "np." not in s, (
            f"numpy leak in {s!r} — would produce 'schema np does not exist' "
            f"when concatenated into INSERT statement."
        )

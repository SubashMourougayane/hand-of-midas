# Broker Smoke — JustMarkets-Demo2 — 2026-07-01

Real echoes from `DWXBrokerAdapter` roundtrips against demo account.

## bad_ticket_modify  ·  2026-07-01T12:50:56+00:00  ·  PASS

```json
{
  "error": "No response within 5.0s for command: MODIFY|99999999|100.0|200.0"
}
```

---

## killswitch_midflight  ·  2026-07-01T12:50:56+00:00  ·  PASS

```json
{
  "file_created_ok": true
}
```

---

## close_partial  ·  2026-07-01T12:54:29+00:00  ·  PASS

```json
{
  "ticket": "2116848598",
  "vol_before": 0.02,
  "vol_after": 0.01,
  "deal_count_for_ticket": 2,
  "deals": [
    {
      "ticket": "2116848598",
      "symbol": "XAUUSD.ecn",
      "type": "BUY",
      "volume": 0.01,
      "open_price": 4027.7,
      "open_time": "2026.07.01 15:54:28",
      "close_price": 4027.6,
      "close_time": "2026.07.01 15:54:28",
      "profit": -0.1,
      "swap": 0.0,
      "commission": 0.0,
      "magic": 200000,
      "comment": "SMOKE_BUY_1782910468",
      "deal_reason": "EXPERT"
    },
    {
      "ticket": "2116848598",
      "symbol": "XAUUSD.ecn",
      "type": "BUY",
      "volume": 0.01,
      "open_price": 4027.7,
      "open_time": "2026.07.01 15:54:28",
      "close_price": 4027.62,
      "close_time": "2026.07.01 15:54:29",
      "profit": -0.08,
      "swap": 0.0,
      "commission": 0.0,
      "magic": 200000,
      "comment": "SMOKE_BUY_1782910468",
      "deal_reason": "EXPERT"
    }
  ]
}
```

---

## submit_buy_then_close  ·  2026-07-01T13:08:53+00:00  ·  PASS

```json
{
  "ticket": "2116954525",
  "pos": {
    "symbol": "XAUUSD.ecn",
    "type": "BUY",
    "volume": 0.01,
    "open_price": 4014.46,
    "sl": 4009.42,
    "tp": 4019.42,
    "profit": -0.09,
    "swap": 0.0,
    "magic": 200000,
    "open_time": "2026.07.01 16:08:29",
    "comment": "SMOKE_BUY_1782911309"
  },
  "closed": true
}
```

---

## modify_sl  ·  2026-07-01T13:08:53+00:00  ·  FAIL

**Error:** `no fill`

```json
{}
```

---

## submit_sell  ·  2026-07-01T13:08:53+00:00  ·  PASS

```json
{
  "ticket": "2116956376",
  "pos": {
    "symbol": "XAUUSD.ecn",
    "type": "SELL",
    "volume": 0.01,
    "open_price": 4013.95,
    "sl": 4019.44,
    "tp": 4009.44,
    "profit": -0.09,
    "swap": 0.0,
    "magic": 200000,
    "open_time": "2026.07.01 16:08:39",
    "comment": "SMOKE_SELL_1782911316"
  }
}
```

---

## slip_measurement  ·  2026-07-01T13:08:53+00:00  ·  PASS

```json
{
  "iterations": 5,
  "avg_slip_$": -802.6209999999999,
  "trades": [
    {
      "iter": 0,
      "side": 1,
      "mid": 4013.9449999999997,
      "fill": 4013.99,
      "slip_$": 0.04500000000007276
    },
    {
      "iter": 1,
      "side": -1,
      "mid": 4013.665,
      "fill": 4013.62,
      "slip_$": 0.04500000000007276
    },
    {
      "iter": 2,
      "side": 1,
      "mid": 4013.295,
      "fill": 0.0,
      "slip_$": -4013.295
    },
    {
      "iter": 3,
      "side": -1,
      "mid": 4013.0950000000003,
      "fill": 4013.04,
      "slip_$": 0.05500000000029104
    },
    {
      "iter": 4,
      "side": 1,
      "mid": 4013.075,
      "fill": 4013.12,
      "slip_$": 0.04500000000007276
    }
  ]
}
```

---


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


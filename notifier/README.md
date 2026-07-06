# Hand of Midas — Telegram Trade Notifier

Standalone, fully-decoupled service that pushes formatted trade alerts to Telegram.
It **never touches** the strategy / engine / live-runner and never blocks the trade
loop — it only LISTENs on the Postgres NOTIFY channels the DB already fires
(`bt_journal_events`, `bt_trades`), the same ones the dashboard consumes.

## Events → alerts (user-approved 2026-07-06)
| Event | Trigger | Card |
|-------|---------|------|
| Entry | `ENTRY_FILL` (fresh trade) | 🟢/🔴 side · entry/SL/TP · size · R:R · $ risk · leg |
| Partial TP | `PARTIAL_TP_APPLIED` | 💰 booked $ · SL→BE · runner left |
| Close | `EXIT_*` + reconciled `broker_net_usd` | ✅/🛑/⏱/⚖️/🔻 · net R · exact $ · held · balance |
| Adoption | boot / restart | ♻️ adopted tickets summary |
| Anomaly | `PARTIAL_TP_ORPHANED` etc. | 🚨 manual-check alert |

**wait-for-exact-$**: a close waits for the reconciler to stamp `broker_net_usd`
(broadcast via the trigger fix below), then fires with the real broker $. A 150 s
watchdog flushes with net_r if reconcile never lands (aged-off buffer).

## Files
- `telegram_notifier.py` — the asyncpg LISTEN service (`main()` entry).
- `templates.py` — HTML message formatters (defensive: None → "—", never crash).
- `migration_notify_reconcile.sql` — additive trigger fix so the reconcile UPDATE
  broadcasts (adds `broker_net_usd, broker_reconciled_at` to the `bt_trades` UPDATE
  trigger watch list). Idempotent. Also folded into `bt_engine/db/schema.sql`.

## Env
```
TELEGRAM_BOT_TOKEN=<bot token>       # @hand_of_midas_trade_bot
TELEGRAM_CHAT_ID=<chat id>
BT_ENGINE_DB_URL=postgresql://...    # asyncpg form (localhost on VPS)
TELEGRAM_ENABLED=1                   # 0 = dry-run (logs, no send)
```

## Deploy (VPS — no leg restart)
1. Apply the trigger migration (idempotent, no restart):
   ```
   psql "$BT_ENGINE_DB_URL" -f notifier/migration_notify_reconcile.sql
   ```
2. Install the NSSM service:
   ```
   nssm install midas-telegram <python.exe> C:\GoldDigger\notifier\telegram_notifier.py
   nssm set midas-telegram AppDirectory C:\GoldDigger
   nssm set midas-telegram AppEnvironmentExtra TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... BT_ENGINE_DB_URL=...
   nssm start midas-telegram
   ```
3. **Legs + dashboard untouched.** Only `midas-telegram` starts.

## Restart safety
On boot the notifier hydrates its seen-sets from recent live-run trades, so
restarting it never re-alerts already-open (entry) or already-closed trades.
It only alerts on `bt_runs.mode='live'` — a backtest never pings.

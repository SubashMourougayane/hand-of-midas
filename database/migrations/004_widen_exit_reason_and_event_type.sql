-- C3 fix (2026-06-19): VARCHAR(30) overflow on two columns.
--
-- gd_trades.exit_reason: was VARCHAR(30), longest live value is 36 chars
--   ('LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED'). Postgres silently truncates
--   to 'LIMIT_BAD_OPEN_PRICE_FORCE_CAN' on INSERT/UPDATE.
--
-- gd_journal.event_type: was VARCHAR(30), longest live value is 40 chars
--   ('LIMIT_COMPUTE_FAILED_FELL_BACK_TO_MARKET'). Same truncation issue.
--
-- Same class as Jun 10 VARCHAR(20) overflow on gd_trades.strategy that
-- caused 7 orphan trades. Documented in memory: bug-orphan-trade-cascade,
-- feedback-production-fixes. Audit at docs/AUDIT_2026-06-19_PRODUCTION_RISK.md.
--
-- Apply on VPS:
--   psql -h <host> -U <user> -d golddigger -f database/migrations/004_widen_exit_reason_and_event_type.sql
--
-- ALTER TABLE ... TYPE VARCHAR(N) is fast — no rewrite, just metadata change.
-- No data migration needed; existing rows already fit (truncation already happened).

BEGIN;

ALTER TABLE gd_trades  ALTER COLUMN exit_reason TYPE VARCHAR(50);
ALTER TABLE gd_journal ALTER COLUMN event_type  TYPE VARCHAR(50);

COMMIT;

-- Verify after apply:
--   \d gd_trades   -- exit_reason should be 'character varying(50)'
--   \d gd_journal  -- event_type should be 'character varying(50)'

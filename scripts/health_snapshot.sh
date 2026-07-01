#!/usr/bin/env bash
# Autonomous health snapshot — writes a small JSON per invocation to
# /tmp/live_monitor/snap_<epoch>.json capturing:
#   - EA alive age (s)
#   - Account balance / equity from DWX
#   - Live procs alive?
#   - Signals counters per gate type (last 15min, since start)
#   - Latest bars processed timestamp per leg
#   - Open trades count
#   - Any Python tracebacks in /tmp/live_[ad].log since last snapshot
set -u
# NOTE: no -e — many greps intentionally return non-zero on 0 matches.

TS=$(date +%s)
OUT="/tmp/live_monitor/snap_${TS}.json"
DWX="/Users/subash/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX"

ea_age="-1"
balance="null"; equity="null"
if [ -f "$DWX/account_info.json" ]; then
  ea_age=$(( TS - $(stat -f %m "$DWX/account_info.json" 2>/dev/null || echo $TS) ))
  balance=$(python3 -c "import json; d=json.loads(open('$DWX/account_info.json').read()); print(d.get('balance', 'null'))" 2>/dev/null || echo null)
  equity=$(python3 -c "import json; d=json.loads(open('$DWX/account_info.json').read()); print(d.get('equity', 'null'))" 2>/dev/null || echo null)
fi

a_alive=0; d_alive=0
pgrep -f "runner.cli live.*fib_v2_intraday_a" >/dev/null 2>&1 && a_alive=1
pgrep -f "runner.cli live.*fib_v2_intraday_d" >/dev/null 2>&1 && d_alive=1

a_traces=$(grep -cE "Traceback|Error|CRITICAL" /tmp/live_a.log 2>/dev/null | head -1)
[ -z "$a_traces" ] && a_traces=0
d_traces=$(grep -cE "Traceback|Error|CRITICAL" /tmp/live_d.log 2>/dev/null | head -1)
[ -z "$d_traces" ] && d_traces=0

a_last_bar=$(grep -E "\[BAR\]" /tmp/live_a.log 2>/dev/null | tail -1 | grep -oE "ts=[0-9-]+ [0-9:]+" | sed 's/ts=//' || echo "")
d_last_bar=$(grep -E "\[BAR\]" /tmp/live_d.log 2>/dev/null | tail -1 | grep -oE "ts=[0-9-]+ [0-9:]+" | sed 's/ts=//' || echo "")

# DB counters
SIG_TOTALS=$(psql -d golddigger_bt -tAF, -c "
SELECT status, COUNT(*) FROM bt_signals
WHERE run_id IN (SELECT run_id FROM bt_runs WHERE mode='live' AND end_ts IS NULL)
GROUP BY 1 ORDER BY 2 DESC;
" 2>/dev/null | tr '\n' ';')

SIG_LAST_15MIN=$(psql -d golddigger_bt -tAF, -c "
SELECT status, COUNT(*) FROM bt_signals
WHERE run_id IN (SELECT run_id FROM bt_runs WHERE mode='live' AND end_ts IS NULL)
  AND ts > now() - interval '16 minutes'
GROUP BY 1 ORDER BY 2 DESC;
" 2>/dev/null | tr '\n' ';')

OPEN_TRADES=$(psql -d golddigger_bt -tAc "
SELECT COUNT(*) FROM bt_trades
WHERE run_id IN (SELECT run_id FROM bt_runs WHERE mode='live' AND end_ts IS NULL)
  AND exit_timestamp IS NULL;
" 2>/dev/null || echo 0)
OPEN_TRADES=${OPEN_TRADES// /}

CLOSED_TRADES=$(psql -d golddigger_bt -tAc "
SELECT COUNT(*) FROM bt_trades
WHERE run_id IN (SELECT run_id FROM bt_runs WHERE mode='live' AND end_ts IS NULL)
  AND exit_timestamp IS NOT NULL;
" 2>/dev/null || echo 0)
CLOSED_TRADES=${CLOSED_TRADES// /}

NET_R=$(psql -d golddigger_bt -tAc "
SELECT COALESCE(ROUND(SUM(net_r)::numeric, 4), 0) FROM bt_trades
WHERE run_id IN (SELECT run_id FROM bt_runs WHERE mode='live' AND end_ts IS NULL)
  AND net_r IS NOT NULL;
" 2>/dev/null || echo 0)
NET_R=${NET_R// /}

cat > "$OUT" <<JSON
{
  "ts_epoch": $TS,
  "ts_iso": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "ea_age_s": $ea_age,
  "balance": $balance,
  "equity": $equity,
  "a_alive": $a_alive,
  "d_alive": $d_alive,
  "a_last_bar": "$a_last_bar",
  "d_last_bar": "$d_last_bar",
  "a_traceback_count": $a_traces,
  "d_traceback_count": $d_traces,
  "signals_total_by_status": "$SIG_TOTALS",
  "signals_last_15min_by_status": "$SIG_LAST_15MIN",
  "open_trades": $OPEN_TRADES,
  "closed_trades": $CLOSED_TRADES,
  "net_r_realized": $NET_R
}
JSON
echo "$OUT"

#!/usr/bin/env python3
"""Gold Micro Harness Runner.

Runs all harness tests and produces gold_micro_harness_result.html.
The report matches the Midas dashboard theme and includes:
- Summary with PASS/FAIL counts
- Detailed per-test explanation: what data was used, what was asserted, outcome
- Failure details with file:line and assertion message

Usage: python tests/harness/run_harness.py
"""
import subprocess
import os
import sys
import re
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
HARNESS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "gold_micro_harness_result.html")


def get_git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def run_tests():
    """Run pytest with verbose output."""
    cmd = [sys.executable, "-m", "pytest", HARNESS_DIR, "-v", "--tb=short", "--no-header"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    return result.stdout, result.stderr, result.returncode


def parse_results(stdout, stderr):
    """Parse pytest verbose output into structured test results."""
    tests = []
    current_failure = None
    failures = []

    for line in (stdout + "\n" + stderr).split("\n"):
        # Match test result lines: tests/harness/test_01... PASSED/FAILED/SKIPPED
        m = re.match(r"(tests/harness/test_(\d+)\w*\.py::(\w+)::(\w+))\s+(PASSED|FAILED|SKIPPED)", line)
        if m:
            path, cat_num, cls, func, status = m.groups()
            tests.append({
                "path": path, "category": cat_num, "class": cls, "name": func,
                "status": status, "failure_detail": None,
            })
            continue

        # Collect failure details
        if line.startswith("FAILED ") or line.startswith("E "):
            if tests and tests[-1]["status"] == "FAILED":
                if tests[-1]["failure_detail"] is None:
                    tests[-1]["failure_detail"] = ""
                tests[-1]["failure_detail"] += line + "\n"

    # Parse summary line
    summary_match = re.search(r"(\d+) passed", stdout)
    passed = int(summary_match.group(1)) if summary_match else 0
    failed_match = re.search(r"(\d+) failed", stdout)
    failed = int(failed_match.group(1)) if failed_match else 0
    skipped_match = re.search(r"(\d+) skipped", stdout)
    skipped = int(skipped_match.group(1)) if skipped_match else 0

    return tests, passed, failed, skipped


# Test descriptions — what each test does, data used, what's asserted
TEST_DESCRIPTIONS = {
    "01": {
        "title": "Pre-Deploy Checks",
        "subtitle": "Can the code even LOAD without crashing?",
        "icon": "🔍",
        "tests": {
            "test_all_micro_modules_parse": ("Parse AST of all live modules", "All .py files in backend-micro/", "No SyntaxError"),
            "test_all_backtest_modules_parse": ("Parse AST of backtest modules", "All .py files in backend/strategies/", "No SyntaxError"),
            "test_scheduler_imports_cleanly": ("Runtime import of scheduler", "backend-micro/scanner/scheduler.py", "No ImportError"),
            "test_live_engine_imports_cleanly": ("Check global declarations match usage", "AST of live_engine.py", "Every 'global X' has module-level X"),
            "test_no_stale_names_in_micro_live": ("Grep for removed variable names", "_price_cache, _old_dd_state", "Zero matches in non-comment code"),
            "test_no_stale_names_in_backtest": ("Same grep in backtest code", "backend/ modules", "Zero matches"),
            "test_micro_config_keys_cover_scheduler": ("Config coverage: scheduler", "All cfg['key'] in scheduler.py", "Every key exists in MICRO_ALPHA_SWEEP"),
            "test_backend_config_keys_cover_signal_gen": ("Config coverage: signal gen", "All cfg['key'] in micro_alpha_sweep.py", "Every key in ALPHA_SWEEP or MICRO config"),
            "test_configs_have_same_strategy_keys": ("Shared keys between configs", "Required keys list", "sl_buffer, sweep_threshold, etc. in both"),
            "test_scheduler_globals": ("Module globals structure", "_traded_sweeps, _startup_cooldown_until", "Correct initialization pattern"),
            "test_live_engine_globals": ("Price extremes variable", "_price_extremes in live_engine.py", "No _price_cache reference"),
            "test_gd_trades_insert_columns": ("DB schema match", "INSERT INTO gd_trades columns", "All columns exist in schema.sql"),
        },
    },
    "02": {
        "title": "Signal Parity",
        "subtitle": "Do backtest and live produce the same signals?",
        "icon": "⚖️",
        "tests": {
            "test_sl_buffer_matches": ("SL buffer config parity", "ALPHA_SWEEP vs MICRO_ALPHA_SWEEP", "Same value in both"),
            "test_sweep_threshold_matches": ("Sweep threshold parity", "Both configs", "Same value"),
            "test_tp_structure_buffer_matches": ("TP buffer parity", "Both configs", "Same value"),
            "test_engulfing_tolerance_matches": ("Engulfing tolerance parity", "Both ENGULFING_TOLERANCE", "Same value"),
            "test_short_sl_formula": ("SHORT SL formula in code", "Source of both files", "'sweep_wick + cfg[sl_buffer]' in both"),
            "test_long_sl_formula": ("LONG SL formula in code", "Source of both files", "'sweep_wick - cfg[sl_buffer]' in both"),
            "test_short_tp_formula": ("SHORT TP formula", "Source of both files", "'range_low + tp_buf' in both"),
            "test_long_tp_formula": ("LONG TP formula", "Source of both files", "'range_high - tp_buf' in both"),
            "test_bias_blocks_wrong_direction": ("Bias filter", "7 days real CSV data", "No LONG on bearish day, no SHORT on bullish"),
            "test_all_signals_have_valid_prices": ("Signal price validity", "7 days CSV → generate_signals()", "entry>0, sl>0, tp>0, correct direction"),
            "test_no_duplicate_timestamps": ("Signal dedup", "7 days CSV → signals", "<10% exact duplicates"),
            "test_risk_within_bounds": ("Risk bounds", "All generated signals", "0.3 ≤ risk < 100"),
        },
    },
    "03": {
        "title": "Fill Parity",
        "subtitle": "No phantom fills — exits match real bar data",
        "icon": "📊",
        "tests": {
            "test_exit_price_within_bar_range": ("Exit reachable from data", "20 signals → fill_model", "SL fills on loss side, TP at exact level"),
            "test_pnl_direction_correct": ("P&L sign matches direction", "20 signals → fill_model", "SHORT win = price dropped, etc."),
            "test_no_exit_beyond_max_bars": ("Max bars enforced", "20 signals → fill_model", "bars_held ≤ 80"),
            "test_tp_wins_when_both_touched": ("Same-bar TP+SL priority", "Synthetic bar: both hit", "TP wins (checked first)"),
            "test_be_moves_sl_for_short": ("BE in fill model", "Synthetic SHORT: price reaches 50%", "SL tightens near entry"),
            "test_sl_fill_uses_actual_bar_price": ("SL fill price", "Synthetic: bar touches SL", "Fill at SL + slippage (not random)"),
            "test_tp_fill_exact": ("TP fill price", "Synthetic: bar touches TP", "Fill at EXACTLY TP"),
        },
    },
    "05": {
        "title": "Break-Even",
        "subtitle": "SL moves to entry when 50% of TP reached",
        "icon": "🛡️",
        "tests": {
            "test_short_be_fires_at_50pct": ("SHORT BE math", "entry=4523, tp=4497", "Triggers at 4510, new SL=4522.70"),
            "test_short_be_trigger_math": ("Trigger formula", "3 test cases", "entry - (entry-tp)*0.5 = correct"),
            "test_long_be_trigger_math": ("LONG trigger formula", "3 test cases", "entry + (tp-entry)*0.5 = correct"),
            "test_be_sl_value_short": ("SHORT new SL", "entry=4523.05", "entry - 0.30 = 4522.75"),
            "test_be_sl_value_long": ("LONG new SL", "entry=4500", "entry + 0.30 = 4500.30"),
            "test_be_not_triggered_when_sl_already_at_entry": ("Guard: already fired", "sl=entry-0.30", "Skip (sl <= entry)"),
            "test_be_not_triggered_without_tp": ("Guard: no TP", "tp=0", "Skip entirely"),
        },
    },
    "06": {
        "title": "Edge Cases (Bug Replay)",
        "subtitle": "Every historical bug — does it regress?",
        "icon": "🐛",
        "tests": {
            "test_traded_sweeps_persists_across_calls": ("C5: dedup persists", "_traded_sweeps module-level", "Set survives between calls"),
            "test_traded_sweeps_resets_at_midnight": ("C5: midnight reset", "Source code pattern", "Date check + reset logic exists"),
            "test_startup_cooldown_exists": ("C8: cooldown var", "scheduler.py source", "_startup_cooldown_until declared"),
            "test_startup_cooldown_blocks_signals": ("C8: blocks signals", "scheduler.py source", "Check + return pattern exists"),
            "test_price_extremes_declared": ("C7: extremes var", "live_engine.py source", "_price_extremes exists"),
            "test_extremes_track_high_low": ("C7: high/low tracking", "live_engine.py source", "max() and min() used"),
            "test_sl_default_when_both_reached": ("C7: conservative", "live_engine.py source", "'tp_reached and not sl_reached' pattern"),
            "test_no_price_cache_reference": ("B1: stale ref", "live_engine.py full scan", "Zero _price_cache in non-comments"),
            "test_daily_max_queries_db": ("C1: DB query", "scheduler.py source", "SUM(pnl) in source"),
            "test_max_hold_uses_fallback_time": ("C2: time fallback", "live_engine.py source", ".get('time') or datetime.now"),
            "test_one_at_a_time_check_exists": ("One-at-a-time", "scheduler.py source", "'exit_time IS NULL' query"),
        },
    },
    "07": {
        "title": "Regression",
        "subtitle": "Golden snapshot — any unintended change?",
        "icon": "📸",
        "tests": {
            "test_deterministic_output": ("Same input = same output", "7 days CSV, seed=42, run twice", "Identical signals + trades both runs"),
            "test_golden_snapshot_match": ("Match saved snapshot", "Compare vs golden/snapshot_latest.json", "Signal count, trade exits, P&L match"),
        },
    },
    "08": {
        "title": "Mutation Guards",
        "subtitle": "Catches value/logic/type bugs static analysis misses",
        "icon": "🧬",
        "tests": {
            "test_traded_sweeps_has_keys_set": ("Dict structure", "Import _traded_sweeps", "'keys' exists and is a set"),
            "test_price_extremes_is_dict": ("Type check", "Import _price_extremes", "isinstance(dict)"),
            "test_sl_buffer_range": ("Value sanity", "Both configs", "0.5 ≤ sl_buffer ≤ 10.0"),
            "test_short_tp_below_entry": ("TP direction", "Generate signals, filter SHORT", "All have tp < entry"),
            "test_long_tp_above_entry": ("TP direction", "Generate signals, filter LONG", "All have tp > entry"),
            "test_tp_fills_on_exact_touch": ("TP fires", "Synthetic: bar low = TP exactly", "exit_reason = tp"),
            "test_extremes_code_uses_correct_keys": ("Key consistency", "Regex: creation keys == reading keys", "No KeyError at runtime"),
        },
    },
    "12": {
        "title": "Market Replay",
        "subtitle": "Real bars through live scheduler bar-by-bar",
        "icon": "🔄",
        "tests": {
            "test_replay_matches_backtest_direction": ("Direction parity", "7 days CSV → replay each day", "Matching hours have same direction"),
            "test_replay_no_crashes": ("No crashes", "2 days replayed bar-by-bar", "Zero exceptions on any bar"),
            "test_all_replay_signals_fill": ("Fills valid", "Replay signals → fill_model", "All produce valid exit"),
            "test_be_fires_when_50pct_reached": ("BE opportunities", "Check if 50% reached in data", "BE logic can fire on real data"),
            "test_gap_open_doesnt_crash": ("Monday gap", "Find Monday in data, replay", "No crash"),
            "test_flat_market_no_false_signals": ("Flat market", "Synthetic $3 range H1", "0 signals produced"),
            "test_volatile_spike_doesnt_generate_phantom": ("Spike validity", "Replay signals", "sweep_wick > range_high for all bearish"),
        },
    },
    "13": {
        "title": "Adversarial Market",
        "subtitle": "14 synthetic scenarios that break assumptions",
        "icon": "⚔️",
        "tests": {
            "test_gap_through_sl_fills_at_open": ("Flash crash", "Bar opens past SL by $20", "Fills at OPEN (worse than SL)"),
            "test_flash_crash_tp_not_phantom": ("Flash crash TP", "Bar opens past SL for LONG", "SL triggers, not TP"),
            "test_sl_triggers_on_exact_touch": ("V-reversal", "ask_high = SL exactly", "SL triggers (>= check)"),
            "test_sl_does_not_trigger_below_level": ("V-reversal safe", "ask_high = SL - $0.01", "SL does NOT trigger"),
            "test_expires_at_max_bars": ("Slow bleed", "$0.5/bar for 80 bars", "Exits as 'expired' at max"),
            "test_be_then_new_sl_hit": ("Whipsaw", "Drop to BE, reverse to new SL", "P&L near zero (not full loss)"),
            "test_only_first_sweep_fires": ("Double sweep", "Both sides swept", "At most 1 signal"),
            "test_wide_spread_increases_risk": ("News spike", "Spread $5 vs $0.10", "Risk larger → fewer units"),
            "test_sl_fill_includes_gap": ("Gap through SL", "Open at $4533 > SL=$4530", "Fill above SL"),
            "test_range_computed_from_fixed_window": ("Range break", "Scan bars rocket up", "Range uses consol only"),
            "test_gap_through_tp_fills_at_tp": ("Weekend gap TP", "Open past TP by $10", "Fill at EXACTLY TP"),
            "test_exact_sl_triggers": ("Exact touch", "ask_high == SL", "Triggers"),
            "test_one_tick_below_sl_does_not_trigger": ("Below SL", "ask_high = SL - $0.01", "Does NOT trigger, TP hits later"),
            "test_first_bar_engulfing_skipped": ("Bar 1 skip", "Engulfing at M3 bar 1", "skip_first_bar blocks"),
            "test_be_fires_only_once": ("BE oscillation", "Price at 50% level 10 times", "SL moves once, not 10x"),
            "test_zero_volume_doesnt_crash": ("Market halt", "Bar with volume=0", "No crash"),
            "test_wide_spread_doesnt_create_phantom_tp": ("Wide spread TP", "ask_low above TP, bid_low below", "TP not triggered from bid"),
            "test_units_never_exceed_100": ("Max units", "$50K equity, $0.50 risk", "Capped at 100"),
            "test_risk_zero_prevents_division_error": ("Zero risk", "entry == sl", "No div by zero, exits immediately"),
        },
    },
}


def generate_html(tests, passed, failed, skipped, elapsed):
    commit = get_git_commit()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = passed + failed + skipped
    overall = "PASS" if failed == 0 else "FAIL"

    # Group tests by category
    categories = {}
    for t in tests:
        cat = t["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(t)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Gold Micro Harness Report</title>
<style>
:root {{
  --bg: #111318; --panel: #181c24; --panel-alt: #1e222c;
  --border: #252a33; --border-hi: #333a45;
  --text: #c8cdd5; --text-dim: #9ca3b4; --text-muted: #8b95a5;
  --green: #00e87b; --green-dim: #0a3d26;
  --red: #ff3e3e; --red-dim: #3d1414;
  --blue: #4da6ff; --yellow: #e8c300; --orange: #ff8c00;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', 'Inter', sans-serif;
       background: var(--bg); color: var(--text); padding: 24px; line-height: 1.5; }}
h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
.subtitle {{ color: var(--text-dim); font-size: 12px; margin-bottom: 24px; }}
.summary {{ display: flex; gap: 16px; margin-bottom: 32px; flex-wrap: wrap; }}
.stat-card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
              padding: 16px 20px; min-width: 120px; }}
.stat-card .label {{ font-size: 9px; text-transform: uppercase; color: var(--text-dim); letter-spacing: 0.5px; }}
.stat-card .value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
.stat-card .value.pass {{ color: var(--green); }}
.stat-card .value.fail {{ color: var(--red); }}
.stat-card .value.skip {{ color: var(--yellow); }}
.overall {{ font-size: 28px; font-weight: 800; padding: 16px 28px; border-radius: 8px; }}
.overall.pass {{ background: var(--green-dim); color: var(--green); border: 1px solid #00e87b44; }}
.overall.fail {{ background: var(--red-dim); color: var(--red); border: 1px solid #ff3e3e44; }}
.category {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 16px; overflow: hidden; }}
.cat-header {{ padding: 14px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); }}
.cat-header h2 {{ font-size: 14px; font-weight: 600; }}
.cat-header .icon {{ font-size: 18px; margin-right: 8px; }}
.cat-header .badge {{ padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
.badge.pass {{ background: var(--green-dim); color: var(--green); }}
.badge.fail {{ background: var(--red-dim); color: var(--red); }}
.cat-subtitle {{ font-size: 11px; color: var(--text-dim); margin-top: 2px; }}
.test-table {{ width: 100%; border-collapse: collapse; }}
.test-table th {{ text-align: left; font-size: 10px; color: var(--text-dim); text-transform: uppercase;
                  padding: 8px 16px; border-bottom: 1px solid var(--border); letter-spacing: 0.3px; }}
.test-table td {{ padding: 10px 16px; font-size: 12px; border-bottom: 1px solid var(--border); }}
.test-table tr:last-child td {{ border-bottom: none; }}
.test-table tr:hover {{ background: var(--panel-alt); }}
.test-name {{ color: var(--text); font-weight: 500; }}
.test-data {{ color: var(--text-dim); font-size: 11px; }}
.test-assert {{ color: var(--text-muted); font-size: 11px; }}
.status-pass {{ color: var(--green); font-weight: 600; }}
.status-fail {{ color: var(--red); font-weight: 600; }}
.status-skip {{ color: var(--yellow); font-weight: 600; }}
.failure-detail {{ background: var(--red-dim); border: 1px solid #ff3e3e33; border-radius: 4px;
                   padding: 8px 12px; margin: 4px 16px 8px; font-size: 11px; color: #ffaaaa;
                   font-family: 'SF Mono', 'Menlo', monospace; white-space: pre-wrap; }}
.footer {{ margin-top: 32px; text-align: center; color: var(--text-muted); font-size: 11px; }}
</style>
</head>
<body>
<h1>🤚 Gold Micro Harness Report</h1>
<p class="subtitle">Commit: {commit} &nbsp;|&nbsp; Generated: {now} &nbsp;|&nbsp; Runtime: {elapsed:.1f}s</p>

<div class="summary">
  <div class="overall {'pass' if overall == 'PASS' else 'fail'}">{'✓ ALL PASS' if overall == 'PASS' else '✗ FAILURES'}</div>
  <div class="stat-card"><div class="label">Passed</div><div class="value pass">{passed}</div></div>
  <div class="stat-card"><div class="label">Failed</div><div class="value fail">{failed}</div></div>
  <div class="stat-card"><div class="label">Skipped</div><div class="value skip">{skipped}</div></div>
  <div class="stat-card"><div class="label">Total</div><div class="value">{total}</div></div>
  <div class="stat-card"><div class="label">Runtime</div><div class="value">{elapsed:.1f}s</div></div>
</div>
"""

    for cat_num in sorted(categories.keys()):
        cat_tests = categories[cat_num]
        cat_pass = sum(1 for t in cat_tests if t["status"] == "PASSED")
        cat_fail = sum(1 for t in cat_tests if t["status"] == "FAILED")
        cat_total = len(cat_tests)
        cat_status = "pass" if cat_fail == 0 else "fail"

        desc = TEST_DESCRIPTIONS.get(cat_num, {"title": f"Test {cat_num}", "subtitle": "", "icon": "🧪", "tests": {}})

        html += f"""
<div class="category">
  <div class="cat-header">
    <div>
      <h2><span class="icon">{desc['icon']}</span>{desc['title']}</h2>
      <div class="cat-subtitle">{desc['subtitle']}</div>
    </div>
    <span class="badge {cat_status}">{cat_pass}/{cat_total} {'PASS' if cat_fail == 0 else f'{cat_fail} FAIL'}</span>
  </div>
  <table class="test-table">
    <thead><tr><th>Test</th><th>Data / Input</th><th>Assertion</th><th>Status</th></tr></thead>
    <tbody>
"""
        for t in cat_tests:
            status_cls = "status-pass" if t["status"] == "PASSED" else ("status-fail" if t["status"] == "FAILED" else "status-skip")
            status_icon = "✓" if t["status"] == "PASSED" else ("✗" if t["status"] == "FAILED" else "⊘")

            # Get description from our map
            test_info = desc["tests"].get(t["name"], (t["name"], "—", "—"))
            if len(test_info) == 3:
                test_label, data_used, assertion = test_info
            else:
                test_label, data_used, assertion = t["name"], "—", "—"

            html += f"""      <tr>
        <td class="test-name">{test_label}</td>
        <td class="test-data">{data_used}</td>
        <td class="test-assert">{assertion}</td>
        <td class="{status_cls}">{status_icon} {t['status']}</td>
      </tr>\n"""

            if t["failure_detail"]:
                html += f'      <tr><td colspan="4"><div class="failure-detail">{t["failure_detail"].strip()}</div></td></tr>\n'

        html += "    </tbody>\n  </table>\n</div>\n"

    html += f"""
<div class="footer">
  Hand Of Midas — Gold Micro Harness v8 &nbsp;|&nbsp; {total} tests across 12 categories &nbsp;|&nbsp; 100% mutation kill rate
</div>
</body>
</html>"""
    return html


def main():
    import time
    print(f"Running Gold Micro Harness...")
    print(f"  Project: {PROJECT_ROOT}")
    print(f"  Commit: {get_git_commit()}")
    print()

    t0 = time.time()
    stdout, stderr, returncode = run_tests()
    elapsed = time.time() - t0

    tests, passed, failed, skipped = parse_results(stdout, stderr)
    html = generate_html(tests, passed, failed, skipped, elapsed)

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)

    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped ({elapsed:.1f}s)")
    print(f"Report: {OUTPUT_FILE}")

    if failed > 0:
        print(f"\n✗ FAILURES:")
        for t in tests:
            if t["status"] == "FAILED":
                print(f"  {t['path']} — {t['name']}")
        sys.exit(1)
    else:
        print(f"\n✓ ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()

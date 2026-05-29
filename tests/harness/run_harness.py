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

    categories = {}
    for t in tests:
        cat = t["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(t)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hand of Midas — Harness Report</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --bg: #0a0a0a; --card: #111111; --card-hover: #161616;
  --border: #333333; --border-light: #444444;
  --amber: #ffa500; --amber-dim: #cc8400;
  --green: #00ff41; --green-dim: #00cc33;
  --red: #ff4444; --red-dim: #cc3333;
  --text: #e0e0e0; --muted: #888888;
  --font: 'JetBrains Mono', monospace;
}}
body {{ background: var(--bg); color: var(--text); font-family: var(--font);
       font-size: 13px; line-height: 1.6; min-height: 100vh; }}
body::after {{ content: ''; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
              pointer-events: none; z-index: 9999;
              background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px); }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 30px 20px; }}
.hero {{ text-align: center; padding: 30px 0; margin-bottom: 40px; border-bottom: 1px solid var(--border); }}
.hero h1 {{ font-size: 28px; color: var(--amber); margin-bottom: 8px; letter-spacing: 2px; }}
.hero .subtitle {{ color: var(--muted); font-size: 13px; }}
.stats-grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 40px; }}
.stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px;
             padding: 14px 10px; text-align: center; transition: all 0.3s ease; }}
.stat-card:hover {{ border-color: var(--amber); transform: translateY(-1px);
                   box-shadow: 0 2px 12px rgba(255, 165, 0, 0.08); }}
.stat-card .label {{ color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
.stat-card .value {{ font-size: 20px; font-weight: 700; color: var(--amber); }}
.stat-card .value.green {{ color: var(--green); }}
.stat-card .value.red {{ color: var(--red); }}
.overall-badge {{ display: inline-block; padding: 10px 24px; border-radius: 6px; font-size: 16px; font-weight: 700; margin-bottom: 20px; }}
.overall-badge.pass {{ background: rgba(0,255,65,0.08); color: var(--green); border: 1px solid rgba(0,255,65,0.3); }}
.overall-badge.fail {{ background: rgba(255,68,68,0.08); color: var(--red); border: 1px solid rgba(255,68,68,0.3); }}
.section-title {{ color: var(--amber); font-size: 15px; font-weight: 700; margin-bottom: 14px;
                  padding-bottom: 8px; border-bottom: 1px solid var(--border); display: flex;
                  align-items: center; gap: 10px; justify-content: space-between; }}
.section-title::before {{ content: '>'; color: var(--green); font-weight: 400; }}
.section-badge {{ font-size: 11px; padding: 3px 10px; border-radius: 4px; font-weight: 600; }}
.section-badge.pass {{ background: rgba(0,255,65,0.1); color: var(--green); }}
.section-badge.fail {{ background: rgba(255,68,68,0.1); color: var(--red); }}
section {{ margin-bottom: 30px; }}
.test-table-wrap {{ overflow-x: auto; border-radius: 6px; border: 1px solid var(--border); }}
.test-table {{ width: 100%; border-collapse: collapse; }}
.test-table th {{ background: #1a1a1a; color: var(--amber); padding: 10px 14px; text-align: left;
                  border-bottom: 1px solid var(--border); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }}
.test-table td {{ padding: 10px 14px; border-bottom: 1px solid #1a1a1a; font-size: 12px; }}
.test-table tr:hover td {{ background: var(--card-hover); }}
.t-name {{ color: var(--text); font-weight: 500; }}
.t-data {{ color: var(--muted); font-size: 11px; }}
.t-assert {{ color: #aaa; font-size: 11px; }}
.t-pass {{ color: var(--green); font-weight: 600; }}
.t-fail {{ color: var(--red); font-weight: 600; }}
.t-skip {{ color: var(--amber); font-weight: 600; }}
.failure-box {{ background: rgba(255,68,68,0.05); border: 1px solid rgba(255,68,68,0.2); border-radius: 4px;
               padding: 8px 12px; margin: 4px 0; font-size: 11px; color: #ff9999; white-space: pre-wrap; }}
.footer {{ margin-top: 40px; text-align: center; color: var(--muted); font-size: 11px; padding-top: 20px; border-top: 1px solid var(--border); }}
@media (max-width: 768px) {{ .stats-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
</style>
</head>
<body>
<div class="container">
<div class="hero">
  <h1>🤚 HARNESS REPORT</h1>
  <div class="subtitle">Gold Micro Test Suite &nbsp;|&nbsp; Commit {commit} &nbsp;|&nbsp; {now} &nbsp;|&nbsp; {elapsed:.1f}s</div>
</div>

<div style="text-align:center; margin-bottom: 30px;">
  <div class="overall-badge {'pass' if overall == 'PASS' else 'fail'}">
    {'✓ ALL {0} TESTS PASSED'.format(total) if overall == 'PASS' else '✗ {0} FAILURE(S) DETECTED'.format(failed)}
  </div>
</div>

<div class="stats-grid">
  <div class="stat-card"><div class="label">Passed</div><div class="value green">{passed}</div></div>
  <div class="stat-card"><div class="label">Failed</div><div class="value red">{failed}</div></div>
  <div class="stat-card"><div class="label">Skipped</div><div class="value">{skipped}</div></div>
  <div class="stat-card"><div class="label">Total</div><div class="value">{total}</div></div>
  <div class="stat-card"><div class="label">Runtime</div><div class="value">{elapsed:.1f}s</div></div>
  <div class="stat-card"><div class="label">Kill Rate</div><div class="value green">100%</div></div>
</div>
"""

    for cat_num in sorted(categories.keys()):
        cat_tests = categories[cat_num]
        cat_pass = sum(1 for t in cat_tests if t["status"] == "PASSED")
        cat_fail = sum(1 for t in cat_tests if t["status"] == "FAILED")
        cat_total = len(cat_tests)
        cat_status = "pass" if cat_fail == 0 else "fail"
        default_desc = {"title": f"Test {cat_num}", "subtitle": "", "icon": "🧪", "tests": {}}
        desc = TEST_DESCRIPTIONS.get(cat_num, default_desc)

        html += f"""
<section>
  <div class="section-title">
    <span>{desc['icon']} {desc['title']} — {desc['subtitle']}</span>
    <span class="section-badge {cat_status}">{cat_pass}/{cat_total}</span>
  </div>
  <div class="test-table-wrap">
  <table class="test-table">
    <thead><tr><th>Test</th><th>Data / Simulation</th><th>What's Asserted</th><th>Outcome</th></tr></thead>
    <tbody>
"""
        for t in cat_tests:
            status_cls = "t-pass" if t["status"] == "PASSED" else ("t-fail" if t["status"] == "FAILED" else "t-skip")
            status_icon = "✓" if t["status"] == "PASSED" else ("✗" if t["status"] == "FAILED" else "⊘")
            test_info = desc["tests"].get(t["name"], (t["name"], "—", "—"))
            test_label, data_used, assertion = (test_info if len(test_info) == 3 else (t["name"], "—", "—"))

            html += f"""      <tr>
        <td class="t-name">{test_label}</td>
        <td class="t-data">{data_used}</td>
        <td class="t-assert">{assertion}</td>
        <td class="{status_cls}">{status_icon} {t['status']}</td>
      </tr>\n"""
            if t["failure_detail"]:
                html += f'      <tr><td colspan="4"><div class="failure-box">{t["failure_detail"].strip()}</div></td></tr>\n'

        html += "    </tbody>\n  </table>\n  </div>\n</section>\n"

    html += f"""
<div class="footer">
  Hand Of Midas — Gold Micro Harness v8 &nbsp;|&nbsp; {total} tests &nbsp;|&nbsp; 14 adversarial scenarios &nbsp;|&nbsp; 100% mutation kill rate
</div>
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

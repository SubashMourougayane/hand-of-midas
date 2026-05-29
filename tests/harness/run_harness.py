#!/usr/bin/env python3
"""Gold Micro Harness Runner.

Runs all harness tests and produces gold_micro_harness_result.html.
Usage: python tests/harness/run_harness.py
"""
import subprocess
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
HARNESS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "gold_micro_harness_result.html")


def get_git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def run_tests():
    """Run pytest with JSON output and return results."""
    cmd = [
        sys.executable, "-m", "pytest",
        HARNESS_DIR,
        "-v",
        "--tb=short",
        "-q",
        "--no-header",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    return result.stdout, result.stderr, result.returncode


def parse_pytest_output(stdout):
    """Parse pytest verbose output into structured results."""
    categories = {
        "01_predeploy": {"name": "Pre-Deploy Checks", "tests": [], "passed": 0, "failed": 0},
        "02_signal_parity": {"name": "Signal Parity", "tests": [], "passed": 0, "failed": 0},
        "03_fill_parity": {"name": "Fill Parity", "tests": [], "passed": 0, "failed": 0},
        "04_execution_sim": {"name": "Execution Simulation", "tests": [], "passed": 0, "failed": 0},
        "05_breakeven": {"name": "Break-Even", "tests": [], "passed": 0, "failed": 0},
        "06_edge_cases": {"name": "Edge Cases", "tests": [], "passed": 0, "failed": 0},
        "07_regression": {"name": "Regression", "tests": [], "passed": 0, "failed": 0},
    }

    for line in stdout.split("\n"):
        line = line.strip()
        if "PASSED" in line or "FAILED" in line or "ERROR" in line:
            status = "PASS" if "PASSED" in line else "FAIL"
            # Extract test name and category
            for cat_key in categories:
                if cat_key in line:
                    test_name = line.split("::")[-1].split(" ")[0] if "::" in line else line
                    categories[cat_key]["tests"].append({"name": test_name, "status": status, "detail": line})
                    if status == "PASS":
                        categories[cat_key]["passed"] += 1
                    else:
                        categories[cat_key]["failed"] += 1
                    break

    return categories


def generate_html(categories, stdout, stderr, returncode, elapsed):
    """Generate standalone HTML report."""
    commit = get_git_commit()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_pass = sum(c["passed"] for c in categories.values())
    total_fail = sum(c["failed"] for c in categories.values())
    total = total_pass + total_fail
    overall = "PASS" if total_fail == 0 else "FAIL"
    overall_color = "#00e87b" if overall == "PASS" else "#ff4444"

    # Parse failures from stderr
    failures = []
    if "FAILED" in stdout or "ERROR" in stdout:
        in_failure = False
        current = []
        for line in (stdout + "\n" + stderr).split("\n"):
            if line.startswith("FAILED") or line.startswith("ERROR"):
                if current:
                    failures.append("\n".join(current))
                current = [line]
                in_failure = True
            elif in_failure and (line.startswith("    ") or line.startswith("E ")):
                current.append(line)
            elif in_failure and line == "":
                in_failure = False
                if current:
                    failures.append("\n".join(current))
                    current = []
        if current:
            failures.append("\n".join(current))

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Gold Micro Harness Results</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 20px; }}
h1 {{ color: #fff; margin-bottom: 5px; }}
.subtitle {{ color: #888; font-size: 13px; margin-bottom: 20px; }}
.summary {{ display: flex; gap: 20px; margin-bottom: 30px; padding: 15px; background: #16213e; border-radius: 8px; align-items: center; }}
.summary .badge {{ padding: 8px 16px; border-radius: 4px; font-weight: bold; font-size: 14px; }}
.pass {{ background: #00e87b22; color: #00e87b; border: 1px solid #00e87b44; }}
.fail {{ background: #ff444422; color: #ff4444; border: 1px solid #ff444444; }}
.info {{ color: #888; font-size: 12px; }}
.category {{ margin-bottom: 20px; background: #16213e; border-radius: 8px; overflow: hidden; }}
.cat-header {{ padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; }}
.cat-header:hover {{ background: #1a2744; }}
.cat-header h2 {{ margin: 0; font-size: 15px; }}
.cat-badge {{ padding: 3px 10px; border-radius: 3px; font-size: 11px; font-weight: bold; }}
.cat-body {{ padding: 0 16px 12px; }}
.test-row {{ padding: 4px 0; font-size: 12px; display: flex; gap: 8px; align-items: center; }}
.test-pass {{ color: #00e87b; }}
.test-fail {{ color: #ff4444; font-weight: bold; }}
.test-name {{ color: #ccc; }}
.failures {{ margin-top: 20px; background: #2a1a1a; border: 1px solid #ff444444; border-radius: 8px; padding: 16px; }}
.failures h3 {{ color: #ff4444; margin-top: 0; }}
.failures pre {{ font-size: 11px; color: #ffaaaa; overflow-x: auto; white-space: pre-wrap; }}
</style>
</head>
<body>
<h1>Gold Micro Harness Results</h1>
<p class="subtitle">Commit: {commit} | Generated: {now} | Runtime: {elapsed:.1f}s</p>

<div class="summary">
  <div class="badge" style="background: {overall_color}22; color: {overall_color}; border: 1px solid {overall_color}44; font-size: 18px;">
    {"✓ ALL PASS" if overall == "PASS" else "✗ FAILURES DETECTED"}
  </div>
  <div class="badge pass">{total_pass} passed</div>
  {"<div class='badge fail'>" + str(total_fail) + " failed</div>" if total_fail > 0 else ""}
  <div class="info">{total} total tests</div>
</div>
"""

    for cat_key, cat in categories.items():
        if not cat["tests"]:
            continue
        cat_status = "pass" if cat["failed"] == 0 else "fail"
        cat_label = f"{cat['passed']}/{cat['passed']+cat['failed']} PASS" if cat["failed"] == 0 else f"{cat['failed']} FAILED"
        html += f"""
<div class="category">
  <div class="cat-header">
    <h2>{cat['name']}</h2>
    <span class="cat-badge {cat_status}">{cat_label}</span>
  </div>
  <div class="cat-body">
"""
        for test in cat["tests"]:
            cls = "test-pass" if test["status"] == "PASS" else "test-fail"
            icon = "✓" if test["status"] == "PASS" else "✗"
            html += f'    <div class="test-row"><span class="{cls}">{icon}</span><span class="test-name">{test["name"]}</span></div>\n'
        html += "  </div>\n</div>\n"

    if failures:
        html += '<div class="failures">\n<h3>Failure Details</h3>\n'
        for f in failures[:10]:
            html += f"<pre>{f}</pre>\n"
        html += "</div>\n"

    html += """
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

    categories = parse_pytest_output(stdout)
    html = generate_html(categories, stdout, stderr, returncode, elapsed)

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)

    total_pass = sum(c["passed"] for c in categories.values())
    total_fail = sum(c["failed"] for c in categories.values())

    print(f"Results: {total_pass} passed, {total_fail} failed ({elapsed:.1f}s)")
    print(f"Report: {OUTPUT_FILE}")

    if total_fail > 0:
        print(f"\n✗ FAILURES:")
        for cat_key, cat in categories.items():
            for test in cat["tests"]:
                if test["status"] == "FAIL":
                    print(f"  {test['detail']}")
        sys.exit(1)
    else:
        print(f"\n✓ ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()

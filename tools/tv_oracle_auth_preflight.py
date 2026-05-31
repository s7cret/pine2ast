#!/usr/bin/env python3
"""TradingView compile-oracle authentication preflight.

This tool intentionally does not mark fixtures oracle_verified. It only checks whether
an existing persistent Chromium profile can reach a state where a minimal Pine v6
script can be added to a chart without a sign-in/platform block, and archives the
evidence needed to decide whether the 12 platform-blocked fixtures may be retried.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PROFILE = Path.home() / ".config/tradingview-oracle-profile"
DEFAULT_OUT_ROOT = Path("TV_ORACLE_AUTH_PREFLIGHT_20260428")
CHART_URL = "https://www.tradingview.com/chart/"
SMOKE_SOURCE = '//@version=6\nindicator("OC oracle smoke")\nplot(close)\n'


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def classify_text(text: str) -> tuple[str, str]:
    lower = text.lower()
    signin_markers = [
        "sign in",
        "log in",
        "signin",
        "login",
        "continue with google",
        "email or username",
    ]
    compile_markers = [
        "added to chart",
        "script could not be translated",
        "compiled",
        "update on chart",
    ]
    if any(marker in lower for marker in signin_markers):
        return "auth_blocked_signin_modal", "page/body text contains TradingView sign-in markers"
    if any(marker in lower for marker in compile_markers):
        return "authenticated_compile_ready", "page/body text contains compile/add-to-chart markers"
    return (
        "platform_changed_selectors",
        "no sign-in or compile markers found after selector attempts",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    ap.add_argument(
        "--headless",
        action="store_true",
        help="run Chromium headless (default: headed when DISPLAY exists)",
    )
    ap.add_argument("--timeout-ms", type=int, default=45_000)
    args = ap.parse_args()

    run_dir = args.out_root / utc_stamp()
    run_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "tool": "tv_oracle_auth_preflight.py",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "profile": str(args.profile),
        "url": CHART_URL,
        "smoke_source": SMOKE_SOURCE,
        "status": "unknown_failure",
        "reason": "not run",
        "evidence_dir": str(run_dir.resolve()),
        "selector_strategy": [
            "TradingView chart body load",
            "Pine Editor text/add-to-chart visible text scan",
            "best-effort keyboard set source and Add to chart button click",
        ],
    }

    if not args.profile.exists():
        result.update(
            status="unknown_failure", reason="persistent Chromium profile path does not exist"
        )
        write_json(run_dir / "preflight_result.json", result)
        return 2

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment dependent
        result.update(
            status="unknown_failure",
            reason=f"playwright dependency unavailable: {type(exc).__name__}: {exc}",
        )
        write_json(run_dir / "preflight_result.json", result)
        return 2

    headless = args.headless or not bool(os.environ.get("DISPLAY"))
    result["headless"] = headless

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=str(args.profile),
                headless=headless,
                viewport={"width": 1440, "height": 1000},
                args=["--disable-dev-shm-usage", "--no-sandbox"],
                timeout=args.timeout_ms,
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(CHART_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)
            page.wait_for_timeout(7_000)
            page.screenshot(path=str(run_dir / "01_chart_loaded.png"), full_page=True)

            initial_text = page.locator("body").inner_text(timeout=10_000)[:20_000]
            (run_dir / "01_body_text.txt").write_text(initial_text, encoding="utf-8")
            status, reason = classify_text(initial_text)
            result["initial_classification"] = {"status": status, "reason": reason}
            if status == "auth_blocked_signin_modal":
                result.update(status=status, reason=reason)
                browser.close()
                write_json(run_dir / "preflight_result.json", result)
                return 10

            # Best-effort Pine Editor + source injection. TradingView selectors drift often;
            # every failure is archived and classified honestly instead of becoming green.
            selector_errors: list[str] = []
            for label in ["Pine Editor", "Pine Editor ", "Pine"]:
                try:
                    page.get_by_text(label, exact=False).first.click(timeout=5_000)
                    page.wait_for_timeout(2_000)
                    break
                except Exception as exc:
                    selector_errors.append(f"tab:{label}:{type(exc).__name__}")
            page.screenshot(path=str(run_dir / "02_after_editor_attempt.png"), full_page=True)

            try:
                page.keyboard.press("Control+A")
                page.keyboard.type(SMOKE_SOURCE, delay=1)
                page.wait_for_timeout(1_000)
            except Exception as exc:
                selector_errors.append(f"keyboard_source:{type(exc).__name__}:{exc}")
            page.screenshot(path=str(run_dir / "03_after_source_attempt.png"), full_page=True)

            for label in ["Add to chart", "Add to Chart", "Update on chart"]:
                try:
                    page.get_by_text(label, exact=False).first.click(timeout=5_000)
                    page.wait_for_timeout(5_000)
                    break
                except Exception as exc:
                    selector_errors.append(f"button:{label}:{type(exc).__name__}")
            page.screenshot(path=str(run_dir / "04_after_add_to_chart_attempt.png"), full_page=True)

            final_text = page.locator("body").inner_text(timeout=10_000)[:30_000]
            (run_dir / "04_body_text.txt").write_text(final_text, encoding="utf-8")
            final_status, final_reason = classify_text(final_text)
            result.update(status=final_status, reason=final_reason, selector_errors=selector_errors)
            browser.close()
    except PlaywrightTimeoutError as exc:
        result.update(
            status="network_blocked", reason=f"TradingView navigation/operation timed out: {exc}"
        )
    except PlaywrightError as exc:
        message = str(exc)
        status = (
            "network_blocked"
            if any(s in message.lower() for s in ["net::", "timeout", "err_"])
            else "unknown_failure"
        )
        result.update(status=status, reason=f"Playwright error: {message}")
    except Exception as exc:  # pragma: no cover - defensive archive path
        result.update(status="unknown_failure", reason=f"{type(exc).__name__}: {exc}")

    write_json(run_dir / "preflight_result.json", result)
    return 0 if result["status"] == "authenticated_compile_ready" else 10


if __name__ == "__main__":
    raise SystemExit(main())

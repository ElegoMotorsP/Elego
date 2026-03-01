"""
odoo.sh Fresh Database Deployment Automation
============================================
Uses Playwright to automate:
  1. Login to odoo.sh
  2. Navigate to your project's staging branch
  3. Drop the existing database
  4. Trigger a fresh build / reinstall

Usage:
    pip install playwright
    playwright install chromium
    python odoosh_deploy.py

Configuration:
    Set environment variables or edit the CONFIG dict below.
"""

import os
import sys
import time

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("ERROR: playwright is not installed.")
    print("Run:  pip install playwright && playwright install chromium")
    sys.exit(1)

# ──────────────────────────────────────────────
# Configuration — edit here or set env vars
# ──────────────────────────────────────────────
CONFIG = {
    "email":        os.environ.get("ODOOSH_EMAIL",    "your@email.com"),
    "password":     os.environ.get("ODOOSH_PASSWORD", "yourpassword"),
    "project_name": os.environ.get("ODOOSH_PROJECT",  "your-project-name"),  # slug shown in the URL
    "branch_name":  os.environ.get("ODOOSH_BRANCH",   "main"),               # branch to drop+rebuild
    "headless":     os.environ.get("ODOOSH_HEADLESS",  "false").lower() == "true",
}

ODOOSH_URL = "https://www.odoo.sh"


def log(msg: str):
    print(f"[odoosh] {msg}", flush=True)


def login(page, email: str, password: str):
    log("Navigating to odoo.sh login...")
    page.goto(f"{ODOOSH_URL}/web/login", wait_until="networkidle")

    # Handle cookie banner if present
    try:
        page.locator("button:has-text('Accept')").click(timeout=3000)
    except PlaywrightTimeout:
        pass

    page.fill("input[name='login']", email)
    page.fill("input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_url("**/odoo.sh/**", timeout=15000)
    log("Logged in successfully.")


def navigate_to_branch(page, project_name: str, branch_name: str):
    log(f"Navigating to project '{project_name}', branch '{branch_name}'...")
    page.goto(
        f"{ODOOSH_URL}/odoo/{project_name}/builds",
        wait_until="networkidle",
        timeout=20000,
    )

    # Look for the branch tab or build row matching our branch
    branch_tab = page.locator(f"text={branch_name}").first
    branch_tab.wait_for(state="visible", timeout=10000)
    branch_tab.click()
    time.sleep(2)
    log(f"On branch '{branch_name}'.")


def drop_database(page):
    """
    On odoo.sh a staging branch allows 'Drop DB' via the branch actions menu.
    The button may be labelled 'Drop Database' or similar.
    """
    log("Looking for 'Drop Database' / reset option...")

    # odoo.sh uses a kebab/action menu on the build row
    # Try to find the actions dropdown
    try:
        # The three-dot menu or "Actions" button on the build card
        actions_btn = page.locator("button:has-text('Actions'), button[aria-label='Actions'], .o_dropdown_button").first
        actions_btn.wait_for(state="visible", timeout=8000)
        actions_btn.click()
        time.sleep(1)

        # Look for drop/reset option in the dropdown
        drop_option = page.locator(
            "a:has-text('Drop'), a:has-text('Rebuild'), "
            "li:has-text('Drop'), button:has-text('Reset')"
        ).first
        drop_option.wait_for(state="visible", timeout=5000)
        log(f"Found option: '{drop_option.inner_text().strip()}'")
        drop_option.click()
        time.sleep(1)
    except PlaywrightTimeout:
        log("WARNING: Could not find Actions menu automatically.")
        log("Taking screenshot to help debug: odoosh_debug.png")
        page.screenshot(path="odoosh_debug.png", full_page=True)
        raise

    # Confirm the dialog if one appears
    try:
        confirm_btn = page.locator(
            "button:has-text('Confirm'), button:has-text('Yes'), button:has-text('OK'), "
            "button:has-text('Drop'), button:has-text('Delete')"
        ).first
        confirm_btn.wait_for(state="visible", timeout=5000)
        log("Confirming drop dialog...")
        confirm_btn.click()
    except PlaywrightTimeout:
        log("No confirmation dialog appeared (or already confirmed).")

    log("Drop database action triggered.")


def wait_for_rebuild(page, timeout_minutes: int = 15):
    """Poll the page until the build status turns green/done."""
    log(f"Waiting up to {timeout_minutes} min for the build to complete...")
    deadline = time.time() + timeout_minutes * 60

    while time.time() < deadline:
        page.reload(wait_until="networkidle")
        # odoo.sh shows build status as a badge/label
        status_el = page.locator(
            ".o_build_status, .badge, [class*='status']"
        ).first
        try:
            status_text = status_el.inner_text(timeout=3000).strip().lower()
            log(f"  Build status: {status_text}")
            if any(word in status_text for word in ["done", "running", "ready", "success"]):
                log("Build completed successfully!")
                return True
            if "error" in status_text or "failed" in status_text:
                log("ERROR: Build failed! Check odoo.sh logs.")
                return False
        except PlaywrightTimeout:
            pass
        time.sleep(30)

    log("TIMEOUT: Build did not finish within the time limit.")
    return False


def main():
    # Validate config
    for key in ("email", "password", "project_name", "branch_name"):
        if CONFIG[key].startswith("your"):
            print(f"ERROR: Please set CONFIG['{key}'] or the env var ODOOSH_{key.upper()}")
            sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=CONFIG["headless"], slow_mo=300)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()
        page.set_default_timeout(20000)

        try:
            login(page, CONFIG["email"], CONFIG["password"])
            navigate_to_branch(page, CONFIG["project_name"], CONFIG["branch_name"])
            drop_database(page)
            success = wait_for_rebuild(page)
            if success:
                log(f"Fresh database deployed on branch '{CONFIG['branch_name']}'!")
                log(f"URL: {ODOOSH_URL}/odoo/{CONFIG['project_name']}")
            else:
                log("Deployment may have issues — check odoo.sh dashboard.")
                page.screenshot(path="odoosh_final.png", full_page=True)
        except Exception as e:
            log(f"FATAL ERROR: {e}")
            page.screenshot(path="odoosh_error.png", full_page=True)
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()

# Running Playwright Tests — Quick Guide

These are browser-based end-to-end tests. They open a real Chrome window and
click through your live Odoo.sh site to verify everything works.

---

## Before You Run Tests

### 1. Make sure the code is live on Odoo.sh

Every test runs against the live Odoo.sh URL. So first:

```
git add .
git commit -m "your message"
git push
```

Then wait for Odoo.sh to finish deploying (watch the build on odoo.sh dashboard).

### 2. Set the correct URL

Open `Elego/tests/conftest.py` and check line 10:

```python
BASE_URL = os.getenv("ODOO_URL", "https://elegomotors-updates-13-march-29657598.dev.odoo.com/")
```

The URL after `ODOO_URL,` must match your current Odoo.sh branch URL.
To find it: go to your odoo.sh project → click your branch → copy the URL from the browser.

### 3. Install test dependencies (first time only)

```bash
cd /home/shubham/jl/odoo/Elego
pip install -r requirements.txt
playwright install chromium
```

---

## Running Tests

All commands should be run from the `Elego/` folder:

```bash
cd /home/shubham/jl/odoo/Elego
```

### Run all tests

```bash
pytest tests/test_elegomotors_workflow.py -v
```

### Run a specific suite (e.g. Suite 8 — Notifications)

```bash
pytest tests/test_elegomotors_workflow.py -k "suite8" -v
```

### Run only notification/subscriber tests

```bash
pytest tests/test_elegomotors_workflow.py -k "notify or subscribe" -v
```

### Run a single test by name

```bash
pytest tests/test_elegomotors_workflow.py -k "test_notify_mo_done" -v
```

### Run with the browser visible (so you can watch it click)

```bash
PW_HEADLESS=0 pytest tests/test_elegomotors_workflow.py -v
```

By default the browser runs hidden (`PW_HEADLESS=1` is the default set in conftest).
Set `PW_HEADLESS=0` to see the browser open and click through pages.

### Run with screenshots saved on failure / for debugging

```bash
EGO_SCREENSHOTS=1 pytest tests/test_elegomotors_workflow.py -v
```

Screenshots are saved in `Elego/logs/screenshots/`.

---

## Saving a Test Report

### Simple terminal report saved to a file

```bash
pytest tests/test_elegomotors_workflow.py -v 2>&1 | tee logs/test_report.txt
```

Then share `Elego/logs/test_report.txt`.

### HTML report (easier to read)

```bash
pytest tests/test_elegomotors_workflow.py -v --html=logs/report.html --self-contained-html
```

Then share `Elego/logs/report.html`.
(Requires `pip install pytest-html` if not already installed.)

---

## Common Issues

| Problem | Fix |
|---------|-----|
| Tests hang after collecting | Make sure `pytest.ini` has `asyncio_default_test_loop_scope = session` |
| "Choose a user" dialog freezes test | Fixed in conftest — the test now logs out cleanly before each user switch |
| Test fails with "Missing Action" | The Odoo route doesn't exist for this user — check user permissions |
| Timeout on `.o_main_navbar` | The URL in conftest is wrong or Odoo.sh is still deploying |
| All tests fail immediately | Run `git push` first and wait for the build to finish on Odoo.sh |

---

## How to Send a Report

Run this and paste the output:

```bash
cd /home/shubham/jl/odoo/Elego
pytest tests/test_elegomotors_workflow.py -v 2>&1 | tee logs/test_report.txt
```

Then share the contents of `logs/test_report.txt`.

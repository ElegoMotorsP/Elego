/** @odoo-module **/

/**
 * ElegoMotors — Barcode Capture Wizard: auto-advance + beep
 *
 * Strategy: `input` event debounce (150 ms) detects when the scanner has
 * finished typing. `keydown` Enter capture is a backup that also prevents
 * Odoo's dialog-submit handler from firing prematurely.
 *
 * On each scan (scanner types barcode chars → Enter):
 *   1. `input` events fire per char; debounce resets on each one.
 *   2. 150 ms after the last char, the debounce fires → beep + focus next.
 *   3. The `keydown` Enter listener (capture) fires on the Enter key:
 *      - prevents form submit (ev.preventDefault)
 *      - stops propagation so Odoo's dialog handler doesn't fire
 *      - clears the debounce and advances immediately (no extra 150 ms wait)
 *
 * Req 4: x_auto_scan checkbox disables auto-advance when unchecked.
 *        Enter still prevents form submit but does not move focus.
 */

function playBeep() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = "sine";
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.4, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.15);
    } catch (e) {
        console.warn("ElegoMotors barcode: Web Audio unavailable", e);
    }
}

const BARCODE_FIELDS = [
    "x_motor_serial",
    "x_battery_serial",
    "x_controller_serial",
    "x_charger_serial",
];

// Global Production Scan wizard: full 5-column scan order.
// Cursor starts at Model and auto-advances column by column; after the
// controller of the LAST row is scanned the wizard confirms itself
// (generates serials, closes MOs FIFO, prints labels).
const GLOBAL_SCAN_FIELDS = [
    "x_model_code",
    "x_color_code",
    "x_chassis_serial",
    "x_motor_serial",
    "x_controller_serial",
];

function isAutoScan(dialog) {
    const checkbox = dialog.querySelector('[name="x_auto_scan"] input[type="checkbox"]');
    return checkbox ? checkbox.checked : true;
}

function isGlobalScanDialog(dialog) {
    return !!dialog.querySelector('[name="x_model_code"]');
}

/** All data rows complete? Committed rows show cell text; the row being
 *  edited exposes inputs instead. */
function allGlobalRowsComplete(dialog) {
    const rows = dialog.querySelectorAll(".o_data_row");
    if (!rows.length) return false;
    for (const row of rows) {
        for (const name of GLOBAL_SCAN_FIELDS) {
            const cell = row.querySelector(`[name="${name}"]`);
            if (!cell) return false;
            const input = cell.querySelector("input");
            const value = input ? input.value : cell.textContent;
            if (!value || !value.trim()) return false;
        }
    }
    return true;
}

function autoConfirmGlobalScan(dialog) {
    // Give Odoo time to commit the last cell, then re-check and confirm.
    setTimeout(() => {
        if (!allGlobalRowsComplete(dialog)) return;
        const btn = dialog.querySelector('footer button[name="action_confirm"]');
        if (btn) btn.click();
    }, 300);
}

/** Continuous mode: on a fresh window (or right after a batch resets the
 *  rows), enter edit mode on the first row's Model cell and focus it so the
 *  operator can keep scanning without any clicks. Only fires when every row
 *  is completely empty and nothing is being edited. */
function autoFocusFirstCell(dialog) {
    if (dialog.querySelector(".o_selected_row")) return;
    if (dialog._elego_focus_pending) return;
    const rows = dialog.querySelectorAll(".o_data_row");
    if (!rows.length) return;
    for (const row of rows) {
        for (const name of GLOBAL_SCAN_FIELDS) {
            const cell = row.querySelector(`[name="${name}"]`);
            if (cell && cell.textContent.trim()) return;
        }
    }
    dialog._elego_focus_pending = true;
    const firstCell = rows[0].querySelector(`[name="${GLOBAL_SCAN_FIELDS[0]}"]`);
    if (firstCell) firstCell.click();
    setTimeout(() => {
        const input = dialog.querySelector(
            `.o_selected_row [name="${GLOBAL_SCAN_FIELDS[0]}"] input`
        );
        if (input) {
            input.focus();
            input.select();
        }
        dialog._elego_focus_pending = false;
    }, 120);
}

function attachBarcodeHandlers(dialog) {
    const isGlobal = isGlobalScanDialog(dialog);
    const fieldNames = isGlobal ? GLOBAL_SCAN_FIELDS : BARCODE_FIELDS;
    const inputs = fieldNames
        .map((name) => dialog.querySelector(`[name="${name}"] input`))
        .filter(Boolean);

    if (!inputs.length || inputs[0]._elego_barcode) return;

    inputs.forEach((input, idx) => {
        input._elego_barcode = true;
        let debounceTimer = null;

        function advance() {
            clearTimeout(debounceTimer);
            debounceTimer = null;
            if (!input.value) return;
            playBeep();
            // Req 4: only advance focus when Auto-Advance is enabled
            if (isAutoScan(dialog) && idx < inputs.length - 1) {
                input.blur(); // commits current value into Odoo's record
                setTimeout(() => {
                    inputs[idx + 1].focus();
                    inputs[idx + 1].select();
                }, 30);
            } else if (isGlobal && idx === inputs.length - 1) {
                // Last column scanned: if every row is complete, the wizard
                // confirms itself (auto-close + FIFO deduction + label print).
                input.blur();
                autoConfirmGlobalScan(dialog);
            }
        }

        // Primary: debounce on `input` — fires after scanner finishes typing
        input.addEventListener("input", () => {
            clearTimeout(debounceTimer);
            if (!input.value) return;
            debounceTimer = setTimeout(advance, 150);
        });

        // Backup: intercept Enter key (capture phase) to prevent form submit
        // and advance immediately without waiting for the 150 ms debounce
        input.addEventListener(
            "keydown",
            (ev) => {
                if (ev.key !== "Enter") return;
                ev.stopImmediatePropagation();
                ev.preventDefault();
                advance();
            },
            true
        );
    });
}

/**
 * Serial-scan wizards (delivery "Scan Bike Serials" + invoice fallback):
 * a single scan column across multiple unit rows. After each scan the
 * cursor advances to the NEXT ROW's serial field automatically, so Amit
 * can scan unit after unit without touching the mouse.
 */
function attachSerialRowHandlers(dialog) {
    const input = dialog.querySelector('.o_selected_row [name="scanned_serial"] input');
    if (!input || input._elego_barcode) return;
    input._elego_barcode = true;
    let debounceTimer = null;

    function advance() {
        clearTimeout(debounceTimer);
        debounceTimer = null;
        if (!input.value) return;
        playBeep();
        const row = input.closest(".o_data_row");
        const rows = Array.from(dialog.querySelectorAll(".o_data_row"));
        const idx = rows.indexOf(row);
        input.blur(); // commits the value into Odoo's record
        setTimeout(() => {
            const newRows = dialog.querySelectorAll(".o_data_row");
            if (idx < 0 || idx + 1 >= newRows.length) return;
            const cell = newRows[idx + 1].querySelector('[name="scanned_serial"]');
            if (!cell) return;
            cell.click(); // enter edit mode on the next unit's row
            setTimeout(() => {
                const next = dialog.querySelector(
                    '.o_selected_row [name="scanned_serial"] input'
                );
                if (next) {
                    next.focus();
                    next.select();
                }
            }, 120);
        }, 120);
    }

    input.addEventListener("input", () => {
        clearTimeout(debounceTimer);
        if (!input.value) return;
        debounceTimer = setTimeout(advance, 150);
    });
    input.addEventListener(
        "keydown",
        (ev) => {
            if (ev.key !== "Enter") return;
            ev.stopImmediatePropagation();
            ev.preventDefault();
            advance();
        },
        true
    );
}

/** Fresh serial-scan dialog: enter edit mode on the first row's serial cell
 *  so scanning can start immediately without a click. */
function autoFocusFirstSerialCell(dialog) {
    if (dialog.querySelector(".o_selected_row")) return;
    if (dialog._elego_focus_pending) return;
    const rows = dialog.querySelectorAll(".o_data_row");
    if (!rows.length) return;
    for (const row of rows) {
        const cell = row.querySelector('[name="scanned_serial"]');
        if (cell && cell.textContent.trim()) return; // scans already present
    }
    dialog._elego_focus_pending = true;
    const firstCell = rows[0].querySelector('[name="scanned_serial"]');
    if (firstCell) firstCell.click();
    setTimeout(() => {
        const input = dialog.querySelector(
            '.o_selected_row [name="scanned_serial"] input'
        );
        if (input) {
            input.focus();
            input.select();
        }
        dialog._elego_focus_pending = false;
    }, 120);
}

const observer = new MutationObserver(() => {
    const dialog = document.querySelector(".o_dialog");
    if (!dialog) return;
    if (dialog.querySelector('[name="scanned_serial"]')) {
        autoFocusFirstSerialCell(dialog);
        attachSerialRowHandlers(dialog);
        return;
    }
    if (
        !dialog.querySelector('[name="x_motor_serial"]') &&
        !dialog.querySelector('[name="x_model_code"]')
    ) return;
    if (isGlobalScanDialog(dialog)) {
        autoFocusFirstCell(dialog);
    }
    attachBarcodeHandlers(dialog);
});

function startObserving() {
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startObserving);
} else {
    startObserving();
}

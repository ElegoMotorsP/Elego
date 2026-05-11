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

function isAutoScan(dialog) {
    const checkbox = dialog.querySelector('[name="x_auto_scan"] input[type="checkbox"]');
    return checkbox ? checkbox.checked : true;
}

function attachBarcodeHandlers(dialog) {
    const inputs = BARCODE_FIELDS
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

const observer = new MutationObserver(() => {
    const dialog = document.querySelector(".o_dialog");
    if (!dialog || !dialog.querySelector('[name="x_motor_serial"]')) return;
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

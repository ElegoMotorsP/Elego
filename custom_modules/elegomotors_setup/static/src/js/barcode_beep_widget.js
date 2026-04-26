/** @odoo-module **/

/**
 * ElegoMotors — Barcode Capture Wizard: auto-advance + beep
 *
 * MutationObserver watches for the barcode wizard dialog to appear, then
 * attaches keydown handlers directly to the 3 barcode input fields.
 *
 * On each scan (barcode text + Enter from USB scanner):
 *   1. stopPropagation/preventDefault — blocks Odoo's dialog-save handler
 *   2. blur() current input           — commits value into Odoo's record
 *   3. 50 ms later: focus+select next input
 *   4. playBeep()                     — audible confirmation
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

const BARCODE_FIELDS = ["x_motor_serial", "x_battery_serial", "x_controller_serial"];

function attachBarcodeHandlers(dialog) {
    const inputs = BARCODE_FIELDS
        .map((name) => dialog.querySelector(`[name="${name}"] input`))
        .filter(Boolean);

    if (!inputs.length) return;
    if (inputs[0]._elego_barcode) return; // already attached

    inputs.forEach((input, idx) => {
        input._elego_barcode = true;
        input.addEventListener(
            "keydown",
            (ev) => {
                if (ev.key !== "Enter" || !ev.target.value) return;
                ev.stopPropagation();
                ev.preventDefault();
                playBeep();
                if (idx < inputs.length - 1) {
                    ev.target.blur(); // commit value to Odoo record
                    setTimeout(() => {
                        inputs[idx + 1].focus();
                        inputs[idx + 1].select();
                    }, 50);
                }
            },
            true // capture phase — fires before Odoo's own Enter handlers
        );
    });
}

const observer = new MutationObserver(() => {
    const dialog = document.querySelector(".o_dialog");
    if (!dialog) return;
    if (!dialog.querySelector('[name="x_motor_serial"]')) return;
    attachBarcodeHandlers(dialog);
});

// Defer observation until body is a real DOM Node (Odoo bundle runs before DOMContentLoaded)
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

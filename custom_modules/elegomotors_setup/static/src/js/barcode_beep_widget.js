/** @odoo-module **/

/**
 * ElegoMotors — Barcode Capture Wizard: auto-advance + beep
 *
 * Uses MutationObserver to detect when the barcode wizard dialog opens,
 * then attaches keydown handlers directly to the 3 barcode input fields.
 *
 * Flow per scan:
 *   scanner types barcode → Enter keydown fires → we intercept (capture phase)
 *   → stopPropagation + preventDefault (blocks Odoo's dialog-save handler)
 *   → blur() current input  (commits value into Odoo's reactive record)
 *   → 50ms later: focus + select next input
 *   → playBeep() confirms the scan audibly
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
    // Resolve inputs for all 3 barcode fields in DOM order
    const inputs = BARCODE_FIELDS
        .map((name) => dialog.querySelector(`[name="${name}"] input`))
        .filter(Boolean);

    if (!inputs.length) return;
    // Guard: skip if already attached to the first input (avoids duplicate after re-render)
    if (inputs[0]._elego_barcode) return;

    inputs.forEach((input, idx) => {
        input._elego_barcode = true;
        input.addEventListener(
            "keydown",
            (ev) => {
                if (ev.key !== "Enter") return;
                // Only advance if there is a value (empty Enter → ignore)
                if (!ev.target.value) return;

                ev.stopPropagation();
                ev.preventDefault();

                playBeep();

                if (idx < inputs.length - 1) {
                    const next = inputs[idx + 1];
                    // blur() triggers Odoo's field-commit (saves value to record)
                    ev.target.blur();
                    setTimeout(() => {
                        next.focus();
                        next.select();
                    }, 50);
                }
                // On last field: do nothing extra — Confirm button stays as the next action
            },
            true  // capture phase: fires before Odoo's own Enter handlers
        );
    });
}

// Watch the DOM for the barcode wizard dialog to appear (or re-render after onchange)
const observer = new MutationObserver(() => {
    const dialog = document.querySelector(".o_dialog");
    if (!dialog) return;
    // Only act when our specific wizard is open
    if (!dialog.querySelector('[name="x_motor_serial"]')) return;
    attachBarcodeHandlers(dialog);
});

observer.observe(document.body, { childList: true, subtree: true });
